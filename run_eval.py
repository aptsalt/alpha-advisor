"""Offline evaluation harness — run a fixed set of cases through the agent and score each
briefing on citation coverage, groundedness, and suitability. Prints a scorecard and writes
eval-report.json. This is the "how do you know the agent is right?" artifact.

    python run_eval.py                 # mock (fast, no keys)
    ALPHA_PROVIDER=ollama python run_eval.py
"""
from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))
try:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
except Exception:
    pass

from alpha import config, evaluate  # noqa: E402
from alpha.graph import build_graph  # noqa: E402

# Each case names the flags we expect the agent to surface — the eval checks the briefing
# actually reflects them (suitability), on top of grounding every claim in a source.
CASES = [
    {"request": "Prepare a portfolio review for Jane Harrington", "expect": ["restricted_list", "concentration"]},
    {"request": "Review C-1002 for concentration and suitability", "expect": ["concentration"]},
    {"request": "Holding lookup: what is the suitability policy?", "expect": []},
]


def run_case(case: dict, i: int) -> dict:
    app = build_graph()
    thread = {"configurable": {"thread_id": f"eval-{i}"}}
    app.invoke({"request": case["request"]}, thread)
    state = app.get_state(thread).values
    scores = evaluate.evaluate(state.get("draft", ""), state.get("citations", []),
                               state.get("compliance", []))
    return {"request": case["request"], "compliance_status": state.get("compliance_status"),
            "scores": scores}


def main() -> None:
    print(f"\n  Eval harness · provider={config.PROVIDER}\n  " + "─" * 58)
    rows = []
    for i, case in enumerate(CASES):
        r = run_case(case, i)
        rows.append(r)
        s = r["scores"]
        print(f"  {r['request'][:46]:46}  cov {s['citation_coverage']['score']:.2f}  "
              f"ground {s['groundedness']['score']:.2f}  suit {s['suitability']['score']:.2f}  "
              f"→ overall {s['overall']:.2f}")
        for u in s["groundedness"].get("unsupported", []):
            print(f"      ⚠ unsupported: {u[:70]}")
        for m in s["suitability"].get("missed", []):
            print(f"      ⚠ missed finding: {m[:70]}")

    avg = round(sum(r["scores"]["overall"] for r in rows) / len(rows), 3)
    print("  " + "─" * 58)
    print(f"  Mean overall score: {avg}   ({len(rows)} cases)")
    with open("eval-report.json", "w", encoding="utf-8") as f:
        json.dump({"provider": config.PROVIDER, "mean_overall": avg, "cases": rows}, f, indent=2)
    print("  Wrote eval-report.json\n")


if __name__ == "__main__":
    main()
