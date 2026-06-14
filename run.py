"""ALPHA Advisor — CLI driver.

    python run.py "Prepare a portfolio review for Jane Harrington"
    python run.py "review C-1002" --approve            # non-interactive (CI / demo)
    python run.py "review Jane" --reject --note "rerun after rebalancing"

Drives the LangGraph run up to the human-in-the-loop interrupt, shows the advisor what
the agent prepared, takes a decision, then resumes the graph to finalize. Works with
ALPHA_PROVIDER=mock (default, no keys), =ollama (local), or =azure.
"""
from __future__ import annotations

import argparse
import os
import sys

# UTF-8 console so box-drawing / glyphs render on Windows (cp1252) too.
try:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
except Exception:
    pass

# Make `import alpha...` work when run from the repo root without installing.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))

from langgraph.types import Command  # noqa: E402

from alpha import audit, config  # noqa: E402
from alpha.graph import build_graph  # noqa: E402


def _banner() -> None:
    s = config.summary()
    print("─" * 64)
    print(f"  ALPHA Advisor · provider={s['provider']} · model={s['chat_model']}")
    print(f"  top_k={s['top_k']}  max_retries={s['max_retries']}  "
          f"concentration_limit={s['concentration_limit']:.0%}")
    print("─" * 64)


def _print_trace(state: dict) -> None:
    print("\n  Agent trace")
    for step in state.get("trace", []):
        node = step.get("node", "?")
        rest = {k: v for k, v in step.items() if k != "node"}
        print(f"    • {node:<13} {rest}")


def _print_compliance(state: dict) -> None:
    findings = state.get("compliance", [])
    if not findings:
        return
    print(f"\n  Compliance — overall: {state.get('compliance_status','?').upper()}")
    for f in findings:
        glyph = {"pass": "✓", "warn": "▲", "fail": "✗"}.get(f["status"], "?")
        print(f"    {glyph} {f['check']:<15} {f['detail']}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("request", help="the advisor's natural-language request")
    ap.add_argument("--approve", action="store_true", help="auto-approve at the HITL gate")
    ap.add_argument("--reject", action="store_true", help="auto-reject at the HITL gate")
    ap.add_argument("--note", default="", help="advisor note (used with --reject or edit)")
    args = ap.parse_args()

    # Fresh audit log per run for a clean demo.
    if os.path.exists(config.AUDIT_PATH):
        os.remove(config.AUDIT_PATH)

    _banner()
    app = build_graph()
    thread = {"configurable": {"thread_id": "demo-run"}}

    # 1. Run until the interrupt (the human-approval gate).
    result = app.invoke({"request": args.request}, thread)
    state = app.get_state(thread).values

    _print_trace(state)
    _print_compliance(state)

    interrupted = result.get("__interrupt__")
    if not interrupted:
        # Graph ended without pausing (e.g. a policy-blocked request).
        print("\n  Final\n" + _indent(state.get("draft") or state.get("final", "(no output)")))
        _verify_audit()
        return

    payload = interrupted[0].value
    print("\n  ┌─ Advisor approval required " + "─" * 35)
    print(_indent(payload.get("draft", ""), "  │ "))
    print("  └" + "─" * 62)

    # 2. Decide (flag-driven, else interactive).
    if args.approve:
        decision, note = "approved", ""
    elif args.reject:
        decision, note = "rejected", args.note
    else:
        choice = input("\n  [a]pprove / [r]eject / [e]dit? ").strip().lower()
        decision = {"a": "approved", "r": "rejected", "e": "edited"}.get(choice, "approved")
        note = args.note or (input("  note: ").strip() if decision in ("rejected", "edited") else "")
    print(f"\n  → advisor decision: {decision}")

    # 3. Resume the paused graph with the human decision.
    app.invoke(Command(resume={"decision": decision, "note": note}), thread)
    final_state = app.get_state(thread).values

    print("\n  Final briefing\n" + _indent(final_state.get("final", "(none)")))
    _verify_audit()


def _verify_audit() -> None:
    ok = audit.verify()
    n = sum(1 for _ in open(config.AUDIT_PATH, encoding="utf-8")) if os.path.exists(config.AUDIT_PATH) else 0
    print(f"\n  Audit log: {n} records · tamper-check {'PASS ✓' if ok else 'FAIL ✗'} "
          f"· {config.AUDIT_PATH}")


def _indent(text: str, prefix: str = "    ") -> str:
    return "\n".join(prefix + line for line in (text or "").splitlines())


if __name__ == "__main__":
    main()
