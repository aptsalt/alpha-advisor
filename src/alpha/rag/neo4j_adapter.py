"""Neo4j knowledge-graph backend — the production swap for the in-memory networkx graph.

Same public surface as `graphrag.KnowledgeGraph` (holdings / issuer_concentration /
sector_concentration / restricted_hits / risk_profile / as_facts), implemented in Cypher.
Because the networkx version documented each query's Cypher equivalent, this is a faithful
1:1 port — the rest of the app (retrieval, compliance, drafting) doesn't change at all.

Activated by ALPHA_GRAPH_DB=bolt://... (+ NEO4J_USER / NEO4J_PASSWORD). Requires
`pip install neo4j`. If the driver or server is unavailable, the corpus factory falls
back to the networkx graph, so local development never needs a database.

This file is the production path; it is not exercised by the local mock/Ollama demo.
"""
from __future__ import annotations

import os


class Neo4jKnowledgeGraph:
    def __init__(self, uri: str, user: str, password: str) -> None:
        from neo4j import GraphDatabase  # imported lazily so the package is optional

        self._driver = GraphDatabase.driver(uri, auth=(user, password))

    def close(self) -> None:
        self._driver.close()

    # ── one-time load of the synthetic corpus (idempotent MERGE) ──────────────
    def load_synthetic(self) -> None:
        from ..data import synth

        with self._driver.session() as s:
            s.run("MATCH (n) DETACH DELETE n")  # demo data only — never run against prod
            for sid, (sname, iss_id, iss_name, sector) in synth._SECURITIES.items():
                s.run(
                    """
                    MERGE (sec:Security {id:$sid}) SET sec.name=$sname
                    MERGE (iss:Issuer {id:$iss_id}) SET iss.name=$iss_name
                    MERGE (sect:Sector {name:$sector})
                    MERGE (sec)-[:ISSUED_BY]->(iss)
                    MERGE (sec)-[:IN_SECTOR]->(sect)
                    """,
                    sid=sid, sname=sname, iss_id=iss_id, iss_name=iss_name, sector=sector,
                )
            s.run(
                """MERGE (p:Policy {name:'Restricted List'}) SET p.reason=$reason
                   WITH p MATCH (sec:Security {id:'NFE'}) MERGE (sec)-[:RESTRICTED_BY]->(p)""",
                reason="Active underwriting — material non-public information",
            )
            for cid, client in synth.CLIENTS.items():
                prof = synth._RISK_PROFILES[client["risk"]]
                s.run(
                    """MERGE (c:Client {id:$cid}) SET c.name=$name
                       MERGE (rp:RiskProfile {id:$cid}) SET rp += $prof
                       MERGE (c)-[:HAS_PROFILE]->(rp)""",
                    cid=cid, name=client["name"], prof=prof,
                )
                for sec_id, weight in synth._PORTFOLIOS[cid].items():
                    s.run(
                        """MATCH (c:Client {id:$cid}), (sec:Security {id:$sid})
                           MERGE (c)-[h:HOLDS]->(sec) SET h.weight=$w""",
                        cid=cid, sid=sec_id, w=weight,
                    )

    # ── queries (mirror graphrag.KnowledgeGraph) ──────────────────────────────
    def holdings(self, client_id: str) -> list[dict]:
        cy = """
        MATCH (c:Client {id:$cid})-[h:HOLDS]->(s:Security)
        OPTIONAL MATCH (s)-[:ISSUED_BY]->(i:Issuer)
        OPTIONAL MATCH (s)-[:IN_SECTOR]->(sec:Sector)
        RETURN s.id AS security_id, s.name AS security, h.weight AS weight,
               coalesce(i.name,'unknown') AS issuer, i.id AS issuer_id,
               coalesce(sec.name,'unknown') AS sector
        ORDER BY h.weight DESC
        """
        with self._driver.session() as s:
            return [dict(r) for r in s.run(cy, cid=client_id)]

    def issuer_concentration(self, client_id: str) -> dict[str, float]:
        cy = """
        MATCH (c:Client {id:$cid})-[h:HOLDS]->(:Security)-[:ISSUED_BY]->(i:Issuer)
        RETURN i.name AS issuer, sum(h.weight) AS w ORDER BY w DESC
        """
        with self._driver.session() as s:
            return {r["issuer"]: r["w"] for r in s.run(cy, cid=client_id)}

    def sector_concentration(self, client_id: str) -> dict[str, float]:
        cy = """
        MATCH (c:Client {id:$cid})-[h:HOLDS]->(:Security)-[:IN_SECTOR]->(sec:Sector)
        RETURN sec.name AS sector, sum(h.weight) AS w ORDER BY w DESC
        """
        with self._driver.session() as s:
            return {r["sector"]: r["w"] for r in s.run(cy, cid=client_id)}

    def restricted_hits(self, client_id: str) -> list[dict]:
        cy = """
        MATCH (c:Client {id:$cid})-[h:HOLDS]->(s:Security)-[:RESTRICTED_BY]->(p:Policy)
        RETURN s.name AS security, h.weight AS weight, p.name AS policy, p.reason AS reason
        """
        with self._driver.session() as s:
            return [dict(r) for r in s.run(cy, cid=client_id)]

    def risk_profile(self, client_id: str) -> dict:
        cy = "MATCH (c:Client {id:$cid})-[:HAS_PROFILE]->(rp:RiskProfile) RETURN rp"
        with self._driver.session() as s:
            rec = s.run(cy, cid=client_id).single()
            return dict(rec["rp"]) if rec else {}

    def as_facts(self, client_id: str) -> list[dict]:
        # Reuse the exact flattening logic from the networkx version for parity.
        from .graphrag import KnowledgeGraph

        return KnowledgeGraph.as_facts(self, client_id)  # type: ignore[arg-type]


def from_env() -> "Neo4jKnowledgeGraph":
    return Neo4jKnowledgeGraph(
        os.environ["ALPHA_GRAPH_DB"],
        os.getenv("NEO4J_USER", "neo4j"),
        os.getenv("NEO4J_PASSWORD", "neo4j"),
    )
