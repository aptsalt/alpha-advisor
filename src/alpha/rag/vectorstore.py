"""A minimal local vector store (numpy cosine over an in-memory matrix).

Deliberately hand-rolled so the demo runs with no DB server and you can explain the
mechanics end-to-end in an interview. The `VectorStore` surface (add / search) is the
same one Chroma, PGVector, or Azure AI Search expose — swapping to a managed vector DB
in production is an adapter change, not a rewrite. That provider-agnostic seam is the
senior move; the numpy impl is just the default that always runs.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from .. import llm


@dataclass
class VectorStore:
    ids: list[str] = field(default_factory=list)
    titles: list[str] = field(default_factory=list)
    texts: list[str] = field(default_factory=list)
    _matrix: np.ndarray | None = None

    def add(self, docs: list[dict]) -> None:
        """docs: [{id, title, text}]. Embeds and appends."""
        if not docs:
            return
        self.ids += [d["id"] for d in docs]
        self.titles += [d["title"] for d in docs]
        self.texts += [d["text"] for d in docs]
        vecs = llm.embed([f"{d['title']}. {d['text']}" for d in docs])
        self._matrix = vecs if self._matrix is None else np.vstack([self._matrix, vecs])

    def search(self, query: str, k: int) -> list[dict]:
        if self._matrix is None or not self.ids:
            return []
        q = llm.embed([query])[0]
        sims = self._matrix @ q  # rows are L2-normalized, so dot == cosine
        order = np.argsort(-sims)[:k]
        return [
            {
                "source_id": self.ids[i],
                "title": self.titles[i],
                "text": self.texts[i],
                "origin": "vector",
                "score": float(sims[i]),
            }
            for i in order
        ]
