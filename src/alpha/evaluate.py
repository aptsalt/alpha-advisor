"""Evaluation — does the finished briefing meet the bar? LLM-as-judge + hard metrics.

Three scores, each answering a governance question a regulator would ask:
  citation_coverage : (deterministic) what fraction of answer sentences carry a citation?
  groundedness      : (LLM-judge) is every factual claim actually supported by a source?
  suitability       : (LLM-judge) does the briefing correctly reflect the compliance findings?

This is the JD's "explainability / governance" made measurable. Evals are the thing senior
agentic roles probe hardest — "how do you know the agent is right?" — so the system scores
its own output and the score is auditable. The deterministic metric needs no model; the two
judge metrics use the strong model and degrade to a heuristic under the mock provider.
"""
from __future__ import annotations

import json
import re

from . import llm

_GROUND_SYS = ("[TASK:judge_ground] You are a strict financial-compliance evaluator. Given SOURCES "
               "and a BRIEFING, judge whether every factual claim in the briefing is supported by the "
               "sources. Respond ONLY with JSON: {\"score\": <0..1>, \"unsupported\": [\"claim\", ...]}. "
               "score = fraction of claims supported.")
_SUIT_SYS = ("[TASK:judge_suit] You are a suitability reviewer. Given the FLAGGED FINDINGS and the "
             "BRIEFING, judge whether the briefing surfaces each flagged issue to the advisor. Respond "
             "ONLY with JSON: {\"score\": <0..1>, \"missed\": [\"finding\", ...]}.")


def _sentences(text: str) -> list[str]:
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+", text or "") if len(s.strip()) > 12]


def citation_coverage(briefing: str) -> dict:
    """Deterministic: share of substantive sentences that carry a [n] citation."""
    sents = _sentences(briefing)
    if not sents:
        return {"score": 0.0, "cited": 0, "total": 0}
    cited = sum(1 for s in sents if re.search(r"\[\d+", s))
    return {"score": round(cited / len(sents), 3), "cited": cited, "total": len(sents)}


def _parse_json(raw: str) -> dict:
    m = re.search(r"\{.*\}", raw, re.S)
    if m:
        try:
            return json.loads(m.group(0))
        except json.JSONDecodeError:
            pass
    return {}


def judge_groundedness(briefing: str, sources: list[dict]) -> dict:
    src = "\n".join(f"- {s.get('title','')}: {s.get('snippet', s.get('text',''))[:200]}" for s in sources)
    raw = llm.chat(_GROUND_SYS, f"SOURCES:\n{src}\n\nBRIEFING:\n{briefing}", max_tokens=400)
    d = _parse_json(raw)
    score = float(d.get("score", 0.0)) if isinstance(d.get("score"), (int, float)) else 0.0
    return {"score": round(max(0.0, min(1.0, score)), 3), "unsupported": d.get("unsupported", [])[:5]}


def judge_suitability(briefing: str, findings: list[dict]) -> dict:
    flagged = [f for f in findings if f.get("status") != "pass"]
    if not flagged:
        return {"score": 1.0, "missed": [], "note": "no flagged findings to surface"}
    fl = "\n".join(f"- {f['check']}: {f['detail']}" for f in flagged)
    raw = llm.chat(_SUIT_SYS, f"FLAGGED FINDINGS:\n{fl}\n\nBRIEFING:\n{briefing}", max_tokens=300)
    d = _parse_json(raw)
    score = float(d.get("score", 0.0)) if isinstance(d.get("score"), (int, float)) else 0.0
    return {"score": round(max(0.0, min(1.0, score)), 3), "missed": d.get("missed", [])[:5]}


def evaluate(briefing: str, sources: list[dict], findings: list[dict]) -> dict:
    cov = citation_coverage(briefing)
    ground = judge_groundedness(briefing, sources)
    suit = judge_suitability(briefing, findings)
    overall = round(0.3 * cov["score"] + 0.4 * ground["score"] + 0.3 * suit["score"], 3)
    return {"overall": overall, "citation_coverage": cov, "groundedness": ground, "suitability": suit}
