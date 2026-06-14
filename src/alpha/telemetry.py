"""Observability — OpenTelemetry tracing per graph node, plus LangSmith notes.

In a regulated platform you must be able to answer "what did the agent do, step by step,
on this run?" months later. Two complementary layers:

  1. OpenTelemetry spans — one per node, nested under a run span. Exports to the console
     by default, or to any OTLP collector (Jaeger, Tempo, Azure Monitor) via
     OTEL_EXPORTER_OTLP_ENDPOINT. This is the vendor-neutral operational trace.
  2. The hash-chained audit log (audit.py) — the immutable compliance record.

Tracing is opt-in (ALPHA_TRACING=1) and degrades to a no-op if OpenTelemetry isn't
installed, so the local demo never depends on it.

LangSmith: set LANGCHAIN_TRACING_V2=true + LANGCHAIN_API_KEY and LangGraph reports runs to
LangSmith automatically — the easiest hosted option if the team already uses LangChain.
"""
from __future__ import annotations

import os
from contextlib import contextmanager

_ENABLED = os.getenv("ALPHA_TRACING", "0") == "1"
_tracer = None


def setup() -> None:
    """Configure a tracer provider once. Console exporter by default; OTLP if an endpoint
    is set. Safe to call when tracing is disabled or OTel isn't installed."""
    global _tracer
    if not _ENABLED or _tracer is not None:
        return
    try:
        from opentelemetry import trace
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor, ConsoleSpanExporter

        provider = TracerProvider(resource=Resource.create({"service.name": "alpha-advisor"}))
        if os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT"):
            from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
            exporter = OTLPSpanExporter()
        else:
            exporter = ConsoleSpanExporter()
        provider.add_span_processor(BatchSpanProcessor(exporter))
        trace.set_tracer_provider(provider)
        _tracer = trace.get_tracer("alpha-advisor")
    except Exception as e:  # noqa: BLE001
        print(f"[telemetry] OpenTelemetry unavailable ({e}); tracing disabled.")


def traced(name: str, fn):
    """Wrap a node function so each invocation opens a span. No-op when disabled."""
    if not _ENABLED:
        return fn

    def wrapper(state):
        if _tracer is None:
            return fn(state)
        with _tracer.start_as_current_span(f"node.{name}") as span:
            try:
                span.set_attribute("client_id", state.get("client_id", "") or "")
            except Exception:  # noqa: BLE001
                pass
            return fn(state)

    wrapper.__name__ = getattr(fn, "__name__", name)
    return wrapper


@contextmanager
def run_span(request: str):
    """A top-level span for one advisory run."""
    if not _ENABLED or _tracer is None:
        yield
        return
    with _tracer.start_as_current_span("advisory_run") as span:
        span.set_attribute("request.len", len(request))
        yield
