"""Compare the three inventory allocation policies on a single day."""
import sys
sys.path.insert(0, "src")

import pandas as pd

from config import RAW_DATA_DIR
from network import build_lane_matrix
from inventory import allocate_inventory, inventory_report, compare_policies

orders = pd.read_csv(f"{RAW_DATA_DIR}/orders.csv", parse_dates=["date"])
stats = pd.read_csv(f"{RAW_DATA_DIR}/demand_summary.csv")
lanes = build_lane_matrix(save=False)

day = pd.Timestamp("2024-03-14")
demand = (
    orders[orders["date"] == day]
    .groupby(["region_id", "sku_id"], as_index=False)["units"].sum()
)

print(f"Day: {day.date()}   Demand: {demand['units'].sum():,.0f} units\n")

cmp = compare_policies(lanes, demand, stats)
print("INVENTORY SHARE BY POLICY (% of network stock)")
print(cmp[["fc_name", "proportional_to_demand_pct",
           "optimized_pct", "forward_positioned_pct"]]
      .to_string(index=False))

print("\nSTORAGE UTILIZATION, forward-positioned policy")
inv = allocate_inventory(lanes, demand, stats, policy="forward_positioned")
print(inventory_report(inv)[
    ["fc_name", "units_available", "storage_capacity", "utilization_pct"]
].to_string(index=False))

# Concentration check: Herfindahl index of the inventory split.
# Higher means more concentrated. Forward positioning should score highest.
print("\nCONCENTRATION (Herfindahl index, higher = more concentrated)")
for c in ["proportional_to_demand", "optimized", "forward_positioned"]:
    share = cmp[c] / cmp[c].sum()
    print(f"  {c:<24} {(share ** 2).sum():.4f}")