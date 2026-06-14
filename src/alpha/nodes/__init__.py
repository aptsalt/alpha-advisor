"""Graph nodes. Each is a pure-ish function: state in, partial state out, plus a trace
entry and (where it matters) an audit record. One node = one responsibility, so the
LangGraph trace reads like the advisory workflow itself."""
