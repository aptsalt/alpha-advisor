"""Unified LLM interface across mock / ollama / azure.

The rest of the system only ever calls `chat()` and `embed()` — it has no idea which
provider is live. Swapping Azure OpenAI for a local model (or for the deterministic
mock used in CI) is a config change, never a code change. In a regulated setting this
also means the orchestration, guardrails, and audit logic are provider-portable —
you can run the exact same graph fully on-prem.
"""
from __future__ import annotations

import hashlib
import re

import httpx
import numpy as np

from . import config


# ── Public API ────────────────────────────────────────────────────────────────
def chat(system: str, user: str, *, temperature: float = 0.2, max_tokens: int = 700) -> str:
    if config.PROVIDER == "ollama":
        return _ollama_chat(system, user, temperature, max_tokens)
    if config.PROVIDER == "azure":
        return _azure_chat(system, user, temperature, max_tokens)
    return _mock_chat(system, user)


def embed(texts: list[str]) -> np.ndarray:
    if config.PROVIDER == "ollama":
        try:
            return _ollama_embed(texts)
        except Exception:
            pass  # fall back to deterministic embedding so retrieval still works offline
    if config.PROVIDER == "azure":
        try:
            return _azure_embed(texts)
        except Exception:
            pass
    return _hash_embed(texts)


# ── Mock provider (deterministic, dependency-free) ────────────────────────────
def _mock_chat(system: str, user: str) -> str:
    """A deterministic, rule-based 'LLM' good enough to drive and demo the full graph
    with zero keys. It reads the task hint we put at the top of each prompt and returns
    a structured, plausible response. Not intelligent — but reproducible, which is
    exactly what you want for tests and a no-network demo."""
    task = ""
    m = re.search(r"\[TASK:([a-z_]+)\]", system + user)
    if m:
        task = m.group(1)

    if task == "classify_intent":
        u = user.lower()
        if any(w in u for w in ("review", "portfolio", "rebalance", "briefing")):
            return "portfolio_review"
        if any(w in u for w in ("holding", "position", "fund", "etf", "stock")):
            return "holding_lookup"
        return "general"

    if task == "grade_doc":
        # Score = keyword overlap between question and doc; returned as a bare float.
        q = re.search(r"QUESTION:(.*?)DOCUMENT:", user, re.S)
        d = re.search(r"DOCUMENT:(.*)", user, re.S)
        if q and d:
            score = _overlap(q.group(1), d.group(1))
            return f"{score:.2f}"
        return "0.10"

    if task == "rewrite_query":
        q = re.search(r"QUERY:(.*)", user, re.S)
        base = (q.group(1) if q else user).strip()
        # Broaden: add domain synonyms so the retry surfaces different docs.
        return f"{base} investment policy suitability allocation holdings risk"

    if task == "draft_briefing":
        return _mock_briefing(user)

    if task == "summarize":
        return _first_sentences(user, 2)

    return _first_sentences(user, 3)


def _mock_briefing(user: str) -> str:
    name = _grab(user, r"CLIENT:\s*([^\n]+)") or "the client"
    facts = re.findall(r"\[(\d+)\]\s*([^\n]+)", user)
    lines = [f"**Portfolio Review — {name}**", ""]
    lines.append("Based on the connected sources, here is the prepared briefing.")
    for marker, fact in facts[:6]:
        lines.append(f"- {fact.strip()} [{marker}]")
    lines.append("")
    lines.append("This briefing is grounded entirely in the cited sources above and "
                 "is pending advisor review before being shared with the client.")
    return "\n".join(lines)


# ── Ollama provider (local) ───────────────────────────────────────────────────
def _ollama_chat(system: str, user: str, temperature: float, max_tokens: int) -> str:
    r = httpx.post(
        f"{config.OLLAMA_HOST}/api/chat",
        json={
            "model": config.OLLAMA_CHAT_MODEL,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "stream": False,
            "options": {"temperature": temperature, "num_predict": max_tokens},
        },
        timeout=120.0,
    )
    r.raise_for_status()
    return r.json()["message"]["content"].strip()


def _ollama_embed(texts: list[str]) -> np.ndarray:
    vecs = []
    for t in texts:
        r = httpx.post(
            f"{config.OLLAMA_HOST}/api/embeddings",
            json={"model": config.OLLAMA_EMBED_MODEL, "prompt": t},
            timeout=60.0,
        )
        r.raise_for_status()
        vecs.append(r.json()["embedding"])
    return _normalize(np.array(vecs, dtype=np.float32))


# ── Azure OpenAI provider (production target) ─────────────────────────────────
def _azure_chat(system: str, user: str, temperature: float, max_tokens: int) -> str:
    url = (f"{config.AZURE_ENDPOINT}/openai/deployments/{config.AZURE_CHAT_DEPLOYMENT}"
           f"/chat/completions?api-version={config.AZURE_API_VERSION}")
    r = httpx.post(
        url,
        headers={"api-key": config.AZURE_API_KEY},
        json={
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": temperature,
            "max_tokens": max_tokens,
        },
        timeout=120.0,
    )
    r.raise_for_status()
    return r.json()["choices"][0]["message"]["content"].strip()


def _azure_embed(texts: list[str]) -> np.ndarray:
    url = (f"{config.AZURE_ENDPOINT}/openai/deployments/{config.AZURE_EMBED_DEPLOYMENT}"
           f"/embeddings?api-version={config.AZURE_API_VERSION}")
    r = httpx.post(url, headers={"api-key": config.AZURE_API_KEY},
                   json={"input": texts}, timeout=60.0)
    r.raise_for_status()
    data = sorted(r.json()["data"], key=lambda d: d["index"])
    return _normalize(np.array([d["embedding"] for d in data], dtype=np.float32))


# ── Deterministic fallback embedding (hashing trick) ──────────────────────────
def _hash_embed(texts: list[str], dim: int = 256) -> np.ndarray:
    """Bag-of-words hashed into a fixed vector. Crude but real cosine geometry —
    enough for the retrieval/grade/rewrite loop to behave sensibly offline."""
    out = np.zeros((len(texts), dim), dtype=np.float32)
    for i, t in enumerate(texts):
        for tok in _tokens(t):
            h = int(hashlib.md5(tok.encode()).hexdigest(), 16)
            out[i, h % dim] += 1.0
    return _normalize(out)


# ── helpers ───────────────────────────────────────────────────────────────────
def _tokens(s: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", s.lower())


def _overlap(a: str, b: str) -> float:
    ta, tb = set(_tokens(a)), set(_tokens(b))
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta)


def _normalize(m: np.ndarray) -> np.ndarray:
    n = np.linalg.norm(m, axis=1, keepdims=True)
    n[n == 0] = 1.0
    return m / n


def _first_sentences(s: str, n: int) -> str:
    parts = re.split(r"(?<=[.!?])\s+", s.strip())
    return " ".join(parts[:n])


def _grab(s: str, pat: str) -> str | None:
    m = re.search(pat, s)
    return m.group(1).strip() if m else None
