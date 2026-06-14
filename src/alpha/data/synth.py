"""Synthetic wealth-management corpus + knowledge graph.

Everything here is fabricated — no real clients, no real PII, no real holdings. That is
the point: the platform must be demoable and testable without touching regulated data.
In production these loaders are replaced by connectors to the custodian, the CRM, the
document store, and the market-data feed; the rest of the system does not change.

Produces:
  - CLIENTS: profiles with (synthetic) PII so we can show the input guard redacting it
  - DOCUMENTS: IPS, fund factsheets, firm policies, restricted list  → vector store
  - build_graph(): the client→holding→issuer→sector knowledge graph  → Graph RAG
"""
from __future__ import annotations

from ..rag.graphrag import KnowledgeGraph

# ── Clients (synthetic; includes fake PII to exercise the input guard) ────────
CLIENTS = {
    "C-1001": {
        "client_id": "C-1001",
        "name": "Jane Harrington",
        "email": "jane.harrington@example.com",
        "phone": "+1-416-555-0142",
        "ssn": "123-45-6789",
        "risk": "balanced",
    },
    "C-1002": {
        "client_id": "C-1002",
        "name": "Marcus Bell",
        "email": "marcus.bell@example.com",
        "phone": "+1-647-555-0199",
        "ssn": "987-65-4321",
        "risk": "growth",
    },
}

NAME_TO_ID = {c["name"].lower(): cid for cid, c in CLIENTS.items()}

# ── Documents (prose → vector store) ──────────────────────────────────────────
DOCUMENTS = [
    {
        "id": "ips-balanced",
        "title": "Investment Policy Statement — Balanced Mandate",
        "text": ("The balanced mandate targets a 60/40 split between equities and fixed income. "
                 "Maximum single-issuer concentration is 25% of portfolio value. Tactical drift of "
                 "plus or minus 5% is permitted before rebalancing is required. Suitable for clients "
                 "with a medium risk tolerance and a 5 to 10 year horizon."),
    },
    {
        "id": "ips-growth",
        "title": "Investment Policy Statement — Growth Mandate",
        "text": ("The growth mandate targets 80% equities and 20% fixed income, accepting higher "
                 "volatility for long-term capital appreciation. Single-issuer concentration limit is "
                 "25%. Suitable for clients with a high risk tolerance and a horizon beyond 10 years."),
    },
    {
        "id": "policy-restricted",
        "title": "Firm Policy — Restricted Securities List",
        "text": ("Securities on the restricted list may not be added to client portfolios and existing "
                 "positions must be flagged for review. A security is restricted when the firm holds "
                 "material non-public information, during an active underwriting, or by compliance "
                 "directive. NorthForge Energy (NFE) is currently restricted pending an underwriting."),
    },
    {
        "id": "policy-suitability",
        "title": "Firm Policy — Suitability & Know-Your-Client",
        "text": ("Every recommendation must be suitable for the client's documented risk profile, "
                 "objectives, and horizon. A growth-only allocation is not suitable for a client with a "
                 "balanced or conservative profile. Suitability must be reassessed at each portfolio "
                 "review and any mismatch escalated to a human advisor before action."),
    },
    {
        "id": "factsheet-glx",
        "title": "Fund Factsheet — Global Equity Index (GLX)",
        "text": ("GLX is a broad global equity index fund, expense ratio 0.09%, tracking developed and "
                 "emerging markets. Top sector exposure is technology at roughly 24%. Used as the core "
                 "equity building block across balanced and growth mandates."),
    },
    {
        "id": "factsheet-agg",
        "title": "Fund Factsheet — Aggregate Bond (AGG)",
        "text": ("AGG is an investment-grade aggregate bond fund, average duration 6.2 years, used as "
                 "the core fixed-income holding. Provides ballast against equity drawdowns in the "
                 "balanced mandate."),
    },
    {
        "id": "factsheet-nfe",
        "title": "Fund Factsheet — NorthForge Energy (NFE)",
        "text": ("NorthForge Energy is a single-name energy equity. High volatility, concentrated "
                 "commodity exposure. Note: NFE currently appears on the firm restricted list."),
    },
]

# ── Holdings (structure → knowledge graph) ────────────────────────────────────
# security_id -> (display name, issuer_id, issuer name, sector)
_SECURITIES = {
    "GLX": ("Global Equity Index", "ISS-VANTAGE", "Vantage Funds", "Equity"),
    "AGG": ("Aggregate Bond", "ISS-VANTAGE", "Vantage Funds", "Fixed Income"),
    "NFE": ("NorthForge Energy", "ISS-NORTHFORGE", "NorthForge Inc.", "Energy"),
    "TQQ": ("Tech Growth ETF", "ISS-APEX", "Apex ETFs", "Equity"),
}

# client_id -> {security_id: weight}
_PORTFOLIOS = {
    "C-1001": {"GLX": 0.42, "AGG": 0.36, "NFE": 0.22},   # balanced, but 22% energy + restricted NFE
    "C-1002": {"GLX": 0.30, "TQQ": 0.50, "AGG": 0.20},   # growth, heavy tech
}

_RISK_PROFILES = {
    "balanced": {"name": "Balanced", "tolerance": "medium", "horizon": "5-10y",
                 "target_mix": "60% equity / 40% fixed income"},
    "growth": {"name": "Growth", "tolerance": "high", "horizon": ">10y",
               "target_mix": "80% equity / 20% fixed income"},
}


def resolve_client(text: str) -> str | None:
    """Map a free-text mention ('review Jane's portfolio') to a client id."""
    low = text.lower()
    for cid in CLIENTS:
        if cid.lower() in low:
            return cid
    for name, cid in NAME_TO_ID.items():
        first = name.split()[0]
        if name in low or first in low:
            return cid
    return None


def build_graph() -> KnowledgeGraph:
    kg = KnowledgeGraph()
    # securities, issuers, sectors (sector hangs off the security)
    for sid, (sname, iss_id, iss_name, sector) in _SECURITIES.items():
        sec_node = f"SECTOR:{sector}"
        if sec_node not in kg.g:
            kg.add_node(sec_node, kind="Sector", name=sector)
        if iss_id not in kg.g:
            kg.add_node(iss_id, kind="Issuer", name=iss_name)
        kg.add_node(sid, kind="Security", name=sname)
        kg.add_edge(sid, "ISSUED_BY", iss_id)
        kg.add_edge(sid, "IN_SECTOR", sec_node)

    # restricted list
    kg.add_node("POLICY:restricted", kind="Policy", name="Restricted List",
                reason="Active underwriting — material non-public information")
    kg.add_edge("NFE", "RESTRICTED_BY", "POLICY:restricted")

    # clients, profiles, holdings
    for cid, client in CLIENTS.items():
        kg.add_node(cid, kind="Client", name=client["name"])
        prof = _RISK_PROFILES[client["risk"]]
        prof_node = f"PROFILE:{cid}"
        kg.add_node(prof_node, kind="RiskProfile", **prof)
        kg.add_edge(cid, "HAS_PROFILE", prof_node)
        for sid, weight in _PORTFOLIOS[cid].items():
            kg.add_edge(cid, "HOLDS", sid, weight=weight)
    return kg
