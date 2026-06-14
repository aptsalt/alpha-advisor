"""Terminal nodes: finalize (advisor approved) and discard (advisor rejected).
Both write a closing audit record so every run ends with a recorded human decision."""
from __future__ import annotations

from .. import audit
from ..state import AdvisorState


def finalize_node(state: AdvisorState) -> dict:
    draft = state.get("draft", "")
    note = state.get("advisor_note", "")
    final = draft
    if state.get("decision") == "edited" and note:
        final = draft.rstrip() + f"\n\n---\n**Advisor note:** {note}"
    audit.log("finalized", {"decision": state.get("decision"),
                            "compliance_status": state.get("compliance_status")},
              run_id=state.get("client_id", ""))
    return {"final": final, "trace": [{"node": "finalize", "decision": state.get("decision")}]}


def discard_node(state: AdvisorState) -> dict:
    audit.log("discarded", {"note": state.get("advisor_note", "")},
              run_id=state.get("client_id", ""))
    final = ("Briefing discarded by advisor. Nothing was shared with the client."
             + (f" Reason: {state['advisor_note']}" if state.get("advisor_note") else ""))
    return {"final": final, "trace": [{"node": "discard"}]}
