"""The ALPHA Advisor orchestration graph — the LangGraph 'spine' of the platform.

    START
      → plan            (classify intent, resolve client, decompose)
      → input_guard     (PII redaction + policy block)        ── governance (in)
      → retrieve  ⇄ rewrite   (agentic RAG: grade → retry)    ── Agentic / Graph RAG
      → market          (tool call: synthetic market data)    ── tool integration
      → compliance      (suitability / restricted / concentration)  ── governance
      → draft           (cited briefing)                       ── grounding
      → output_guard    (citations present, no PII, disclaimer) ── governance (out)
      → approval        (interrupt → advisor decision)         ── human-in-the-loop
      → finalize | discard
      → END

The whole flow is provider-agnostic (mock / Ollama / Azure) and every node writes to an
append-only audit log. Swapping LangGraph for AutoGen/CrewAI/Semantic Kernel would re-
implement THIS diagram — the orchestration contract is the durable asset, the framework
is an implementation detail (see docs/frameworks.md).
"""
from __future__ import annotations

from langgraph.graph import END, START, StateGraph

from . import telemetry
from .checkpoint import make_checkpointer
from .state import AdvisorState
from .nodes.plan import plan_node
from .nodes.guardrails import (
    input_guard_node, output_guard_node, route_after_input_guard, refuse_node,
)
from .nodes.retrieve import retrieve_node, rewrite_node, should_retry
from .nodes.market import market_node
from .nodes.compliance import compliance_node
from .nodes.rebalance import rebalance_node
from .nodes.draft import draft_node
from .nodes.approval import approval_node, route_after_approval
from .nodes.finalize import finalize_node, discard_node


def build_graph(checkpointer=None):
    telemetry.setup()
    g = StateGraph(AdvisorState)

    # Each node is wrapped with telemetry.traced(): a no-op unless ALPHA_TRACING=1, in
    # which case every node invocation opens an OpenTelemetry span. The graph shape is
    # unchanged either way — observability is a cross-cutting concern, not a node's job.
    def node(name, fn):
        g.add_node(name, telemetry.traced(name, fn))

    node("plan", plan_node)
    node("input_guard", input_guard_node)
    node("retrieve", retrieve_node)
    node("rewrite", rewrite_node)
    node("market", market_node)
    node("compliance", compliance_node)
    node("rebalance", rebalance_node)
    node("draft", draft_node)
    node("output_guard", output_guard_node)
    node("approval", approval_node)
    node("finalize", finalize_node)
    node("discard", discard_node)
    node("refuse", refuse_node)

    g.add_edge(START, "plan")
    g.add_edge("plan", "input_guard")

    # a policy-blocked request never reaches retrieval / client data
    g.add_conditional_edges("input_guard", route_after_input_guard,
                            {"blocked": "refuse", "ok": "retrieve"})
    g.add_edge("refuse", END)

    # agentic retrieval loop: weak evidence → rewrite → retrieve again; else proceed
    g.add_conditional_edges("retrieve", should_retry,
                            {"rewrite": "rewrite", "proceed": "market"})
    g.add_edge("rewrite", "retrieve")

    g.add_edge("market", "compliance")
    g.add_edge("compliance", "rebalance")   # findings → proposed trades
    g.add_edge("rebalance", "draft")
    g.add_edge("draft", "output_guard")
    g.add_edge("output_guard", "approval")

    # human decision routes to finalize or discard
    g.add_conditional_edges("approval", route_after_approval,
                            {"finalize": "finalize", "discard": "discard"})
    g.add_edge("finalize", END)
    g.add_edge("discard", END)

    # A checkpointer is REQUIRED for interrupt()/resume to work — it persists the paused
    # state between the interrupt and the human's resume. Memory locally; Postgres in prod
    # (ALPHA_CHECKPOINT_DB) so paused runs survive restarts and any worker can resume them.
    return g.compile(checkpointer=checkpointer or make_checkpointer())
