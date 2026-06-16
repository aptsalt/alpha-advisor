"""HTTP service around the advisory graph — the deployable surface for Azure.

Two endpoints mirror the human-in-the-loop lifecycle:
  POST /api/review                 → run to the approval interrupt; returns the prepared
                                      briefing + compliance findings + a run_id
  POST /api/review/{run_id}/decision → resume the paused run with the advisor's decision

The graph is stateless; the *checkpointer* holds each paused run (keyed by run_id =
thread_id). With the Postgres checkpointer (ALPHA_CHECKPOINT_DB) any instance can serve
the resume call for a run any other instance started — that's what makes this horizontally
scalable behind a load balancer on Azure Container Apps.

    uvicorn alpha.api:app --port 8200      (from the src/ dir, or set PYTHONPATH=src)
"""
from __future__ import annotations

import json
import os

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from langgraph.types import Command
from pydantic import BaseModel

from . import audit, config
from .graph import build_graph

app = FastAPI(title="ALPHA Advisor", version="1.0")
_WEB = os.path.join(os.path.dirname(__file__), "web")


@app.get("/")
def home() -> FileResponse:
    """Serve the single-page advisor UI (same origin as the API, so no CORS needed)."""
    return FileResponse(os.path.join(_WEB, "index.html"))
_graph = build_graph()  # one compiled graph; its checkpointer persists runs across requests
_counter = {"n": 0}


class ReviewRequest(BaseModel):
    request: str
    run_id: str | None = None


class Decision(BaseModel):
    decision: str  # approved | rejected | edited
    note: str = ""


def _state(run_id: str) -> dict:
    return _graph.get_state({"configurable": {"thread_id": run_id}}).values


@app.get("/api/health")
def health() -> dict:
    return {"ok": True, **config.summary()}


@app.post("/api/review")
def review(req: ReviewRequest) -> dict:
    _counter["n"] += 1
    run_id = req.run_id or f"run-{_counter['n']}"
    thread = {"configurable": {"thread_id": run_id}}
    result = _graph.invoke({"request": req.request}, thread)
    state = _state(run_id)

    if not result.get("__interrupt__"):
        return {"run_id": run_id, "status": "completed",
                "final": state.get("final") or state.get("draft", ""),
                "trace": state.get("trace", [])}

    return {
        "run_id": run_id,
        "status": "awaiting_approval",
        "intent": state.get("intent"),
        "client_id": state.get("client_id"),
        "compliance_status": state.get("compliance_status"),
        "compliance": state.get("compliance", []),
        "draft": state.get("draft", ""),
        "citations": state.get("citations", []),
        "trace": state.get("trace", []),
    }


def _sse(obj: dict) -> str:
    return f"data: {json.dumps(obj)}\n\n"


@app.post("/api/review/stream")
def review_stream(req: ReviewRequest) -> StreamingResponse:
    """Same as /api/review but streams each node's completion as a Server-Sent Event, so
    the UI can show the agent working live instead of waiting on a spinner — which matters
    when a real local/Azure model is doing the thinking. Ends with an `awaiting_approval`
    (or `completed`) event; the advisor's decision still goes through /decision."""
    _counter["n"] += 1
    run_id = req.run_id or f"run-{_counter['n']}"
    thread = {"configurable": {"thread_id": run_id}}

    def gen():
        yield _sse({"type": "run", "run_id": run_id})
        try:
            # "updates" = per-node completion; "custom" = the draft node's live tokens.
            for mode, chunk in _graph.stream({"request": req.request}, thread,
                                             stream_mode=["updates", "custom"]):
                if mode == "custom":
                    if isinstance(chunk, dict) and chunk.get("type") == "draft_token":
                        yield _sse(chunk)
                    continue
                if "__interrupt__" in chunk:
                    continue  # the pause; full payload surfaced from state below
                for node, update in chunk.items():
                    if not isinstance(update, dict):
                        continue
                    yield _sse({"type": "node", "node": node, "trace": update.get("trace", [])})
            state = _state(run_id)
            snap = _graph.get_state(thread)
            if snap.next:  # paused at the approval interrupt
                yield _sse({"type": "awaiting_approval", "run_id": run_id,
                            "client_id": state.get("client_id", ""),
                            "compliance_status": state.get("compliance_status"),
                            "compliance": state.get("compliance", []),
                            "rebalance": state.get("rebalance", {}),
                            "draft": state.get("draft", ""),
                            "citations": state.get("citations", [])})
            else:
                yield _sse({"type": "completed", "run_id": run_id,
                            "final": state.get("final") or state.get("draft", "")})
        except Exception as e:  # surface errors to the UI rather than a dead stream
            yield _sse({"type": "error", "message": str(e)})
        yield _sse({"type": "done"})

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.post("/api/review/{run_id}/decision")
def decide(run_id: str, body: Decision) -> dict:
    thread = {"configurable": {"thread_id": run_id}}
    try:
        snapshot = _graph.get_state(thread)
    except Exception:
        raise HTTPException(404, "unknown run_id")
    if not snapshot.next:  # nothing pending → run already finished or never existed
        raise HTTPException(409, "run is not awaiting a decision")

    _graph.invoke(Command(resume={"decision": body.decision, "note": body.note}), thread)
    state = _state(run_id)
    return {"run_id": run_id, "status": "completed",
            "decision": state.get("decision"),
            "final": state.get("final", ""),
            "audit_ok": audit.verify()}


# ── Evaluation (LLM-as-judge on a finished run) ──────────────────────────────
@app.post("/api/review/{run_id}/eval")
def evaluate_run(run_id: str) -> dict:
    """Score a run's briefing for citation coverage, groundedness, and suitability."""
    from . import evaluate as _eval
    state = _state(run_id)
    briefing = state.get("draft", "")
    if not briefing:
        raise HTTPException(404, "no briefing for that run_id")
    return _eval.evaluate(briefing, state.get("citations", []), state.get("compliance", []))


# ── Knowledge graph (for the visualization panel) ────────────────────────────
@app.get("/api/graph/{client_id}")
def client_graph(client_id: str) -> dict:
    from . import corpus
    return corpus.knowledge_graph().subgraph(client_id)


# ── Clients + portfolio dashboard scan ───────────────────────────────────────
@app.get("/api/clients")
def clients() -> list[dict]:
    from .data import synth
    return [{"client_id": c["client_id"], "name": c["name"], "risk": c["risk"]}
            for c in synth.CLIENTS.values()]


@app.get("/api/portfolio/scan")
def portfolio_scan() -> list[dict]:
    """Fast, LLM-free compliance scan across every client — the dashboard 'flagged for
    review' queue. Pure graph queries, so it's instant even with many clients."""
    from . import advice
    from .data import synth
    rows = []
    for cid, c in synth.CLIENTS.items():
        findings, status, ctx = advice.assess(cid)
        top_issuer, top_w = next(iter(ctx["issuer_conc"].items()), ("none", 0.0))
        rows.append({
            "client_id": cid, "name": c["name"], "risk": c["risk"], "status": status,
            "flags": [f["check"] for f in findings if f["status"] != "pass"],
            "top_issuer": top_issuer, "top_issuer_weight": round(top_w, 4),
            "restricted": bool(ctx["restricted"]),
        })
    order = {"fail": 0, "warn": 1, "pass": 2}
    return sorted(rows, key=lambda r: order[r["status"]])
