"""Checkpointer factory — the seam that makes human-in-the-loop production-grade.

The checkpointer is where a paused run lives while it waits for an advisor. In the local
demo that's `InMemorySaver` (fine for one process). In production you want a durable,
shared store so a run can wait hours, survive a restart, and be resumed by *any* worker —
which is also what lets the service scale horizontally.

    ALPHA_CHECKPOINT_DB unset            → InMemorySaver (default, local)
    ALPHA_CHECKPOINT_DB=postgres://...   → PostgresSaver (durable, shared)

Postgres support needs `pip install langgraph-checkpoint-postgres`; if it's missing we
fall back to memory and say so, so the app never fails to start in a dev environment.
"""
from __future__ import annotations

import os

from langgraph.checkpoint.memory import InMemorySaver


def make_checkpointer():
    url = os.getenv("ALPHA_CHECKPOINT_DB", "").strip()
    if url.startswith("postgres"):
        try:
            from langgraph.checkpoint.postgres import PostgresSaver

            saver = PostgresSaver.from_conn_string(url)
            # Some versions return a context manager; enter it for a long-lived saver.
            if hasattr(saver, "__enter__"):
                saver = saver.__enter__()
            saver.setup()  # idempotent: creates the checkpoint tables if absent
            return saver
        except Exception as e:  # noqa: BLE001
            print(f"[checkpoint] Postgres unavailable ({e}); falling back to in-memory.")
    return InMemorySaver()
