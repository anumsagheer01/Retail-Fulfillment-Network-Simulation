"""Single-day smoke test for the MIP. Run before building the harness."""
import sys
sys.path.insert(0, "src")

import numpy as np
import pandas as pd

from config import FULFILLMENT_CENTERS, RAW_DATA_DIR
from network import build_lane_matrix
from optimizer import FulfillmentOptimizer, nearest_fc_heuristic

# Load one day of demand
orders = pd.read_csv(f"{RAW_DATA_DIR}/orders.csv", parse_dates=["date"])
day = pd.Timestamp("2024-03-14")
demand = (
    orders[orders["date"] == day]
    .groupby(["region_id", "sku_id"], as_index=False)["units"].sum()
)

lanes = build_lane_matrix(save=False)

# Simple even-split inventory so this test does not depend on Part 4.
# Each FC gets an equal share of 130% of the day's demand per SKU.
sku_totals = demand.groupby("sku_id")["units"].sum()
inv_rows = []
for sku, total in sku_totals.items():
    per_fc = np.floor(total * 1.30 / len(FULFILLMENT_CENTERS))
    for f in FULFILLMENT_CENTERS:
        inv_rows.append({"fc_id": f, "sku_id": sku,
                         "units_available": float(per_fc)})
inventory = pd.DataFrame(inv_rows)

print(f"Test day: {day.date()}")
print(f"Demand:   {demand['units'].sum():,.0f} units "
      f"across {len(demand)} region-SKU pairs")
print(f"Stocked:  {inventory['units_available'].sum():,.0f} units\n")

# --- Baseline heuristic ---
h = nearest_fc_heuristic(lanes, inventory, demand)
hm = h["metrics"]
print("HEURISTIC (nearest FC)")
print(f"  miles/unit    {hm['avg_miles_per_unit']:>10.1f}")
print(f"  ship $/unit   {hm['cost_per_unit']:>10.3f}")
print(f"  service level {hm['service_level']:>10.2%}")
print(f"  FCs used      {hm['fc_count_open']:>10d}")
print(f"  objective     {hm['objective_value']:>10,.0f}")

# --- MIP, cost minimizing, no hard service constraint ---
o2 = FulfillmentOptimizer(lanes, inventory, demand,
                          enforce_service=False).build().solve().extract()
m2 = o2["metrics"]
print("\nMIP (cost minimizing, soft service penalty only)")
print(f"  status        {m2['status']:>10}")
print(f"  solve time    {m2['solve_time_sec']:>10.2f}s")
print(f"  miles/unit    {m2['avg_miles_per_unit']:>10.1f}")
print(f"  ship $/unit   {m2['cost_per_unit']:>10.3f}")
print(f"  service level {m2['service_level']:>10.2%}")
print(f"  FCs used      {m2['fc_count_open']:>10d}  ({m2['fcs_open']})")
print(f"  objective     {m2['objective_value']:>10,.0f}")

# --- MIP with the hard 93% service constraint ---
o3 = FulfillmentOptimizer(lanes, inventory, demand,
                          enforce_service=True).build().solve().extract()
m3 = o3["metrics"]
print("\nMIP (hard 93% service constraint)")
print(f"  status        {m3['status']:>10}")
print(f"  solve time    {m3['solve_time_sec']:>10.2f}s")
print(f"  miles/unit    {m3['avg_miles_per_unit']:>10.1f}")
print(f"  ship $/unit   {m3['cost_per_unit']:>10.3f}")
print(f"  service level {m3['service_level']:>10.2%}")
print(f"  FCs used      {m3['fc_count_open']:>10d}  ({m3['fcs_open']})")
print(f"  objective     {m3['objective_value']:>10,.0f}")

# --- Comparison ---
print("\n" + "=" * 52)
print(f"Miles reduction, MIP-cost vs heuristic:  "
      f"{100 * (m2['avg_miles_per_unit'] - hm['avg_miles_per_unit']) / hm['avg_miles_per_unit']:+.1f}%")
print(f"Miles reduction, MIP-service vs heuristic: "
      f"{100 * (m3['avg_miles_per_unit'] - hm['avg_miles_per_unit']) / hm['avg_miles_per_unit']:+.1f}%")
print(f"Cost of the service constraint: "
      f"{100 * (m3['objective_value'] - m2['objective_value']) / m2['objective_value']:+.2f}% on objective")
print("=" * 52)

# --- Correctness assertions ---
assert m2["status"] == "Optimal", "cost-min MIP did not solve"
assert m3["status"] == "Optimal", "service-constrained MIP did not solve"
assert m3["service_level"] >= 0.9299, "service constraint was violated"
assert m2["objective_value"] <= m3["objective_value"] + 1, \
    "constrained solution beat unconstrained, which is impossible"
print("\nAll assertions passed.")