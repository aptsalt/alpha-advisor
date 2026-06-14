"""Agentic retrieval — the core of 'Agentic RAG' vs plain RAG.

Plain RAG: embed query → top-k → stuff into prompt. One shot, no judgement.
Agentic RAG (this node + its conditional edge):
    1. pick sources   — query BOTH the vector store (prose) and the graph (structure)
    2. grade           — score each retrieved doc for actual relevance to the question
    3. decide          — if the graded evidence is too weak, REWRITE the query and RETRY
                         (bounded by MAX_RETRIEVE_RETRIES); otherwise proceed
This loop is what lets the system recover from a bad first retrieval instead of
confidently answering from irrelevant context — the failure mode that makes naive RAG
unsafe in a regulated setting.
"""
from __future__ import annotations

from .. import audit, config, corpus, llm
from ..state import AdvisorState

_GRADE_SYS = ("[TASK:grade_doc] Score how relevant the DOCUMENT is to the QUESTION on a "
              "scale of 0.0 to 1.0. Reply with only the number.")
_REWRITE_SYS = ("[TASK:rewrite_query] The previous retrieval was too weak. Rewrite the "
                "QUERY to be broader and richer in domain terms. Reply with only the new query.")


def _grade(question: str, doc: dict) -> float:
    raw = llm.chat(_GRADE_SYS, f"QUESTION:{question}\nDOCUMENT:{doc['title']}. {doc['text']}")
    try:
        return max(0.0, min(1.0, float(raw.strip().split()[0])))
    except (ValueError, IndexError):
        return 0.0


def retrieve_node(state: AdvisorState) -> dict:
    query = state.get("query", state["request"])
    client_id = state.get("client_id", "")
    retries = state.get("retries", 0)

    # 1. pick sources — vector (prose) + graph (this client's structure)
    candidates = corpus.vector_store().search(query, config.RETRIEVE_TOP_K)
    if client_id:
        candidates += corpus.knowledge_graph().as_facts(client_id)

    # 2. grade each candidate; keep the ones above threshold
    graded = []
    for c in candidates:
        rel = _grade(query, c)
        if rel >= config.GRADE_THRESHOLD:
            graded.append({**c, "score": round(rel, 3)})
    graded.sort(key=lambda d: -d["score"])
    graded = graded[: config.RETRIEVE_TOP_K + 2]  # allow a few graph facts alongside prose

    mean = round(sum(d["score"] for d in graded) / len(graded), 3) if graded else 0.0
    audit.log("retrieve", {"query": query, "kept": len(graded), "mean_grade": mean,
                           "retry": retries}, run_id=client_id)

    return {
        "docs": graded,
        "retrieval_grade": mean,
        "retries": retries + 1,
        "trace": [{"node": "retrieve", "query": query, "kept": len(graded), "mean_grade": mean,
                   "attempt": retries + 1}],
    }


def rewrite_node(state: AdvisorState) -> dict:
    """Only runs when the grade gate sends us back. Broadens the query, then retrieval reruns."""
    new_q = llm.chat(_REWRITE_SYS, f"QUERY:{state.get('query','')}").strip()
    audit.log("rewrite_query", {"from": state.get("query", ""), "to": new_q},
              run_id=state.get("client_id", ""))
    return {"query": new_q, "trace": [{"node": "rewrite", "new_query": new_q}]}


def should_retry(state: AdvisorState) -> str:
    """Conditional edge after retrieval: retry (rewrite) if evidence is weak and we have
    budget left, else move on to tools/compliance."""
    weak = state.get("retrieval_grade", 0.0) < config.GRADE_THRESHOLD
    has_budget = state.get("retries", 0) <= config.MAX_RETRIEVE_RETRIES
    has_docs = bool(state.get("docs"))
    if weak and has_budget and not has_docs:
        return "rewrite"
    return "proceed"
