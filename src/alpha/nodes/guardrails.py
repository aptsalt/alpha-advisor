"""Guardrail nodes — the governance boundary on both ends of the agent.

input_guard:  runs BEFORE anything reaches the LLM. Redacts PII (the model never needs
              the client's SSN/email to reason about allocation) and blocks disallowed
              intents. In a regulated platform, minimizing what the model sees is itself
              a control.
output_guard: runs AFTER drafting, BEFORE a human sees it. Verifies the draft is grounded
              (has citations), carries no leaked PII, and includes the required advice
              disclaimer. A draft that fails is flagged, never silently shipped.
"""
from __future__ import annotations

import re

from .. import audit
from ..state import AdvisorState

# Synthetic PII patterns — illustrative, not exhaustive.
_PII = [
    ("ssn", re.compile(r"\b\d{3}-\d{2}-\d{4}\b")),
    ("email", re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b")),
    ("phone", re.compile(r"\b\+?\d[\d\-\s().]{7,}\d\b")),
]

_DISALLOWED = re.compile(r"\b(guarantee\w*|insider|front[- ]?run|launder)\b", re.I)

_DISCLAIMER = ("This is a draft prepared for advisor review and is not investment advice "
               "until approved. Past performance does not guarantee future results.")


def redact(text: str) -> tuple[str, list[str]]:
    found = []
    out = text
    for label, pat in _PII:
        if pat.search(out):
            found.append(label)
            out = pat.sub(f"[REDACTED_{label.upper()}]", out)
    return out, found


def input_guard_node(state: AdvisorState) -> dict:
    request = state["request"]
    safe, found = redact(request)
    blocked = bool(_DISALLOWED.search(request))
    guard = {"pii_redacted": found, "blocked": blocked}
    audit.log("input_guard", guard, run_id=state.get("client_id", ""))

    if blocked:
        # Hard stop: short-circuit to a refusal the draft node will surface.
        return {
            "safe_request": safe,
            "input_guard": guard,
            "draft": ("This request cannot be processed: it asks for an action the firm's "
                      "policy prohibits. Escalating to a human compliance officer."),
            "compliance_status": "fail",
            "trace": [{"node": "input_guard", "blocked": True, "pii_redacted": found}],
        }
    return {
        "safe_request": safe,
        "input_guard": guard,
        "query": safe,
        "trace": [{"node": "input_guard", "blocked": False, "pii_redacted": found}],
    }


def route_after_input_guard(state: AdvisorState) -> str:
    """A policy-blocked request must not touch retrieval, tools, or client data at all —
    it routes straight to a refusal terminal."""
    return "blocked" if state.get("input_guard", {}).get("blocked") else "ok"


def refuse_node(state: AdvisorState) -> dict:
    audit.log("refused", {"reason": "input policy block"}, run_id=state.get("client_id", ""))
    return {"final": state.get("draft", "Request refused by policy."),
            "trace": [{"node": "refuse", "reason": "input policy block"}]}


def output_guard_node(state: AdvisorState) -> dict:
    draft = state.get("draft", "")
    citations = state.get("citations", [])
    issues = []

    if not citations:
        issues.append("ungrounded: no citations")
    leaked, leaks = redact(draft)
    if leaks:
        issues.append(f"pii_leak: {','.join(leaks)}")
        draft = leaked  # scrub before a human ever sees it

    if "not investment advice" not in draft.lower():
        draft = draft.rstrip() + "\n\n---\n_" + _DISCLAIMER + "_"

    guard = {"issues": issues, "ok": not issues}
    audit.log("output_guard", guard, run_id=state.get("client_id", ""))
    return {
        "draft": draft,
        "output_guard": guard,
        "trace": [{"node": "output_guard", "issues": issues}],
    }
