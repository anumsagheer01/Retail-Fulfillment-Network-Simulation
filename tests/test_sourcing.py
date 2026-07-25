"""Part 6 checks: product matching and the sourcing tool."""
import sys
sys.path.insert(0, "src")

from match import resolve_line_item, score_query
from sourcing_tool import source_project


def _assert_match(query, expected_sku):
    r = resolve_line_item(query)
    top = r["candidates"][0] if r["candidates"] else None
    assert top and top["sku_id"] == expected_sku, \
        f"{query!r} -> {top['sku_id'] if top else None}, expected {expected_sku}"

_assert_match("half inch copper elbow", "SKU_001")
_assert_match("1/2 cu 90 elbow", "SKU_001")
_assert_match("12-2 romex 250ft", "SKU_003")
_assert_match("2x4 studs 8ft", "SKU_005")
_assert_match("5 gal white interior paint", "SKU_011")
_assert_match("r13 batts", "SKU_009")
print("Pro-speak matching: all resolved correctly")

r = resolve_line_item("purple widget frobnicator")
assert r["status"] == "no_match", f"nonsense got status {r['status']}"
print("Nonsense correctly rejected as no_match")

half = score_query("1/2 copper elbow")[0]
assert half["sku_id"] == "SKU_001"
assert half["attribute_bonus"] > 0, "size facet did not contribute"
print("Attribute-based disambiguation works")

items = [
    {"query": "half inch copper elbow", "quantity": 40},
    {"query": "12-2 romex 250ft", "quantity": 6},
    {"query": "2x4 studs 8ft", "quantity": 120},
    {"query": "totally fake item xyz", "quantity": 3},
]
out = source_project(items, dest_region="Atlanta")

assert out["destination"] == "ATL"
assert out["summary"]["resolved_items"] == 3
assert out["summary"]["unresolved_items"] == 1
assert out["plan"] is not None
assert out["summary"]["total_shortfall"] == 0
assert out["summary"]["two_day_service_level"] >= 0.93
for line in out["plan"]["lines"]:
    assert len(line["sourced_from"]) >= 1, f"{line['sku_id']} sourced from nowhere"
print("Sourcing tool end-to-end: plan produced, service met, nonsense split out")

tight = source_project(
    [{"query": "2x4 studs 8ft", "quantity": 100000}],
    dest_region="Atlanta", headroom=0.5,
)
assert tight["summary"]["total_shortfall"] > 0, "thin stock should show shortfall"
assert tight["plan"] is not None, "should still return a partial plan"
print("Shortfall reporting works under thin inventory")

print("\nAll Part 6 checks passed.")