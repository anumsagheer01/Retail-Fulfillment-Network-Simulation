"""
agent.py
The tool-calling agent that turns a professional customer's free-text project
request into an optimized sourcing quote.

WHAT THE AGENT DOES
-------------------
    Pro: "I'm framing a basement in Atlanta. Need about 120 2x4 studs, 6 rolls
          of 12-2 romex, 40 half inch copper elbows, and 8 buckets of white
          interior paint."

    Agent:
      1. Reads the request.
      2. Calls the source_project tool with parsed line items and destination.
      3. Reads the tool result (matched SKUs, sourcing plan, quote, shortfalls).
      4. Writes back a clear, Pro-facing summary and flags anything ambiguous.

This is the "agentic workflow with custom tool-calling and reasoning traces"
the job description asks for. The agent does not do the optimization itself; it
orchestrates. The optimizer stays behind the tool boundary, which is exactly how
a production agent should be structured: the LLM handles language and control
flow, a deterministic tool handles the math.

TWO MODES
---------
  Real:  uses the Anthropic API. Set ANTHROPIC_API_KEY in the environment.
  Offline: a deterministic stub that parses with regex and calls the same tool.
           Runs with no key and no network, so tests and the FastAPI demo work
           anywhere. The offline path exercises the identical tool contract, so
           it is a faithful stand-in for wiring and integration tests, just not
           for language understanding.
"""

import os
import re
import json

from sourcing_tool import source_project, TOOL_SCHEMA


MODEL = "claude-sonnet-4-6"
MAX_TURNS = 5   # cap the tool-use loop so a misbehaving model cannot spin


SYSTEM_PROMPT = """You are a sourcing assistant for professional trade customers \
(contractors, electricians, plumbers). A Pro describes a project in their own words. \
Your job is to turn that into an optimized sourcing quote.

Rules:
- Extract each material as a line item with a quantity. Preserve the Pro's wording \
in the query field; the tool handles matching to catalog SKUs.
- Identify the destination city from the request. If none is given, ask for it.
- Call the source_project tool once you have line items and a destination.
- When the tool returns, summarize the plan for the Pro: what was sourced, from \
where, the estimated shipping cost, and the two-day service level.
- If the tool reports unresolved items or shortfalls, say so plainly and ask the \
Pro to clarify or adjust. Never invent a product that did not match.
- Be concise and direct. Pros want the number and the plan, not filler."""


def _run_tool(name, tool_input):
    """Map a tool name from the model to the real Python function."""
    if name == "source_project":
        return source_project(
            line_items=tool_input.get("line_items", []),
            dest_region=tool_input.get("dest_region", ""),
        )
    return {"error": f"unknown tool: {name}"}


# ---------------------------------------------------------------------------
# Real Anthropic agent loop
# ---------------------------------------------------------------------------
def _run_real(user_message, history=None, trace=None):
    """
    Run the tool-calling loop against the Anthropic API.

    history : prior message dicts for a multi-turn session (stateful sessions
              are the JD's "maintain context across sessions" requirement).
    trace   : optional list; each tool call is appended for reasoning-trace
              visibility, which is what LangSmith-style observability captures.
    """
    import anthropic
    client = anthropic.Anthropic()   # reads ANTHROPIC_API_KEY

    messages = list(history or [])
    messages.append({"role": "user", "content": user_message})

    final_text = []
    for _ in range(MAX_TURNS):
        resp = client.messages.create(
            model=MODEL,
            max_tokens=1024,
            system=SYSTEM_PROMPT,
            tools=[TOOL_SCHEMA],
            messages=messages,
        )

        for block in resp.content:
            if block.type == "text":
                final_text.append(block.text)

        if resp.stop_reason != "tool_use":
            messages.append({"role": "assistant", "content": resp.content})
            break

        messages.append({"role": "assistant", "content": resp.content})
        tool_results = []
        for block in resp.content:
            if block.type == "tool_use":
                result = _run_tool(block.name, block.input)
                if trace is not None:
                    trace.append({"tool": block.name, "input": block.input,
                                  "result_summary": result.get("summary")})
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": json.dumps(result),
                })
        messages.append({"role": "user", "content": tool_results})

    return {"reply": "\n".join(t for t in final_text if t).strip(),
            "messages": messages, "trace": trace or []}


# ---------------------------------------------------------------------------
# Offline deterministic agent (no API key, no network)
# ---------------------------------------------------------------------------
_QTY_PATTERNS = [
    # "6 rolls of 12-2 romex", "about 40 half inch copper elbows"
    re.compile(r"(\d+)\s+(?:rolls?|coils?|bags?|boxes?|sheets?|pails?|"
               r"buckets?|gallons?|pieces?|pcs?|ea|each)\s+of\s+(.+)"),
    # "120 2x4 studs 8ft" — a bare quantity followed by the product text
    re.compile(r"(\d+)\s+(.+)"),
]

