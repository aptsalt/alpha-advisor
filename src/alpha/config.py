"""Central configuration. Selects the LLM/embedding provider and core knobs.

Three providers, chosen via ALPHA_PROVIDER (default: mock):
  - mock   : deterministic, dependency-free. Always demoable, no keys, no network.
  - ollama : local models (you have qwen2.5-coder + an embedding model). Real LLM behaviour, private.
  - azure  : Azure OpenAI — the production target named in the ALPHA Wealth JD.

Provider is a runtime choice, never hard-coded into a node — the graph is identical
across all three. That separation is the point: the orchestration is the asset.
"""
from __future__ import annotations

import os

from dotenv import load_dotenv

load_dotenv()

PROVIDER = os.getenv("ALPHA_PROVIDER", "mock").strip().lower()

# ── Ollama (local) ───────────────────────────────────────────────────────────
# Task-based model routing: a small/fast model handles the many high-frequency calls
# (intent classification, per-document relevance grading), a stronger model writes the
# final briefing. This is a real cost/latency optimization — you don't pay a 12B model to
# score a document yes/no — and it keeps the local demo responsive.
OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://localhost:11434")
OLLAMA_CHAT_MODEL = os.getenv("OLLAMA_CHAT_MODEL", "gemma3:12b")      # drafting (strong)
OLLAMA_FAST_MODEL = os.getenv("OLLAMA_FAST_MODEL", "qwen2.5:3b")     # grading/classify (fast)
OLLAMA_EMBED_MODEL = os.getenv("OLLAMA_EMBED_MODEL", "nomic-embed-text:latest")

# ── Azure OpenAI (production) ────────────────────────────────────────────────
AZURE_ENDPOINT = os.getenv("AZURE_OPENAI_ENDPOINT", "")
AZURE_API_KEY = os.getenv("AZURE_OPENAI_API_KEY", "")
AZURE_API_VERSION = os.getenv("AZURE_OPENAI_API_VERSION", "2024-10-21")
AZURE_CHAT_DEPLOYMENT = os.getenv("AZURE_OPENAI_CHAT_DEPLOYMENT", "gpt-4o")
AZURE_FAST_DEPLOYMENT = os.getenv("AZURE_OPENAI_FAST_DEPLOYMENT", "gpt-4o-mini")
AZURE_EMBED_DEPLOYMENT = os.getenv("AZURE_OPENAI_EMBED_DEPLOYMENT", "text-embedding-3-small")

# ── Retrieval / agent knobs ──────────────────────────────────────────────────
RETRIEVE_TOP_K = int(os.getenv("ALPHA_TOP_K", "4"))
MAX_RETRIEVE_RETRIES = int(os.getenv("ALPHA_MAX_RETRIES", "2"))
GRADE_THRESHOLD = float(os.getenv("ALPHA_GRADE_THRESHOLD", "0.18"))  # min mean relevance to accept

# ── Concentration / suitability policy (synthetic, illustrative) ─────────────
CONCENTRATION_LIMIT = float(os.getenv("ALPHA_CONCENTRATION_LIMIT", "0.25"))  # max single-issuer weight

AUDIT_PATH = os.getenv("ALPHA_AUDIT_PATH", "audit-log.jsonl")


def summary() -> dict:
    """Non-secret config snapshot for the run banner / audit header."""
    return {
        "provider": PROVIDER,
        "chat_model": {
            "mock": "deterministic-mock",
            "ollama": OLLAMA_CHAT_MODEL,
            "azure": AZURE_CHAT_DEPLOYMENT,
        }.get(PROVIDER, PROVIDER),
        "fast_model": {
            "mock": "deterministic-mock",
            "ollama": OLLAMA_FAST_MODEL,
            "azure": AZURE_FAST_DEPLOYMENT,
        }.get(PROVIDER, PROVIDER),
        "top_k": RETRIEVE_TOP_K,
        "max_retries": MAX_RETRIEVE_RETRIES,
        "concentration_limit": CONCENTRATION_LIMIT,
    }
