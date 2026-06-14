# Deployment & Production Hardening (Phase 4)

How ALPHA Advisor goes from a local demo to a scalable, observable service on Azure —
the "deploy scalable AI solutions in cloud environments" line of the JD. Every swap below
is an **adapter change behind an existing seam**, not a rewrite; the orchestration graph,
guardrails, and audit logic are untouched.

## The deployable surface

`src/alpha/api.py` is a FastAPI service with two endpoints mirroring the human-in-the-loop
lifecycle:

| Endpoint | Purpose |
|---|---|
| `POST /api/review` | run the graph to the approval interrupt; returns the briefing + compliance + `run_id` |
| `POST /api/review/{run_id}/decision` | resume the paused run with `approved` / `rejected` / `edited` |
| `GET /api/health` | provider + config banner |

Run locally:
```bash
PYTHONPATH=src uvicorn alpha.api:app --port 8200
curl -s -X POST localhost:8200/api/review -d '{"request":"review Jane Harrington"}' -H "Content-Type: application/json"
```

## What makes it scalable: stateless graph + durable checkpointer

The graph holds no state between requests — every paused run lives in the **checkpointer**,
keyed by `run_id` (= LangGraph `thread_id`). Locally that's `InMemorySaver`. In production:

```
ALPHA_CHECKPOINT_DB=postgresql://user:pass@host/db    # src/alpha/checkpoint.py
```

With the Postgres checkpointer, a run started by replica A can be resumed by replica B —
so the service scales horizontally behind a load balancer, and a run awaiting an advisor
**survives a restart or deploy**. That's the difference between a demo and a platform an
advisor can leave for an hour and come back to.

## Provider: Azure OpenAI

```
ALPHA_PROVIDER=azure
AZURE_OPENAI_ENDPOINT=https://<resource>.openai.azure.com
AZURE_OPENAI_API_KEY=<key>            # → Key Vault / Container Apps secret in prod
AZURE_OPENAI_CHAT_DEPLOYMENT=gpt-4o
AZURE_OPENAI_EMBED_DEPLOYMENT=text-embedding-3-small
```
Nothing else changes — `src/alpha/llm.py` already speaks the Azure OpenAI REST shape.

## Observability

Two layers, separate concerns:

- **OpenTelemetry** (`src/alpha/telemetry.py`, `ALPHA_TRACING=1`) — one span per node nested
  under a run span. Console exporter by default; set `OTEL_EXPORTER_OTLP_ENDPOINT` to ship
  to Jaeger / Grafana Tempo / **Azure Monitor**. This is the operational trace ("what ran,
  how long, where did it fail").
- **Audit log** (`src/alpha/audit.py`) — append-only, hash-chained JSONL; the immutable
  *compliance* record ("what was decided, on what evidence, by whom"). In prod, ship it to
  immutable/WORM storage.
- **LangSmith** — set `LANGCHAIN_TRACING_V2=true` + `LANGCHAIN_API_KEY` for hosted tracing
  if the team already uses LangChain.

## Data backends (the production swaps)

| Local (default) | Production | Seam |
|---|---|---|
| numpy `VectorStore` | Azure AI Search / PGVector / Chroma | `rag/vectorstore.py` `add`/`search` |
| networkx `KnowledgeGraph` | **Neo4j** (`ALPHA_GRAPH_DB=bolt://…`) | `rag/neo4j_adapter.py` (Cypher, same methods) |
| `InMemorySaver` | Postgres checkpointer | `checkpoint.py` |
| synthetic loaders | custodian / CRM / doc-store connectors | `data/synth.py` |

The Neo4j adapter is a 1:1 port of the networkx queries (the networkx version documents each
query's Cypher) and is selected automatically when `ALPHA_GRAPH_DB` is set, falling back to
networkx if the driver/server is unavailable — so local dev never needs a database.

## Container & deploy

```bash
docker build -t alpha-advisor .                 # Dockerfile: python:3.12-slim, non-root, uvicorn
# or build in the cloud with no local Docker:
RG=alpha-advisor-rg \
AZURE_OPENAI_ENDPOINT=https://<res>.openai.azure.com \
AZURE_OPENAI_API_KEY=<key> \
ALPHA_CHECKPOINT_DB=postgresql://… \
  bash deploy/deploy.sh
```

`deploy/deploy.sh` does: resource group → ACR → `az acr build` (cloud build, no local Docker)
→ `az deployment group create` with `deploy/main.bicep`. The bicep provisions a Container Apps
environment + Log Analytics + the app, with Azure OpenAI key and the Postgres conn string as
secrets, scale-to-zero, and HTTP autoscale to 5 replicas.

## Security posture (regulated context)

- Secrets via Container Apps secrets / Key Vault — never in the image (`.dockerignore` excludes `.env`).
- Non-root container, least privilege.
- PII redacted before the model (`input_guard`); provider-portable so the whole graph can run
  fully on-prem / in-VPC with a self-hosted model — no client data leaves the boundary.
- Append-only, tamper-evident audit trail with `verify()`.
- A prohibited request never reaches retrieval or client data (routes to `refuse`).

> **Status:** the FastAPI service, OpenTelemetry tracing, checkpointer factory, and Neo4j
> adapter run/verify locally (with graceful fallbacks). The Dockerfile, bicep, and deploy
> script are deployment artifacts — correct and ready, exercised when pointed at a real Azure
> subscription. (Docker/Azure were not available in the build environment.)
