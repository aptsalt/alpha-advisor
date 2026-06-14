"""Lazily-built, cached retrieval backends: the vector store and the knowledge graph.

Built once per process from the synthetic loaders. In production these are long-lived
connections to your vector DB and Neo4j; here they're in-memory singletons so the demo
starts instantly.
"""
from __future__ import annotations

import os
from functools import lru_cache

from .data import synth
from .rag.graphrag import KnowledgeGraph
from .rag.vectorstore import VectorStore


@lru_cache(maxsize=1)
def vector_store() -> VectorStore:
    vs = VectorStore()
    vs.add(synth.DOCUMENTS)
    return vs


@lru_cache(maxsize=1)
def knowledge_graph():
    """networkx by default; Neo4j when ALPHA_GRAPH_DB is set and reachable.

    The two backends share a public surface, so callers (retrieval, compliance) are
    backend-agnostic. Neo4j failures fall back to networkx so dev never needs a DB."""
    if os.getenv("ALPHA_GRAPH_DB", "").startswith(("bolt", "neo4j")):
        try:
            from .rag.neo4j_adapter import from_env

            kg = from_env()
            kg.load_synthetic()
            return kg
        except Exception as e:  # noqa: BLE001
            print(f"[corpus] Neo4j unavailable ({e}); using in-memory graph.")
    return synth.build_graph()
