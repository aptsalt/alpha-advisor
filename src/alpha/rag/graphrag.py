"""Graph RAG over a wealth-management knowledge graph (networkx, in-memory).

Schema (the JD's "knowledge graphs" + "Graph RAG"):

    (Client) -[:HOLDS {weight}]-> (Security) -[:ISSUED_BY]-> (Issuer)
    (Security) -[:IN_SECTOR]-> (Sector)            # sector is a property of the security/fund
    (Client) -[:HAS_PROFILE]-> (RiskProfile)
    (Security) -[:RESTRICTED_BY]-> (Policy)        # restricted-list edges

Note sector hangs off the *security*, not the issuer: one issuer (a fund family) can
issue both an equity and a bond fund, so sector-via-issuer would be wrong. Getting this
edge direction right is exactly the kind of structural correctness a graph buys you.

Why a graph and not just vectors: questions like "how concentrated is this client in a
single issuer or sector?" or "does any holding touch the restricted list?" are
multi-hop relationship queries. Vector search retrieves *text that looks similar*; the
graph answers *structural* questions exactly. Agentic RAG uses both — vectors for prose
(policies, factsheets), the graph for the portfolio's structure.

networkx keeps the demo serverless. The query methods below map 1:1 onto Cypher; the
docstrings show the equivalent Neo4j query so the swap is obvious.
"""
from __future__ import annotations

import networkx as nx


class KnowledgeGraph:
    def __init__(self) -> None:
        self.g = nx.MultiDiGraph()

    # ── construction ──────────────────────────────────────────────────────────
    def add_node(self, node_id: str, kind: str, **attrs) -> None:
        self.g.add_node(node_id, kind=kind, **attrs)

    def add_edge(self, src: str, rel: str, dst: str, **attrs) -> None:
        self.g.add_edge(src, dst, key=rel, rel=rel, **attrs)

    # ── queries (each mirrors a Cypher query) ─────────────────────────────────
    def holdings(self, client_id: str) -> list[dict]:
        """Cypher: MATCH (c{id})-[h:HOLDS]->(s)-[:ISSUED_BY]->(i)-[:IN_SECTOR]->(sec)
                   RETURN s, h.weight, i, sec"""
        out = []
        for _, sec_id, data in self.g.out_edges(client_id, data=True):
            if data.get("rel") != "HOLDS":
                continue
            issuer = self._first_neighbor(sec_id, "ISSUED_BY")
            sector = self._first_neighbor(sec_id, "IN_SECTOR")  # sector hangs off the security
            out.append({
                "security_id": sec_id,
                "security": self.g.nodes[sec_id].get("name", sec_id),
                "weight": data.get("weight", 0.0),
                "issuer": self.g.nodes[issuer].get("name", issuer) if issuer else "unknown",
                "issuer_id": issuer,
                "sector": self.g.nodes[sector].get("name", sector) if sector else "unknown",
            })
        return sorted(out, key=lambda d: -d["weight"])

    def issuer_concentration(self, client_id: str) -> dict[str, float]:
        """Aggregate portfolio weight per issuer — the multi-hop query vectors can't do."""
        agg: dict[str, float] = {}
        for h in self.holdings(client_id):
            agg[h["issuer"]] = agg.get(h["issuer"], 0.0) + h["weight"]
        return dict(sorted(agg.items(), key=lambda kv: -kv[1]))

    def sector_concentration(self, client_id: str) -> dict[str, float]:
        agg: dict[str, float] = {}
        for h in self.holdings(client_id):
            agg[h["sector"]] = agg.get(h["sector"], 0.0) + h["weight"]
        return dict(sorted(agg.items(), key=lambda kv: -kv[1]))

    def restricted_hits(self, client_id: str) -> list[dict]:
        """Holdings that touch a restricted-list policy edge.
        Cypher: MATCH (c{id})-[:HOLDS]->(s)-[:RESTRICTED_BY]->(p) RETURN s, p"""
        hits = []
        for h in self.holdings(client_id):
            policy = self._first_neighbor(h["security_id"], "RESTRICTED_BY")
            if policy:
                hits.append({
                    "security": h["security"],
                    "weight": h["weight"],
                    "policy": self.g.nodes[policy].get("name", policy),
                    "reason": self.g.nodes[policy].get("reason", ""),
                })
        return hits

    def risk_profile(self, client_id: str) -> dict:
        rp = self._first_neighbor(client_id, "HAS_PROFILE")
        return dict(self.g.nodes[rp]) if rp else {}

    def as_facts(self, client_id: str) -> list[dict]:
        """Flatten the client's subgraph into retrievable 'graph docs' so the agentic
        retriever can grade graph evidence alongside vector evidence."""
        facts = []
        rp = self.risk_profile(client_id)
        if rp:
            facts.append({
                "source_id": f"graph:{client_id}:profile",
                "title": "Client risk profile",
                "text": (f"Risk profile: {rp.get('name','?')} "
                         f"(tolerance={rp.get('tolerance','?')}, horizon={rp.get('horizon','?')}). "
                         f"Suitable asset mix target: {rp.get('target_mix','?')}."),
                "origin": "graph",
                "score": 0.9,
            })
        for issuer, w in self.issuer_concentration(client_id).items():
            facts.append({
                "source_id": f"graph:{client_id}:issuer:{issuer}",
                "title": f"Issuer concentration — {issuer}",
                "text": f"Aggregate portfolio weight in issuer {issuer} is {w:.0%}.",
                "origin": "graph",
                "score": 0.85,
            })
        for sector, w in self.sector_concentration(client_id).items():
            facts.append({
                "source_id": f"graph:{client_id}:sector:{sector}",
                "title": f"Sector concentration — {sector}",
                "text": f"Aggregate portfolio weight in the {sector} sector is {w:.0%}.",
                "origin": "graph",
                "score": 0.8,
            })
        return facts

    # ── internals ─────────────────────────────────────────────────────────────
    def _first_neighbor(self, node: str | None, rel: str) -> str | None:
        if node is None or node not in self.g:
            return None
        for _, dst, data in self.g.out_edges(node, data=True):
            if data.get("rel") == rel:
                return dst
        return None
