"""Append-only audit log. Every governed action writes one immutable JSONL line.

In regulated wealth management the audit trail is not a feature you bolt on — it's the
thing that makes an autonomous agent deployable at all. Each record answers: what step
ran, on whose behalf, what it decided, and on what evidence. Append-only + content hash
chaining makes after-the-fact tampering detectable.
"""
from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from typing import Any

from . import config

_last_hash = "GENESIS"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def log(event: str, payload: dict[str, Any], *, run_id: str = "") -> None:
    """Write one audit record, chaining each line's hash to the previous one."""
    global _last_hash
    record = {
        "ts": _now(),
        "run_id": run_id,
        "event": event,
        "payload": payload,
        "prev_hash": _last_hash,
    }
    body = json.dumps(record, ensure_ascii=False, sort_keys=True)
    record["hash"] = hashlib.sha256((_last_hash + body).encode()).hexdigest()[:16]
    _last_hash = record["hash"]

    os.makedirs(os.path.dirname(config.AUDIT_PATH) or ".", exist_ok=True)
    with open(config.AUDIT_PATH, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def verify(path: str | None = None) -> bool:
    """Re-walk the chain and confirm no line was altered or removed."""
    path = path or config.AUDIT_PATH
    prev = "GENESIS"
    if not os.path.exists(path):
        return True
    with open(path, encoding="utf-8") as f:
        for line in f:
            rec = json.loads(line)
            stored = rec.pop("hash")
            if rec["prev_hash"] != prev:
                return False
            body = json.dumps(rec, ensure_ascii=False, sort_keys=True)
            if hashlib.sha256((prev + body).encode()).hexdigest()[:16] != stored:
                return False
            prev = stored
    return True
