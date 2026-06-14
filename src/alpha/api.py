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

from fastapi import FastAPI, HTTPException
from langgraph.types import Command
from pydantic import BaseModel

from . import audit, config
from .graph import build_graph

app = FastAPI(title="ALPHA Advisor", version="1.0")
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
