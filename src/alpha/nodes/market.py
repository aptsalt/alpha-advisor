"""Market-data tool node — the 'tool integration' line of the JD.

A deterministic synthetic feed standing in for a Bloomberg/Refinitiv/market-data API.
Modelled as a tool the agent calls (not free text the model hallucinates) so the figures
are real data the rest of the graph can act on and the audit log can record verbatim.
In production: swap this function body for the real client; the node contract is unchanged.
"""
from __future__ import annotations

from .. import audit, corpus
from ..state import AdvisorState

# Synthetic quotes/returns keyed by security id (stable, illustrative).
_QUOTES = {
    "GLX": {"price": 102.4, "ytd_return": 0.071, "vol_30d": 0.12},
    "AGG": {"price": 98.1, "ytd_return": 0.018, "vol_30d": 0.04},
    "NFE": {"price": 14.8, "ytd_return": -0.142, "vol_30d": 0.39},
    "TQQ": {"price": 61.2, "ytd_return": 0.224, "vol_30d": 0.31},
}


def market_node(state: AdvisorState) -> dict:
    client_id = state.get("client_id", "")
    if not client_id:
        return {"market": {}, "trace": [{"node": "market", "skipped": "no client"}]}

    holdings = corpus.knowledge_graph().holdings(client_id)
    rows = []
    for h in holdings:
        q = _QUOTES.get(h["security_id"], {})
        rows.append({
            "security": h["security"],
            "security_id": h["security_id"],
            "weight": h["weight"],
            "price": q.get("price"),
            "ytd_return": q.get("ytd_return"),
            "vol_30d": q.get("vol_30d"),
        })
    portfolio_ytd = round(sum((r["ytd_return"] or 0) * r["weight"] for r in rows), 4)
    market = {"holdings": rows, "portfolio_ytd_return": portfolio_ytd}
    audit.log("market_tool", {"n_holdings": len(rows), "portfolio_ytd": portfolio_ytd},
              run_id=client_id)
    return {"market": market,
            "trace": [{"node": "market", "n_holdings": len(rows), "portfolio_ytd": portfolio_ytd}]}
