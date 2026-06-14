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
from langgraph.checkpoint.memory import InMemorySaver

from .state import AdvisorState
from .nodes.plan import plan_node
from .nodes.guardrails import (
    input_guard_node, output_guard_node, route_after_input_guard, refuse_node,
)
from .nodes.retrieve import retrieve_node, rewrite_node, should_retry
from .nodes.market import market_node
from .nodes.compliance import compliance_node
from .nodes.draft import draft_node
from .nodes.approval import approval_node, route_after_approval
from .nodes.finalize import finalize_node, discard_node


def build_graph(checkpointer=None):
    g = StateGraph(AdvisorState)

    g.add_node("plan", plan_node)
    g.add_node("input_guard", input_guard_node)
    g.add_node("retrieve", retrieve_node)
    g.add_node("rewrite", rewrite_node)
    g.add_node("market", market_node)
    g.add_node("compliance", compliance_node)
    g.add_node("draft", draft_node)
    g.add_node("output_guard", output_guard_node)
    g.add_node("approval", approval_node)
    g.add_node("finalize", finalize_node)
    g.add_node("discard", discard_node)
    g.add_node("refuse", refuse_node)

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
    g.add_edge("compliance", "draft")
    g.add_edge("draft", "output_guard")
    g.add_edge("output_guard", "approval")

    # human decision routes to finalize or discard
    g.add_conditional_edges("approval", route_after_approval,
                            {"finalize": "finalize", "discard": "discard"})
    g.add_edge("finalize", END)
    g.add_edge("discard", END)

    # A checkpointer is REQUIRED for interrupt()/resume to work — it persists the paused
    # state between the interrupt and the human's resume.
    return g.compile(checkpointer=checkpointer or InMemorySaver())
