"""
sourcing_tool.py
The single function an AI agent calls to turn a parsed project list into an
optimized sourcing and fulfillment plan.

WHERE THIS SITS
---------------
    Pro types a messy project list
        -> agent (Part 7) parses it into structured line items
        -> THIS TOOL resolves each item to a SKU, checks inventory across FCs,
           runs the optimizer, and returns a plan + quote
        -> agent presents the quote and holds session state

The tool is deliberately a plain Python function with JSON-serializable input
and output, because that is exactly the contract a tool-calling LLM needs. The
agent does not need to know about PuLP, lanes, or haversine distance; it hands
over line items and a destination and gets back a plan.

The optimizer from Part 3 is reused unchanged. This module is the adapter that
makes a supply-chain optimizer usable as an agent tool.
"""

import numpy as np
import pandas as pd

from catalog import CATALOG, get_product
from match import resolve_line_item
from network import build_lane_matrix
from optimizer import FulfillmentOptimizer
from config import DEMAND_REGIONS, FULFILLMENT_CENTERS


# Lanes never change within a run, so build once at import.
_LANES = build_lane_matrix(save=False)


def _nearest_region(dest_region):
    """
    Map a requested destination to a known demand region. A Pro can name any
    supported metro; unknown names fall back to a common-alias table, then to
    the highest-demand metro as a last resort.
    """
    dest = (dest_region or "").upper().strip()
    if dest in DEMAND_REGIONS:
        return dest
    aliases = {
        "NEW YORK": "NYC", "MANHATTAN": "NYC", "BROOKLYN": "NYC",
        "LOS ANGELES": "LAX", "LA": "LAX",
        "CHICAGO": "CHI", "DALLAS": "DFW", "HOUSTON": "HOU",
        "WASHINGTON": "DCA", "DC": "DCA", "MIAMI": "MIA",
        "PHILADELPHIA": "PHL", "PHILLY": "PHL", "ATLANTA": "ATL",
        "BOSTON": "BOS", "PHOENIX": "PHX", "SEATTLE": "SEA",
        "PORTLAND": "PDX", "DENVER": "DEN", "SAN DIEGO": "SAN",
    }
    if dest in aliases:
        return aliases[dest]
    return "NYC"


def _synthetic_inventory_for_items(line_skus, dest_region, headroom=3.0):
    """
    Build a current on-hand inventory position for just the SKUs in this order,
    spread across FCs. A real system would query a live inventory service. For
    a self-contained demo, stock is seeded so that FCs closer to the destination
    hold more, which makes the optimizer's job realistic.

    headroom scales total stock relative to order size. Values below ~1 force
    partial stockouts, useful for demonstrating shortfall reporting.
    """
    dest_lanes = _LANES[_LANES["region_id"] == dest_region]
    dist = dest_lanes.set_index("fc_id")["road_miles"].to_dict()
    max_d = max(dist.values()) if dist else 1.0
    weight = {f: (1.0 - 0.6 * dist.get(f, max_d) / max_d) for f in FULFILLMENT_CENTERS}
    wsum = sum(weight.values())

    rows = []
    for sku_id, qty in line_skus.items():
        total_stock = float(np.ceil(qty * headroom))
        for f in FULFILLMENT_CENTERS:
            rows.append({
                "fc_id": f,
                "sku_id": sku_id,
                "units_available": float(np.floor(total_stock * weight[f] / wsum)),
            })
    return pd.DataFrame(rows)


