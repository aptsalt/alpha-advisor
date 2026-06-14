# Agentic Frameworks — LangGraph · AutoGen · CrewAI · Semantic Kernel

The JD names all four. ALPHA Advisor is built on **LangGraph**, but the orchestration —
plan → guard → agentic-retrieve → tools → compliance → draft → human-approval → finalize —
is the durable asset. Each framework would re-implement *that*. Here's how to speak to each.

## The one-paragraph positioning (say this in the interview)

> "I treat the framework as an implementation detail under a fixed orchestration contract.
> LangGraph fit ALPHA Advisor because the workflow is a **stateful graph with conditional
> loops and a durable human-in-the-loop pause** — that's exactly LangGraph's model. If the
> client standardized on Semantic Kernel (common in Azure/.NET shops) or wanted CrewAI's
> role metaphor, the nodes port over; the graph shape, guardrails, and audit logic don't change."

## Side-by-side

| | **LangGraph** | **AutoGen** | **CrewAI** | **Semantic Kernel** |
|---|---|---|---|---|
| Mental model | State machine / graph | Conversing agents | Role-based crew + tasks | Plugins + planner (kernel) |
| Control flow | Explicit nodes & edges, conditional + cycles | Emergent from chat between agents | Sequential / hierarchical process | Planner composes plugin calls |
| Human-in-the-loop | First-class `interrupt()` + checkpointer resume | `UserProxyAgent` / `human_input_mode` | Human-input tasks / callbacks | Manual via filters / function hooks |
| State / durability | Typed shared state + pluggable checkpointers | Conversation history | Task context passing | Kernel memory / context |
| Strengths | Deterministic, inspectable, resumable, cyclic | Flexible multi-agent dialogue, code-exec | Fast to express team workflows | Native Azure/.NET, enterprise plugins |
| Watch-outs | More wiring up front | Emergent flow is harder to audit | Less control over low-level routing | Planner less transparent; C#-first |
| Best fit here | ✅ regulated, auditable, HITL graph | research/brainstorm multi-agent | quick role-based pipelines | Azure-native .NET enterprise |

## The same flow, mapped to each framework

- **LangGraph** (this repo): nodes = functions, edges = control flow, `should_retry`
  conditional edge = the agentic loop, `interrupt()` = the approval gate.
- **AutoGen**: a `GroupChat` of `Planner`, `Retriever`, `Compliance`, `Writer` agents with a
  `UserProxyAgent` for approval; the grade→retry loop becomes the Retriever re-querying until
  a Critic agent signals the evidence is sufficient.
- **CrewAI**: a `Crew` with `researcher` / `compliance_officer` / `writer` roles and a
  hierarchical process; tasks carry context; a human-input task is the approval gate.
- **Semantic Kernel**: retrieval, market-data, and compliance become **plugins**; a planner
  sequences them; a function filter implements the guardrails; approval via a hook before the
  finalize function. Most natural if the bank is Azure/.NET end-to-end.

## RAG vocabulary the interview will probe

- **Naive RAG** — embed query → top-k → stuff context → generate. One shot, no self-check.
- **Agentic RAG** — an agent *decides* what/whether to retrieve, **grades** results, and can
  **rewrite & retry** or pick a different source. (This repo: `nodes/retrieve.py`.)
- **Graph RAG** — retrieve over a knowledge graph; answers multi-hop / structural questions
  (concentration, relationships, lineage) that vector similarity can't. (`rag/graphrag.py`.)
- **Hybrid** — combine vector + graph (+ keyword/BM25); grade and merge. ALPHA Advisor does
  vector + graph and grades the union.

## Production hardening (what changes for the cloud line of the JD)

- **Vector DB**: swap the numpy `VectorStore` for Azure AI Search / PGVector / Chroma (same
  `add`/`search` surface).
- **Graph**: swap the networkx `KnowledgeGraph` for Neo4j; the query methods already document
  their Cypher equivalents.
- **Checkpointer**: swap `InMemorySaver` for the Postgres/Redis checkpointer so paused runs
  (awaiting advisor approval) survive process restarts and scale horizontally.
- **Deploy**: containerize; **Azure Container Apps** (or AKS) behind an API; secrets in Key
  Vault; **LangSmith / OpenTelemetry** tracing on every node; the audit JSONL → an append-only
  store (e.g. immutable blob / WORM).
- **LLM**: `ALPHA_PROVIDER=azure` points at your Azure OpenAI deployments; nothing else changes.
