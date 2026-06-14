"""Lazily-built, cached retrieval backends: the vector store and the knowledge graph.

Built once per process from the synthetic loaders. In production these are long-lived
connections to your vector DB and Neo4j; here they're in-memory singletons so the demo
starts instantly.
"""
from __future__ import annotations

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
def knowledge_graph() -> KnowledgeGraph:
    return synth.build_graph()
