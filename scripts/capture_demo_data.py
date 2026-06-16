"""Capture real responses from the running app into a single JSON the static GitHub Pages
demo replays (Pages has no Python/LLM backend). Run with the server up on :8200.

    python scripts/capture_demo_data.py
"""
import json
import urllib.request

BASE = "http://localhost:8200"


def get(path):
    with urllib.request.urlopen(BASE + path, timeout=30) as r:
        return json.load(r)


def stream_review(request):
    """POST the SSE stream, collect ordered trace steps + the awaiting/completed payload."""
    body = json.dumps({"request": request}).encode()
    req = urllib.request.Request(BASE + "/api/review/stream", data=body,
                                 headers={"Content-Type": "application/json"})
    trace, final, run_id = [], None, None
    with urllib.request.urlopen(req, timeout=300) as r:
        buf = ""
        for raw in r:
            buf += raw.decode("utf-8")
            while "\n\n" in buf:
                frame, buf = buf.split("\n\n", 1)
                for line in frame.split("\n"):
                    if not line.startswith("data:"):
                        continue
                    ev = json.loads(line[5:].strip())
                    if ev["type"] == "run":
                        run_id = ev["run_id"]
                    elif ev["type"] == "node":
                        trace.extend(ev.get("trace", []))
                    elif ev["type"] in ("awaiting_approval", "completed"):
                        final = ev
    return run_id, trace, final


def main():
    data = {"health": get("/api/health"), "clients": get("/api/clients"),
            "scan": get("/api/portfolio/scan"),
            "graph": {"C-1001": get("/api/graph/C-1001"), "C-1002": get("/api/graph/C-1002")},
            "examples": {}}

    cases = {
        "jane": "Prepare a portfolio review for Jane Harrington",
        "marcus": "Review C-1002's portfolio for concentration and suitability",
        "blocked": "Can you guarantee 20% returns for Jane next year?",
    }
    for key, q in cases.items():
        print("capturing:", q)
        run_id, trace, final = stream_review(q)
        ex = {"request": q, "trace": trace, "final": final}
        if final and final.get("type") == "awaiting_approval":
            try:
                req = urllib.request.Request(BASE + f"/api/review/{run_id}/eval", data=b"",
                                             headers={"Content-Type": "application/json"})
                with urllib.request.urlopen(req, timeout=120) as r:
                    ex["eval"] = json.load(r)
            except Exception as e:  # noqa: BLE001
                print("  eval skipped:", e)
        data["examples"][key] = ex

    out = "docs/demo-data.json"
    with open(out, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=1)
    print("wrote", out, "·", sum(len(json.dumps(v)) for v in data.values()), "chars")


if __name__ == "__main__":
    main()
