"""Human-in-the-loop approval node — the JD's 'human-in-the-loop AI workflows'.

This is a real LangGraph `interrupt()`: the graph pauses, persists its full state to the
checkpointer, and surfaces an approval request to the caller. Nothing is finalized until
a human resumes the run with a decision via `Command(resume=...)`. In wealth management
the autonomous agent is never the last actor before the client — the advisor is.

The interrupt payload is everything the advisor needs to decide: the draft, the citation
list, and the compliance findings (especially any warn/fail). On resume, the human's
decision (approve / reject / edit) flows back in as the node's return value.
"""
from __future__ import annotations

from langgraph.types import interrupt

from .. import audit
from ..state import AdvisorState


def approval_node(state: AdvisorState) -> dict:
    request = {
        "type": "advisor_approval",
        "client_id": state.get("client_id", ""),
        "compliance_status": state.get("compliance_status", "pass"),
        "compliance": state.get("compliance", []),
        "draft": state.get("draft", ""),
        "citations": state.get("citations", []),
        "instructions": "Approve to finalize, reject to discard, or edit to supply a revised note.",
    }
    audit.log("approval_requested", {"compliance_status": request["compliance_status"]},
              run_id=state.get("client_id", ""))

    # Execution pauses here until the caller resumes with Command(resume={...}).
    response = interrupt(request)

    # `response` is whatever the human passed to Command(resume=...).
    decision = (response or {}).get("decision", "approved")
    note = (response or {}).get("note", "")
    audit.log("approval_decision", {"decision": decision, "note": note},
              run_id=state.get("client_id", ""))
    return {"decision": decision, "advisor_note": note,
            "trace": [{"node": "approval", "decision": decision}]}


def route_after_approval(state: AdvisorState) -> str:
    return "finalize" if state.get("decision") in ("approved", "edited") else "discard"
