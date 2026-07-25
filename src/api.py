"""
api.py
FastAPI service exposing the sourcing agent and tool over HTTP.

ENDPOINTS
---------
  GET  /health                 liveness check
  POST /session                create a stateful session, returns session_id
  POST /session/{id}/message   send a Pro's message to the agent, get a reply;
                               conversation history is retained per session
  POST /tool/source            call the sourcing tool directly, bypassing the
                               agent (useful for other services and for testing
                               the optimizer path without an LLM)
  GET  /catalog                list the product families the agent can source

WHY BOTH AN AGENT ENDPOINT AND A RAW TOOL ENDPOINT
--------------------------------------------------
The agent endpoint is the conversational, Pro-facing surface. The raw tool
endpoint is the machine-facing surface: another service, a batch job, or a test
can get an optimized sourcing plan without paying for an LLM round trip. Exposing
the tool independently of the agent is what makes the optimizer a reusable
capability rather than something locked inside one chat flow.

Session state is held in memory here for simplicity. The store is abstracted
behind a tiny interface so swapping in Redis or a database later touches one
class, not the endpoints.
"""

import uuid
from typing import List, Optional

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from agent import run_agent
from sourcing_tool import source_project
from catalog import CATALOG


app = FastAPI(
    title="Pro Sourcing Agent",
    description="Agentic sourcing and fulfillment optimization for trade customers.",
    version="1.0.0",
)


class SessionStore:
    """Minimal session store. Swap the body for Redis without touching routes."""

    def __init__(self):
        self._data = {}

    def create(self):
        sid = uuid.uuid4().hex[:12]
        self._data[sid] = {"history": [], "quotes": []}
        return sid

    def get(self, sid):
        return self._data.get(sid)

    def exists(self, sid):
        return sid in self._data

    def append_turn(self, sid, role, content):
        self._data[sid]["history"].append({"role": role, "content": content})

    def record_quote(self, sid, quote):
        self._data[sid]["quotes"].append(quote)


STORE = SessionStore()


class MessageIn(BaseModel):
    message: str = Field(..., description="The Pro's free-text request.")
    force_offline: bool = Field(
        False, description="Force the deterministic offline agent (no API key)."
    )


class MessageOut(BaseModel):
    session_id: str
    reply: str
    trace: list
    result: Optional[dict] = None


class LineItemIn(BaseModel):
    query: str
    quantity: float


class SourceIn(BaseModel):
    line_items: List[LineItemIn]
    dest_region: str
    headroom: float = 3.0


@app.get("/health")
def health():
    return {"status": "ok", "catalog_size": len(CATALOG)}


@app.get("/catalog")
def catalog():
    return {
        "families": [
            {"sku_id": k, "name": v["name"], "category": v["category"],
             "unit": v["unit"]}
            for k, v in CATALOG.items()
        ]
    }


@app.post("/session")
def create_session():
    sid = STORE.create()
    return {"session_id": sid}


@app.post("/session/{session_id}/message", response_model=MessageOut)
def send_message(session_id: str, body: MessageIn):
    if not STORE.exists(session_id):
        raise HTTPException(status_code=404, detail="session not found")

    session = STORE.get(session_id)
    trace = []
    out = run_agent(
        body.message,
        history=session["history"],
        trace=trace,
        force_offline=body.force_offline,
    )

    if out.get("messages"):
        session["history"] = out["messages"]
    else:
        STORE.append_turn(session_id, "user", body.message)
        STORE.append_turn(session_id, "assistant", out["reply"])

    if out.get("result") and out["result"].get("plan"):
        STORE.record_quote(session_id, out["result"]["summary"])

    return MessageOut(session_id=session_id, reply=out["reply"],
                      trace=out.get("trace", []), result=out.get("result"))


@app.get("/session/{session_id}")
def get_session(session_id: str):
    session = STORE.get(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="session not found")
    return {"session_id": session_id,
            "turns": len(session["history"]),
            "quotes": session["quotes"]}


@app.post("/tool/source")
def tool_source(body: SourceIn):
    """Direct optimizer access, no LLM in the path."""
    items = [{"query": li.query, "quantity": li.quantity} for li in body.line_items]
    return source_project(items, dest_region=body.dest_region, headroom=body.headroom)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("api:app", host="127.0.0.1", port=8000, reload=False)