# ALPHA Advisor — Architecture & JD Mapping

A multi-agent wealth-advisory copilot that prepares a client portfolio review **under
human supervision**. Built to make every line of the *Agentic AI / Agentic RAG Engineer*
posting a feature you can point at and explain.

## The orchestration graph (the spine)

```
 START
   │
   ▼
 [plan]            classify intent · resolve client · decompose into sub-tasks   (ReAct: reason)
   │
   ▼
 [input_guard] ── blocked ──▶ [refuse] ──▶ END     PII redaction + disallowed-intent block (governance, in)
   │ ok
   ▼
 [retrieve] ◀───────┐        vector store (prose) + knowledge graph (structure)
   │     │          │        grade every doc for relevance
   │     └─ weak ──▶ [rewrite]   broaden query, retry (≤ MAX_RETRIES)   ← Agentic RAG loop
   │ proceed
   ▼
 [market]          synthetic market-data tool call (holdings, returns, vol)   (tool integration)
   │
   ▼
 [compliance]      suitability · restricted-list · concentration  → pass/warn/fail   (governance)
   │
   ▼
 [draft]           compose the cited briefing from graded evidence              (grounding)
   │
   ▼
 [output_guard]    citations present? PII leaked? disclaimer attached?          (governance, out)
   │
   ▼
 [approval]        interrupt() → advisor approves / edits / rejects             (human-in-the-loop)
   │
   ├─ approved/edited ─▶ [finalize] ─▶ END
   └─ rejected ────────▶ [discard]  ─▶ END

 Every node writes an append-only, hash-chained audit record.                   (auditability)
```

## Each JD requirement → where it lives

| JD requirement | In ALPHA Advisor |
|---|---|
| **Agentic AI / Agentic RAG** | `nodes/retrieve.py` — retrieve → **grade** → **rewrite & retry** loop via a conditional edge (`should_retry`). Not one-shot RAG. |
| **LangGraph** (or AutoGen/CrewAI/SK) | `graph.py` — `StateGraph`, conditional edges, `interrupt()`, checkpointer. The same flow in the other three frameworks: `docs/frameworks.md`. |
| **Strong Python** | Typed `AdvisorState`, pure-ish node functions, provider abstraction, `lru_cache`d corpus, dataclasses. |
| **RAG architectures + vector databases** | `rag/vectorstore.py` — embed + cosine top-k behind a `VectorStore` interface (swap Chroma / PGVector / Azure AI Search). |
| **Graph RAG + knowledge graphs** | `rag/graphrag.py` — `client→holds→security→issuer / →sector` graph; multi-hop queries (issuer/sector concentration, restricted-list hits) vectors can't answer. |
| **APIs / enterprise tools** | `nodes/market.py` — market data modelled as a *tool call*, not model free-text. |
| **AI governance, guardrails, explainability, compliance** | `nodes/guardrails.py` (in/out guards, PII), `nodes/compliance.py` (3 checks with reasons), citations on every claim. |
| **Human-in-the-loop + auditability** | `nodes/approval.py` (`interrupt()` + `Command(resume=...)`), `audit.py` (hash-chained JSONL, `verify()`). |
| **Scalable cloud deployment** | Stateless graph + external checkpointer → containerize; `docs/frameworks.md` covers Azure Container Apps + tracing. |
| **Azure OpenAI** | `llm.py` Azure provider (chat + embeddings); `ALPHA_PROVIDER=azure`. |

## Why these design choices (the interview answers)

- **One typed state object, nodes return partials.** Makes the run inspectable and the
  audit trail a byproduct, not extra work. In a regulated setting, *explainability is the
  architecture*, not a feature bolted on top.
- **Agentic retrieval over naive RAG.** Naive RAG answers confidently from whatever it
  retrieved. The grade→rewrite→retry loop lets the system notice weak evidence and try
  again — the difference between "plausible" and "defensible" in wealth management.
- **Vectors *and* a graph.** Prose questions ("what's the suitability policy?") are vector
  search; structural questions ("how concentrated is this client in one issuer?") are graph
  traversals. Agentic RAG routes to both and grades the combined evidence.
- **Guardrails on both ends + a hard policy gate.** The model never sees client PII, and a
  prohibited request never reaches retrieval or client data at all (it routes to `refuse`).
- **The human is the last actor.** `interrupt()` persists full state and waits. The agent
  proposes; the advisor disposes. Nothing reaches a client without a recorded human decision.
- **Provider-portable.** mock / Ollama / Azure are a config switch — the graph, guardrails,
  and audit logic are identical, so the same system can run fully on-prem.
