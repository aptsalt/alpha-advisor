"""Compliance node — three structural checks the graph can answer exactly.

  suitability     : is the client's actual allocation consistent with their documented
                    risk profile? (growth-heavy book under a balanced mandate = mismatch)
  restricted_list : does any holding touch a restricted-list policy edge?
  concentration   : is any single issuer over the policy limit?

Each produces a pass / warn / fail finding with a human-readable reason. The worst
finding sets the run's compliance_status, which later gates the briefing's framing and
is recorded in the audit log. This is where 'guardrails + explainability + compliance
workflows' stop being buzzwords and become graph queries with thresholds.
"""
from __future__ import annotations

from .. import advice, audit
from ..state import AdvisorState


def compliance_node(state: AdvisorState) -> dict:
    client_id = state.get("client_id", "")
    if not client_id:
        return {"compliance": [], "compliance_status": "pass",
                "trace": [{"node": "compliance", "skipped": "no client"}]}

    findings, status, _ = advice.assess(client_id)  # the three checks live in advice.py
    audit.log("compliance", {"status": status, "findings": findings}, run_id=client_id)
    return {"compliance": findings, "compliance_status": status,
            "trace": [{"node": "compliance", "status": status,
                       "checks": {f["check"]: f["status"] for f in findings}}]}
