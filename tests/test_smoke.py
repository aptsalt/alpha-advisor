"""End-to-end smoke tests — run the whole graph in mock mode (no keys, no network).

    python -m pytest -q          # if pytest installed
    python tests/test_smoke.py   # plain-python fallback runner (no pytest needed)
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
os.environ.setdefault("ALPHA_PROVIDER", "mock")
os.environ["ALPHA_AUDIT_PATH"] = os.path.join(os.path.dirname(__file__), "_test_audit.jsonl")

from langgraph.types import Command  # noqa: E402

from alpha import audit  # noqa: E402
from alpha.graph import build_graph  # noqa: E402


def _run(request: str, resume: dict | None = None):
    app = build_graph()
    thread = {"configurable": {"thread_id": "t"}}
    result = app.invoke({"request": request}, thread)
    if result.get("__interrupt__") and resume is not None:
        app.invoke(Command(resume=resume), thread)
    return app.get_state(thread).values


def test_portfolio_review_reaches_approval_with_compliance():
    state = _run("Prepare a portfolio review for Jane Harrington")
    assert state["intent"] == "portfolio_review"
    assert state["client_id"] == "C-1001"
    assert state["docs"], "retrieval returned no graded docs"
    assert state["citations"], "draft has no citations"
    # Jane holds restricted NFE → compliance must flag it
    assert state["compliance_status"] == "fail"
    checks = {f["check"]: f["status"] for f in state["compliance"]}
    assert checks["restricted_list"] == "fail"


def test_approval_finalizes():
    state = _run("review Jane Harrington", resume={"decision": "approved", "note": ""})
    assert state["decision"] == "approved"
    assert state["final"], "no final briefing produced"
    assert "not investment advice" in state["final"].lower()  # disclaimer enforced


def test_rejection_discards():
    state = _run("review C-1002", resume={"decision": "rejected", "note": "rebalance first"})
    assert state["decision"] == "rejected"
    assert "discarded" in state["final"].lower()


def test_pii_is_redacted_before_retrieval():
    state = _run("review C-1002 ssn 123-45-6789 email marcus.bell@example.com",
                 resume={"decision": "approved"})
    assert set(state["input_guard"]["pii_redacted"]) >= {"ssn", "email"}
    assert "123-45-6789" not in state["query"]


def test_policy_block_short_circuits():
    state = _run("Can you guarantee 20% returns?")
    assert state["input_guard"]["blocked"] is True
    # must NOT have run retrieval / compliance
    assert "docs" not in state or not state.get("docs")
    assert state["final"]


def test_audit_chain_intact():
    _run("review Jane Harrington", resume={"decision": "approved"})
    assert audit.verify() is True


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    passed = 0
    for t in tests:
        try:
            t()
            print(f"  PASS  {t.__name__}")
            passed += 1
        except AssertionError as e:
            print(f"  FAIL  {t.__name__}: {e}")
        except Exception as e:  # noqa: BLE001
            print(f"  ERROR {t.__name__}: {type(e).__name__}: {e}")
    print(f"\n  {passed}/{len(tests)} passed")
    if os.path.exists(os.environ["ALPHA_AUDIT_PATH"]):
        os.remove(os.environ["ALPHA_AUDIT_PATH"])
    sys.exit(0 if passed == len(tests) else 1)
