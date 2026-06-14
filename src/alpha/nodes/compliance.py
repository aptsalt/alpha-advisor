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

from .. import audit, config, corpus
from ..state import AdvisorState, ComplianceFinding

_MANDATE_EQUITY_TARGET = {"Balanced": 0.60, "Growth": 0.80}
_TOLERANCE = 0.15  # allowed drift from target equity weight before 'warn'


def compliance_node(state: AdvisorState) -> dict:
    client_id = state.get("client_id", "")
    findings: list[ComplianceFinding] = []
    if not client_id:
        return {"compliance": [], "compliance_status": "pass",
                "trace": [{"node": "compliance", "skipped": "no client"}]}

    kg = corpus.knowledge_graph()
    holdings = kg.holdings(client_id)
    profile = kg.risk_profile(client_id)

    # ── suitability: equity weight vs mandate target ─────────────────────────
    equity_w = sum(h["weight"] for h in holdings if h["sector"] in ("Equity", "Energy")
                   or h["security_id"] == "TQQ")
    target = _MANDATE_EQUITY_TARGET.get(profile.get("name", ""), 0.60)
    drift = equity_w - target
    if abs(drift) <= _TOLERANCE:
        findings.append({"check": "suitability", "status": "pass",
                         "detail": f"Equity weight {equity_w:.0%} is within tolerance of the "
                                   f"{profile.get('name','?')} target {target:.0%}."})
    else:
        findings.append({"check": "suitability", "status": "warn",
                         "detail": f"Equity weight {equity_w:.0%} drifts {drift:+.0%} from the "
                                   f"{profile.get('name','?')} mandate target of {target:.0%}; "
                                   f"reassess suitability."})

    # ── restricted list (a graph edge query) ─────────────────────────────────
    hits = kg.restricted_hits(client_id)
    if hits:
        names = ", ".join(f"{h['security']} ({h['weight']:.0%})" for h in hits)
        findings.append({"check": "restricted_list", "status": "fail",
                         "detail": f"Holdings on the restricted list: {names}. "
                                   f"Reason: {hits[0]['reason']}. Must be flagged for review."})
    else:
        findings.append({"check": "restricted_list", "status": "pass",
                         "detail": "No holdings appear on the restricted list."})

    # ── single-issuer concentration vs policy limit ──────────────────────────
    conc = kg.issuer_concentration(client_id)
    top_issuer, top_w = next(iter(conc.items()), ("none", 0.0))
    if top_w > config.CONCENTRATION_LIMIT:
        findings.append({"check": "concentration", "status": "warn",
                         "detail": f"Largest single-issuer weight is {top_issuer} at {top_w:.0%}, "
                                   f"above the {config.CONCENTRATION_LIMIT:.0%} policy limit."})
    else:
        findings.append({"check": "concentration", "status": "pass",
                         "detail": f"Largest single-issuer weight is {top_issuer} at {top_w:.0%}, "
                                   f"within the {config.CONCENTRATION_LIMIT:.0%} limit."})

    order = {"pass": 0, "warn": 1, "fail": 2}
    status = max(findings, key=lambda f: order[f["status"]])["status"]
    audit.log("compliance", {"status": status, "findings": findings}, run_id=client_id)
    return {"compliance": findings, "compliance_status": status,
            "trace": [{"node": "compliance", "status": status,
                       "checks": {f["check"]: f["status"] for f in findings}}]}
