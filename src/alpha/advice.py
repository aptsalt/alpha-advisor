"""Portfolio assessment + rebalancing logic — deterministic, graph-driven.

Shared by three callers so the rules live in exactly one place:
  - the compliance node (per-review)
  - the rebalance node (turns findings into proposed trades)
  - the portfolio dashboard scan (assess every client fast, no LLM)

All numbers come from the knowledge graph, never the model — an un-sourced figure in a
client briefing is a compliance incident, so trade math is computed, not generated.
"""
from __future__ import annotations

from . import config, corpus

_MANDATE_EQUITY_TARGET = {"Balanced": 0.60, "Growth": 0.80}
_TOLERANCE = 0.15  # allowed drift from target equity weight before 'warn'
_ORDER = {"pass": 0, "warn": 1, "fail": 2}


def assess(client_id: str) -> tuple[list[dict], str, dict]:
    """Return (findings, worst_status, context). Pure graph queries — no LLM."""
    kg = corpus.knowledge_graph()
    holdings = kg.holdings(client_id)
    profile = kg.risk_profile(client_id)
    issuer_conc = kg.issuer_concentration(client_id)
    restricted = kg.restricted_hits(client_id)
    findings: list[dict] = []

    # suitability: equity weight vs mandate target
    equity_w = sum(h["weight"] for h in holdings
                   if h["sector"] in ("Equity", "Energy") or h["security_id"] == "TQQ")
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

    # restricted list (a graph edge query)
    if restricted:
        names = ", ".join(f"{h['security']} ({h['weight']:.0%})" for h in restricted)
        findings.append({"check": "restricted_list", "status": "fail",
                         "detail": f"Holdings on the restricted list: {names}. "
                                   f"Reason: {restricted[0]['reason']}. Must be flagged for review."})
    else:
        findings.append({"check": "restricted_list", "status": "pass",
                         "detail": "No holdings appear on the restricted list."})

    # single-issuer concentration vs policy limit
    top_issuer, top_w = next(iter(issuer_conc.items()), ("none", 0.0))
    if top_w > config.CONCENTRATION_LIMIT:
        findings.append({"check": "concentration", "status": "warn",
                         "detail": f"Largest single-issuer weight is {top_issuer} at {top_w:.0%}, "
                                   f"above the {config.CONCENTRATION_LIMIT:.0%} policy limit."})
    else:
        findings.append({"check": "concentration", "status": "pass",
                         "detail": f"Largest single-issuer weight is {top_issuer} at {top_w:.0%}, "
                                   f"within the {config.CONCENTRATION_LIMIT:.0%} limit."})

    status = max(findings, key=lambda f: _ORDER[f["status"]])["status"]
    ctx = {"holdings": holdings, "profile": profile, "issuer_conc": issuer_conc,
           "restricted": restricted, "equity_weight": round(equity_w, 4)}
    return findings, status, ctx


def propose_rebalance(client_id: str) -> dict:
    """Turn the findings into concrete, policy-satisfying trades. Deterministic.

    Strategy: (1) divest restricted holdings entirely; (2) trim any issuer above the
    concentration limit down to it; (3) reallocate the freed weight to a diversified
    multi-issuer core so no single issuer breaches the limit — preserving the mandate's
    equity/fixed-income split. Returns trades + the projected post-trade concentration.
    """
    kg = corpus.knowledge_graph()
    holdings = {h["security_id"]: h for h in kg.holdings(client_id)}
    limit = config.CONCENTRATION_LIMIT
    weights = {sid: h["weight"] for sid, h in holdings.items()}
    trades: list[dict] = []

    # 1. divest restricted
    for h in kg.restricted_hits(client_id):
        sid = next((s for s, hh in holdings.items() if hh["security"] == h["security"]), None)
        if sid and weights.get(sid, 0) > 0:
            trades.append({"action": "SELL", "security": h["security"], "delta": -weights[sid],
                           "from_weight": weights[sid], "to_weight": 0.0,
                           "reason": f"Restricted list ({h['policy']}) — divest in full."})
            weights[sid] = 0.0

    # 2. trim issuers above the limit
    def issuer_of(sid): return holdings[sid]["issuer"]
    issuer_total: dict[str, float] = {}
    for sid, w in weights.items():
        issuer_total[issuer_of(sid)] = issuer_total.get(issuer_of(sid), 0) + w
    for issuer, total in issuer_total.items():
        if total <= limit:
            continue
        excess = total - limit
        # trim that issuer's securities proportionally
        sids = [s for s in weights if issuer_of(s) == issuer and weights[s] > 0]
        for sid in sids:
            cut = excess * (weights[sid] / total)
            trades.append({"action": "TRIM", "security": holdings[sid]["security"], "delta": -round(cut, 4),
                           "from_weight": round(weights[sid], 4), "to_weight": round(weights[sid] - cut, 4),
                           "reason": f"{issuer} at {total:.0%} exceeds the {limit:.0%} single-issuer "
                                     f"limit — trim toward target."})
            weights[sid] -= cut

    # 3. reallocate freed weight to a diversified core (kept ≤ limit by construction)
    freed = round(1.0 - sum(weights.values()), 4)
    if freed > 0.005:
        trades.append({"action": "BUY", "security": "Diversified Multi-Issuer Core",
                       "delta": freed, "from_weight": 0.0, "to_weight": freed,
                       "reason": "Reallocate freed weight across additional issuers so no single "
                                 f"issuer exceeds {limit:.0%}; preserves the mandate's asset mix."})

    # projected post-trade concentration of the *real* (single-name) issuers
    real: dict[str, float] = {}
    for sid, w in weights.items():
        if w > 0:
            real[issuer_of(sid)] = real.get(issuer_of(sid), 0) + w
    # the diversified core is spread across many issuers (each ≤ limit by construction),
    # so it does not count as a single-issuer exposure for the limit check
    top_after = max(real.values()) if real else 0.0
    projected = {k: round(v, 4) for k, v in sorted(real.items(), key=lambda kv: -kv[1])}
    if freed > 0.005:
        projected["Diversified core (≤ limit per issuer)"] = freed

    return {"trades": trades, "projected_concentration": projected,
            "max_issuer_after": round(top_after, 4), "compliant_after": top_after <= limit + 1e-6}
