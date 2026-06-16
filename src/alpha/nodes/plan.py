"""Supervisor / planner node. Classifies intent, resolves the target client, and lays
out the sub-tasks. This is the 'reasoning' half of the ReAct loop at the top of the run:
decide what work the request implies before any tool fires."""
from __future__ import annotations

from .. import audit, llm
from ..data import synth
from ..state import AdvisorState

_SYS = ("[TASK:classify_intent] You are a wealth-advisory planning agent. Classify the "
        "advisor's request as one of: portfolio_review, holding_lookup, general. "
        "Reply with only the label.")


def plan_node(state: AdvisorState) -> dict:
    request = state["request"]
    intent = llm.chat(_SYS, request, fast=True).strip().split()[0].lower()
    if intent not in {"portfolio_review", "holding_lookup", "general"}:
        intent = "portfolio_review"

    client_id = state.get("client_id") or synth.resolve_client(request) or ""

    plan = {
        "portfolio_review": [
            "retrieve relevant policies and the client's portfolio structure",
            "pull current market data for the holdings",
            "run suitability, restricted-list and concentration checks",
            "draft a cited client briefing",
            "obtain advisor approval before finalizing",
        ],
        "holding_lookup": [
            "retrieve the relevant factsheet / policy",
            "draft a cited answer",
            "obtain advisor approval",
        ],
        "general": ["retrieve relevant context", "draft a cited answer", "advisor approval"],
    }[intent]

    audit.log("plan", {"intent": intent, "client_id": client_id, "plan": plan},
              run_id=state.get("client_id", ""))
    return {
        "intent": intent,
        "client_id": client_id,
        "plan": plan,
        "query": request,
        "retries": 0,
        "trace": [{"node": "plan", "intent": intent, "client_id": client_id or "unresolved"}],
    }
