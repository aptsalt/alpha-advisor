"""Drafting node — composes the cited briefing from graded evidence + market data +
compliance findings. Every factual line carries a citation marker tying it back to a
specific source id; the output guard later rejects an uncited draft. Grounding isn't a
nicety here — an un-sourced number in a client briefing is a compliance incident.
"""
from __future__ import annotations

from .. import audit, llm
from ..state import AdvisorState, Citation

_SYS = ("[TASK:draft_briefing] You are a wealth-advisory writing assistant. Using ONLY the "
        "numbered EVIDENCE, write a concise portfolio-review briefing for advisor review. "
        "Cite each factual claim with its [n] marker. Do not invent figures.")


def draft_node(state: AdvisorState) -> dict:
    # If an earlier guard already produced a refusal draft, leave it untouched.
    if state.get("compliance_status") == "fail" and state.get("draft") and not state.get("docs"):
        return {"citations": [], "trace": [{"node": "draft", "skipped": "blocked upstream"}]}

    docs = state.get("docs", [])
    citations: list[Citation] = []
    evidence_lines = []
    for i, d in enumerate(docs, start=1):
        marker = f"[{i}]"
        citations.append({"marker": marker, "source_id": d["source_id"],
                          "title": d["title"], "snippet": d["text"][:160]})
        evidence_lines.append(f"{marker} {d['title']}: {d['text']}")

    # Fold compliance findings and the portfolio return in as additional cited evidence.
    market = state.get("market", {})
    if market.get("portfolio_ytd_return") is not None:
        i = len(citations) + 1
        evidence_lines.append(f"[{i}] Market data: portfolio YTD return is "
                              f"{market['portfolio_ytd_return']:.1%}.")
        citations.append({"marker": f"[{i}]", "source_id": "tool:market",
                          "title": "Market data (synthetic feed)",
                          "snippet": f"portfolio YTD {market['portfolio_ytd_return']:.1%}"})
    for f in state.get("compliance", []):
        if f["status"] != "pass":
            i = len(citations) + 1
            evidence_lines.append(f"[{i}] Compliance ({f['check']}): {f['detail']}")
            citations.append({"marker": f"[{i}]", "source_id": f"compliance:{f['check']}",
                              "title": f"Compliance finding — {f['check']}",
                              "snippet": f["detail"][:160]})

    client_name = _client_name(state.get("client_id", ""))
    user = (f"CLIENT: {client_name}\nREQUEST: {state.get('safe_request','')}\n\n"
            "EVIDENCE:\n" + "\n".join(evidence_lines))
    draft = llm.chat(_SYS, user, max_tokens=600)

    audit.log("draft", {"n_citations": len(citations), "chars": len(draft)},
              run_id=state.get("client_id", ""))
    return {"draft": draft, "citations": citations,
            "trace": [{"node": "draft", "n_citations": len(citations)}]}


def _client_name(client_id: str) -> str:
    from ..data import synth
    return synth.CLIENTS.get(client_id, {}).get("name", "the client")