_CITY_RE = re.compile(
    r"\b(?:in|to|for|deliver(?:ed)?\s+to)\s+"
    r"(atlanta|new york|nyc|los angeles|la|chicago|dallas|houston|miami|"
    r"boston|phoenix|seattle|portland|denver|philadelphia|philly|"
    r"washington|dc|san diego)\b",
    re.IGNORECASE,
)

# Prose lead-ins that precede the first quantity ("Need about 120 ...").
_LEADIN_RE = re.compile(
    r".*?(?:need|want|get|grab|order|about|roughly|approximately)\s+",
    re.IGNORECASE,
)


def _split_items(text):
    """
    Very small deterministic parser: split the request on commas and 'and',
    strip any prose lead-in, then pull a leading quantity and the rest as the
    product query. This is not meant to rival the LLM; it exists so the wiring
    and the tool contract can be tested without a key.
    """
    body = _CITY_RE.sub("", text)
    chunks = re.split(r",|\band\b", body)
    items = []
    for chunk in chunks:
        c = chunk.strip(" .\n")
        if not c:
            continue
        c = _LEADIN_RE.sub("", c, count=1).strip()
        digit = re.search(r"\d", c)
        if digit and digit.start() > 0 and not c[:digit.start()].strip().isdigit():
            c = c[digit.start():]
        for pat in _QTY_PATTERNS:
            m = pat.match(c)
            if m:
                qty = int(m.group(1))
                query = m.group(2).strip()
                if query:
                    items.append({"query": query, "quantity": qty})
                break
    return items


def _find_city(text):
    m = _CITY_RE.search(text)
    return m.group(1) if m else ""


def _run_offline(user_message, history=None, trace=None):
    items = _split_items(user_message)
    dest = _find_city(user_message)

    if not dest:
        return {"reply": "Which city should this be delivered to?",
                "messages": [], "trace": trace or []}
    if not items:
        return {"reply": "I could not read any materials from that. "
                         "Try listing them with quantities.",
                "messages": [], "trace": trace or []}

    result = source_project(items, dest_region=dest)
    if trace is not None:
        trace.append({"tool": "source_project",
                      "input": {"line_items": items, "dest_region": dest},
                      "result_summary": result.get("summary")})

    reply = _render_offline_reply(result)
    return {"reply": reply, "messages": [], "trace": trace or [],
            "result": result}


def _render_offline_reply(result):
    """Turn a tool result into a plain Pro-facing summary, no LLM needed."""
    if result.get("plan") is None:
        un = ", ".join(u["query"] for u in result.get("unresolved", []))
        return (f"I could not build a plan. Unresolved items: {un or 'none'}. "
                "Please clarify and resend.")

    s = result["summary"]
    lines = [f"Sourcing plan for delivery to {result['destination']}:"]
    for ln in result["plan"]["lines"]:
        srcs = ", ".join(f"{a['fc_name']} ({a['units']:.0f})"
                         for a in ln["sourced_from"])
        row = f"  - {ln['requested']:.0f} {ln['unit']} {ln['product_name']}: {srcs}"
        if ln["shortfall"] > 0:
            row += f"  [short {ln['shortfall']:.0f}]"
        lines.append(row)

    lines.append(f"Estimated shipping cost: ${s['estimated_shipping_cost']:.2f}")
    lines.append(f"Two-day service level: {s['two_day_service_level']:.0%}")
    if result.get("unresolved"):
        un = ", ".join(u["query"] for u in result["unresolved"])
        lines.append(f"Could not match (please clarify): {un}")
    return "\n".join(lines)


def run_agent(user_message, history=None, trace=None, force_offline=False):
    """
    Route to the real agent when a key is present, otherwise the offline stub.
    force_offline lets tests and the demo run deterministically.
    """
    if force_offline or not os.environ.get("ANTHROPIC_API_KEY"):
        return _run_offline(user_message, history=history, trace=trace)
    return _run_real(user_message, history=history, trace=trace)


if __name__ == "__main__":
    msg = ("I'm framing a basement in Atlanta. Need about 120 2x4 studs 8ft, "
           "6 rolls of 12-2 romex 250ft, 40 half inch copper elbows, and "
           "8 buckets of white interior paint.")
    mode = "REAL" if os.environ.get("ANTHROPIC_API_KEY") else "OFFLINE"
    print(f"[running in {mode} mode]\n")
    out = run_agent(msg, trace=[])
    print(out["reply"])
    print("\n--- reasoning trace ---")
    print(json.dumps(out["trace"], indent=2, default=str))