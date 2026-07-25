"""Checks: the agent and the FastAPI service (offline mode)."""
import sys
sys.path.insert(0, "src")

from fastapi.testclient import TestClient
from agent import run_agent
from api import app

client = TestClient(app)


msg = ("I'm framing a basement in Atlanta. Need about 120 2x4 studs 8ft, "
       "6 rolls of 12-2 romex 250ft, 40 half inch copper elbows, and "
       "8 buckets of white interior paint.")
out = run_agent(msg, trace=[], force_offline=True)
assert "ATL" in out["reply"]
assert out["result"]["summary"]["resolved_items"] == 4
assert out["result"]["summary"]["two_day_service_level"] >= 0.93
assert len(out["trace"]) == 1
print("Agent offline: parsed 4 items, sourced, service met, trace captured")

noc = run_agent("I need 20 sheets of drywall", force_offline=True)
assert "city" in noc["reply"].lower()
print("Agent asks for destination when missing")

r = client.get("/health")
assert r.status_code == 200 and r.json()["status"] == "ok"
r = client.get("/catalog")
assert len(r.json()["families"]) == 12
print("Health and catalog endpoints work")

r = client.post("/session")
sid = r.json()["session_id"]
assert sid

r = client.post(f"/session/{sid}/message",
                json={"message": msg, "force_offline": True})
assert r.status_code == 200
body = r.json()
assert body["result"]["summary"]["resolved_items"] == 4
assert body["result"]["summary"]["estimated_shipping_cost"] > 0
print("Session message endpoint returns a quote")

r = client.get(f"/session/{sid}")
assert r.json()["turns"] >= 2
assert len(r.json()["quotes"]) == 1
print("Session state persists turns and quotes")

r = client.post("/session/doesnotexist/message",
                json={"message": "hi", "force_offline": True})
assert r.status_code == 404
print("Unknown session correctly returns 404")

r = client.post("/tool/source", json={
    "line_items": [{"query": "2x4 studs 8ft", "quantity": 50},
                   {"query": "r13 batts", "quantity": 30}],
    "dest_region": "Dallas",
})
assert r.status_code == 200
assert r.json()["summary"]["resolved_items"] == 2
assert r.json()["destination"] == "DFW"
print("Direct /tool/source endpoint works")

print("\nAll Part 7 checks passed.")