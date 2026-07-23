"""Quick inspection of the lane matrix."""
import pandas as pd

lanes = pd.read_csv("data/processed/lane_matrix.csv")

print("Cheapest 5 lanes:")
print(lanes.nsmallest(5, "total_cost_per_unit")[
    ["fc_id", "region_id", "road_miles", "zone", "total_cost_per_unit", "meets_2day"]
].to_string(index=False))

print("\nMost expensive 5 lanes:")
print(lanes.nlargest(5, "total_cost_per_unit")[
    ["fc_id", "region_id", "road_miles", "zone", "total_cost_per_unit", "meets_2day"]
].to_string(index=False))

print("\nLanes that just miss the 2-day cutoff (1000-1100 road miles):")
near = lanes[(lanes.road_miles > 1000) & (lanes.road_miles < 1100)]
print(near[["fc_id", "region_id", "road_miles", "zone", "transit_days"]]
      .sort_values("road_miles").to_string(index=False))

print("\nCost gap, 2-day lanes vs the rest:")
print(lanes.groupby("meets_2day")["total_cost_per_unit"]
      .agg(["count", "mean", "min", "max"]).round(2).to_string())