# Interview Q&A — Agentic AI / Agentic RAG Engineer (ALPHA Wealth)

Senior-level framings, each anchored to something you actually built in this repo so you
answer from experience, not theory. Bring the running demo.

## Agentic RAG

**Q. Naive RAG vs Agentic RAG — and why it matters here?**
Naive RAG embeds the query, pulls top-k, and generates — it will answer confidently from
irrelevant context. Agentic RAG makes retrieval a *decision*: my retrieve node grades each
retrieved doc for relevance and, if the evidence is weak, rewrites the query and retries
(bounded). In wealth management that's the line between a plausible answer and a defensible
one — I'd rather the agent notice it has bad evidence and try again than ground a client
briefing in the wrong policy. *(`nodes/retrieve.py`, `should_retry` edge.)*

**Q. How do you stop the retry loop from running forever?**
A budget (`MAX_RETRIEVE_RETRIES`) and a grade threshold, both in config. The conditional edge
only routes back to rewrite if the evidence is weak *and* there's budget left *and* we still
have no accepted docs. Otherwise it proceeds — a weak-but-best-effort answer still goes
through compliance and a human, who can reject it.

**Q. When do you use a graph vs a vector store?**
Vectors for prose similarity ("what's the suitability policy?"). A graph for structural,
multi-hop questions ("how concentrated is this client in a single issuer or sector?",
"does any holding touch the restricted list?"). My demo catches a 78% issuer concentration
that's invisible to vector search because it requires *aggregating across two funds from the
same issuer* — a graph traversal, not a similarity match. *(`rag/graphrag.py`.)*

## Governance, guardrails, compliance

**Q. Where do guardrails live and why both ends?**
Input guard before the model: redact PII (the model never needs an SSN to reason about
allocation — minimizing what it sees is itself a control) and hard-block prohibited intents,
which route straight to a refusal without touching retrieval or client data. Output guard
after drafting, before any human sees it: verify citations exist, scrub any leaked PII,
attach the advice disclaimer. *(`nodes/guardrails.py`.)*

**Q. How is the agent explainable / auditable?**
One typed state object flows through the graph; every node appends a trace entry and writes
an append-only, **hash-chained** audit record (each line's hash chains to the previous, so a
deletion or edit is detectable; `audit.verify()` re-walks the chain). Every factual line in
the briefing carries a citation back to a source id. So for any output I can show: what ran,
on what evidence, what compliance found, and which human approved it. *(`audit.py`.)*

**Q. A compliance check fails — what happens?**
It doesn't silently block; it sets a `fail` status with a human-readable reason, that becomes
cited evidence in the briefing, and the run still pauses for a human. A restricted-list hit
is a `fail`; a mandate drift is a `warn`. The human sees all findings at the approval gate and
decides. Autonomy with a hard human backstop, not autonomy instead of one.

## Human-in-the-loop

**Q. How does the human-in-the-loop actually work, technically?**
LangGraph `interrupt()` inside the approval node. It persists the full graph state to the
checkpointer and surfaces an approval payload (draft + citations + compliance findings). The
process can exit entirely; when the advisor decides, I resume with `Command(resume={...})`
and the node's return value becomes the decision, which a conditional edge routes to finalize
or discard. With a Postgres checkpointer this survives restarts — a run can wait hours for an
advisor. *(`nodes/approval.py`, `run.py`.)*

## Architecture / scaling / cloud

**Q. How would you deploy and scale this on Azure?**
The graph is stateless; durability lives in the checkpointer. Swap `InMemorySaver` for the
Postgres checkpointer, containerize, run on Azure Container Apps behind an API, secrets in Key
Vault, `ALPHA_PROVIDER=azure` for Azure OpenAI, Azure AI Search as the vector store, Neo4j (or
Cosmos DB Gremlin) for the graph, LangSmith/OpenTelemetry tracing per node, and the audit log
to immutable (WORM) storage. Horizontal scale because any worker can resume any paused run from
the shared checkpointer. *(`docs/frameworks.md` → Production hardening.)*

**Q. Why LangGraph over AutoGen / CrewAI / Semantic Kernel?**
The workflow is a stateful graph with conditional loops and a durable human pause — LangGraph's
exact model, and it gives me deterministic, inspectable, resumable control, which a regulated
setting needs. AutoGen's emergent multi-agent chat is harder to audit; CrewAI is great for
quick role pipelines; Semantic Kernel is the natural pick in an Azure/.NET-first bank. I keep
the orchestration contract fixed so the framework is swappable. *(`docs/frameworks.md`.)*

**Q. Single agent here, or multi-agent?**
Specialized nodes (planner, retriever, compliance, writer) coordinated by an explicit graph —
the supervisor/graph pattern. I chose explicit edges over free-form agent-to-agent chat
precisely because auditability and bounded behavior matter more than emergent flexibility in
wealth management. I can speak to the conversational multi-agent pattern (AutoGen) as the
alternative and why I didn't pick it here.

## Likely curveballs

- **"How do you prevent hallucinated numbers?"** Market figures come from a *tool*, not model
  text; the draft node only cites provided evidence; the output guard rejects an uncited draft.
- **"PII / data residency?"** PII redacted pre-model; provider-portable so it can run fully
  on-prem/in-VPC with Ollama or a self-hosted model — no data leaves the boundary.
- **"What breaks first at scale?"** The in-memory vector store and checkpointer — both are
  deliberately behind interfaces so the swap to Azure AI Search + Postgres checkpointer is an
  adapter change, called out in the code comments.
