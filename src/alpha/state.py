"""The shared graph state. Every LangGraph node receives this and returns a partial
update; LangGraph merges the partials. Keeping one explicit, typed state object is
what makes the agent auditable — every field here shows up in the trace and audit log.
"""
from __future__ import annotations

from typing import Annotated, Any, Literal, TypedDict
from operator import add


class Citation(TypedDict):
    marker: str          # e.g. "[1]"
    source_id: str       # document or graph node id
    title: str
    snippet: str


class RetrievedDoc(TypedDict):
    source_id: str
    title: str
    text: str
    origin: Literal["vector", "graph"]
    score: float


class ComplianceFinding(TypedDict):
    check: str           # "suitability" | "restricted_list" | "concentration"
    status: Literal["pass", "warn", "fail"]
    detail: str


class AdvisorState(TypedDict, total=False):
    # ── Inputs ────────────────────────────────────────────────────────────────
    request: str                 # the advisor's natural-language ask
    client_id: str               # resolved target client

    # ── Plan ──────────────────────────────────────────────────────────────────
    plan: list[str]              # decomposed sub-tasks
    intent: str                  # classified intent (portfolio_review | holding_lookup | general)

    # ── Guardrails ────────────────────────────────────────────────────────────
    safe_request: str            # PII-redacted / policy-checked request actually sent to the LLM
    input_guard: dict[str, Any]  # what the input guard did

    # ── Agentic retrieval ─────────────────────────────────────────────────────
    query: str                   # current (possibly rewritten) retrieval query
    retries: int                 # retrieval attempts so far
    docs: list[RetrievedDoc]     # graded, accepted documents
    retrieval_grade: float       # mean relevance of accepted docs

    # ── Tools ─────────────────────────────────────────────────────────────────
    market: dict[str, Any]       # market-data tool output (synthetic)

    # ── Compliance ────────────────────────────────────────────────────────────
    compliance: list[ComplianceFinding]
    compliance_status: Literal["pass", "warn", "fail"]

    # ── Rebalance (proposed trades to bring the book back within policy) ───────
    rebalance: dict[str, Any]

    # ── Evaluation (LLM-as-judge scores on the finished briefing) ─────────────
    evaluation: dict[str, Any]

    # ── Drafting ──────────────────────────────────────────────────────────────
    draft: str
    citations: list[Citation]
    output_guard: dict[str, Any]

    # ── Human-in-the-loop ─────────────────────────────────────────────────────
    decision: Literal["approved", "rejected", "edited"]
    advisor_note: str
    final: str

    # ── Observability ─────────────────────────────────────────────────────────
    trace: Annotated[list[dict[str, Any]], add]  # append-only step log (reducer = list concat)