def source_project(line_items, dest_region, headroom=3.0):
    """
    The agent-callable entry point.

    Parameters
    ----------
    line_items : list of dicts, each {"query": str, "quantity": number}
    dest_region : str, where the Pro wants delivery
    headroom : float, inventory abundance multiplier for demo stock

    Returns a JSON-serializable dict with destination, resolution, unresolved,
    plan, and summary.
    """
    dest = _nearest_region(dest_region)

    resolved = []
    unresolved = []
    demand_rows = []

    for item in line_items:
        query = item.get("query", "")
        qty = float(item.get("quantity", 0) or 0)
        decision = resolve_line_item(query)

        record = {
            "query": query,
            "quantity": qty,
            "status": decision["status"],
            "candidates": decision["candidates"][:3],
        }

        if decision["status"] == "matched" and qty > 0:
            sku_id = decision["sku_id"]
            product = get_product(sku_id)
            record["sku_id"] = sku_id
            record["product_name"] = product["name"]
            record["unit"] = product["unit"]
            resolved.append(record)
            demand_rows.append({"region_id": dest, "sku_id": sku_id, "units": qty})
        else:
            unresolved.append(record)

    if not demand_rows:
        return {
            "destination": dest,
            "resolution": resolved,
            "unresolved": unresolved,
            "plan": None,
            "summary": {"resolved_items": 0, "unresolved_items": len(unresolved)},
        }

    demand = (
        pd.DataFrame(demand_rows)
        .groupby(["region_id", "sku_id"], as_index=False)["units"].sum()
    )
    line_skus = demand.set_index("sku_id")["units"].to_dict()
    inventory = _synthetic_inventory_for_items(line_skus, dest, headroom)

    # fixed_cost_scale=0: the FCs are already open and staffed. A single order
    # should be priced on marginal shipping and handling, not charged a full
    # day of warehouse fixed cost. With the full daily fixed cost included, the
    # optimizer would refuse to open any building for a small order and quote a
    # total stockout, which is correct for the network study but wrong here.
    opt = FulfillmentOptimizer(
        lanes=_LANES, inventory=inventory, demand=demand, enforce_service=True,
        fixed_cost_scale=0.0,
    )
    result = opt.build().solve().extract()

    if not result["metrics"].get("feasible"):
        return {
            "destination": dest,
            "resolution": resolved,
            "unresolved": unresolved,
            "plan": None,
            "summary": {"status": "no_feasible_plan", "resolved_items": len(resolved)},
        }

    ship = result["shipments"]
    unmet = result["unmet"]
    has_ship = len(ship) > 0 and "sku_id" in ship.columns
    has_unmet = len(unmet) > 0 and "sku_id" in unmet.columns

    plan_lines = []
    for sku_id in line_skus:
        s = ship[ship["sku_id"] == sku_id] if has_ship else ship.iloc[0:0]
        product = get_product(sku_id)
        allocations = [
            {
                "fc_id": r.fc_id,
                "fc_name": FULFILLMENT_CENTERS[r.fc_id]["name"],
                "units": round(r.units, 0),
                "miles": r.miles,
                "meets_2day": bool(r.meets_2day),
                "ship_cost": round(r.ship_cost, 2),
            }
            for r in s.itertuples()
        ]
        short = (
            unmet[unmet["sku_id"] == sku_id]["unmet_units"].sum()
            if has_unmet else 0.0
        )
        plan_lines.append({
            "sku_id": sku_id,
            "product_name": product["name"],
            "unit": product["unit"],
            "requested": round(line_skus[sku_id], 0),
            "sourced_from": allocations,
            "shortfall": round(float(short), 0),
        })

    m = result["metrics"]
    quote_ship_cost = round(ship["ship_cost"].sum(), 2) if has_ship else 0.0

    summary = {
        "resolved_items": len(resolved),
        "unresolved_items": len(unresolved),
        "total_units_sourced": round(ship["units"].sum(), 0) if has_ship else 0.0,
        "total_shortfall": round(m["total_unmet_units"], 0),
        "estimated_shipping_cost": quote_ship_cost,
        "two_day_service_level": round(m["service_level"], 4),
        "fcs_used": m["fcs_open"],
        "solve_time_sec": m["solve_time_sec"],
    }

    return {
        "destination": dest,
        "resolution": resolved,
        "unresolved": unresolved,
        "plan": {"lines": plan_lines},
        "summary": summary,
    }


# The JSON schema the agent's tool definition advertises to the LLM. Kept next
# to the implementation so the two never drift apart.
TOOL_SCHEMA = {
    "name": "source_project",
    "description": (
        "Resolve a professional customer's project material list into catalog "
        "SKUs, check inventory across fulfillment centers, and return an "
        "optimized sourcing and fulfillment plan with an estimated shipping "
        "cost and two-day delivery service level. Call this once the project "
        "line items and a destination city are known."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "line_items": {
                "type": "array",
                "description": "Parsed project items with quantities.",
                "items": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string",
                                  "description": "Pro-speak product description."},
                        "quantity": {"type": "number"},
                    },
                    "required": ["query", "quantity"],
                },
            },
            "dest_region": {
                "type": "string",
                "description": "Destination city or supported metro code.",
            },
        },
        "required": ["line_items", "dest_region"],
    },
}


if __name__ == "__main__":
    import json
    demo = [
        {"query": "half inch copper elbow", "quantity": 40},
        {"query": "12-2 romex 250ft", "quantity": 6},
        {"query": "2x4 studs 8ft", "quantity": 120},
        {"query": "5 gal white interior paint", "quantity": 8},
        {"query": "purple widget frobnicator", "quantity": 3},
    ]
    out = source_project(demo, dest_region="Atlanta")
    print(json.dumps(out["summary"], indent=2))
    print("\nUNRESOLVED:", [u["query"] for u in out["unresolved"]])
    print("\nPLAN LINES:")
    for line in out["plan"]["lines"]:
        srcs = ", ".join(f"{a['fc_name']}:{a['units']:.0f}"
                         for a in line["sourced_from"])
        print(f"  {line['requested']:>4.0f} {line['unit']:<6} "
              f"{line['product_name'][:34]:<34} from {srcs}")