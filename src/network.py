"""
network.py
Converts geography into the numbers the optimizer needs.

Three transformations happen here:
  1. Great-circle distance between every FC and every demand region.
  2. Road-distance approximation (great-circle inflated by a circuity factor).
  3. Zone lookup, which yields shipping cost per unit and transit days.

Output: data/processed/lane_matrix.csv
One row per (fc_id, region_id) pair. In supply chain terminology that pair
is called a "lane".
"""

import os
import numpy as np
import pandas as pd

from config import (
    FULFILLMENT_CENTERS, DEMAND_REGIONS, SHIPPING_ZONES,
    DELIVERY_TARGET_DAYS, PROCESSED_DATA_DIR,
)

EARTH_RADIUS_MILES = 3958.8

# Trucks follow roads, not straight lines. Road distance typically runs
# 15-25% longer than the great-circle distance. 1.20 is the standard
# planning assumption for US network design.
CIRCUITY_FACTOR = 1.20


def haversine_miles(lat1, lon1, lat2, lon2):
    """
    Great-circle distance in miles between two lat/lon points.

    The haversine formula accounts for the curvature of the earth. Treating
    lat/lon as flat Euclidean coordinates would badly distort east-west
    distances at US latitudes, since a degree of longitude is roughly 54
    miles in Seattle but 60 miles in Miami. That error would propagate
    directly into shipping cost, so haversine is not optional here.

    Accepts scalars or numpy arrays.
    """
    lat1, lon1, lat2, lon2 = map(np.radians, [lat1, lon1, lat2, lon2])
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    a = np.sin(dlat / 2.0) ** 2 + np.cos(lat1) * np.cos(lat2) * np.sin(dlon / 2.0) ** 2
    return 2 * EARTH_RADIUS_MILES * np.arcsin(np.sqrt(a))


def lookup_zone(miles: float):
    """
    Map a road distance to a carrier zone.

    SHIPPING_ZONES is ordered by ascending max_miles, so the first band whose
    ceiling exceeds the distance is the correct one. Returns a 4-tuple:
    (zone_name, base_cost, cost_per_mile, transit_days).
    """
    for max_miles, zone, base, per_mile, days in SHIPPING_ZONES:
        if miles <= max_miles:
            return zone, base, per_mile, days
    # Unreachable given the 99999 catch-all band, but kept as a guard
    # against someone editing the rate card and removing it.
    _, zone, base, per_mile, days = SHIPPING_ZONES[-1]
    return zone, base, per_mile, days


def build_lane_matrix(save: bool = True) -> pd.DataFrame:
    """
    Build the full FC x Region lane table.

    Each row carries distance, zone, per-unit cost, transit days, and a
    binary flag for whether the lane satisfies the 2-day delivery promise.
    That binary flag is what makes the service-level constraint in the
    optimizer expressible as a linear inequality.
    """
    rows = []
    for fc_id, fc in FULFILLMENT_CENTERS.items():
        for region_id, reg in DEMAND_REGIONS.items():
            gc = haversine_miles(fc["lat"], fc["lon"], reg["lat"], reg["lon"])
            road = gc * CIRCUITY_FACTOR
            zone, base, per_mile, transit = lookup_zone(road)

            ship_cost = base + per_mile * road

            rows.append({
                "fc_id": fc_id,
                "fc_name": fc["name"],
                "region_id": region_id,
                "great_circle_miles": round(gc, 1),
                "road_miles": round(road, 1),
                "zone": zone,
                "ship_cost_per_unit": round(ship_cost, 4),
                "transit_days": transit,
                "meets_2day": int(transit <= DELIVERY_TARGET_DAYS),
                "handling_cost_unit": fc["handling_cost_unit"],
                # Total variable cost to serve one unit on this lane.
                # Fixed FC cost is excluded here because it is incurred
                # per day, not per unit, and belongs in the objective
                # function attached to the binary open/closed variable.
                "total_cost_per_unit": round(ship_cost + fc["handling_cost_unit"], 4),
            })

    lanes = pd.DataFrame(rows)

    if save:
        os.makedirs(PROCESSED_DATA_DIR, exist_ok=True)
        lanes.to_csv(f"{PROCESSED_DATA_DIR}/lane_matrix.csv", index=False)

    return lanes


def nearest_fc_map(lanes: pd.DataFrame) -> dict:
    """
    Identify the physically closest FC for each region.

    Used by the Scenario 1 baseline heuristic in Part 4, and by the
    proportional inventory allocation policy. Returns {region_id: fc_id}.
    """
    idx = lanes.groupby("region_id")["road_miles"].idxmin()
    return lanes.loc[idx].set_index("region_id")["fc_id"].to_dict()


def coverage_report(lanes: pd.DataFrame) -> pd.DataFrame:
    """
    Count how many regions each FC can reach inside the 2-day promise.

    This is the single most useful diagnostic to run before optimizing
    anything. An FC that covers almost nothing indicates either a badly
    placed building or a hole in the network footprint.
    """
    cov = (
        lanes.groupby(["fc_id", "fc_name"])
        .agg(
            regions_within_2day=("meets_2day", "sum"),
            total_regions=("meets_2day", "count"),
            avg_miles=("road_miles", "mean"),
            avg_cost=("total_cost_per_unit", "mean"),
        )
        .reset_index()
    )
    cov["coverage_pct"] = (
        100 * cov["regions_within_2day"] / cov["total_regions"]
    ).round(1)
    return cov.sort_values("coverage_pct", ascending=False)


def region_reachability(lanes: pd.DataFrame) -> pd.DataFrame:
    """
    Flip the question: how many FCs can serve each region within 2 days?

    A region reachable by zero FCs is structurally unservable and caps the
    achievable service level. A region reachable by exactly one FC is a
    single point of failure, since one stockout or capacity crunch at that
    building breaks the promise for that entire market.
    """
    r = (
        lanes.groupby("region_id")
        .agg(
            fcs_within_2day=("meets_2day", "sum"),
            cheapest_lane=("total_cost_per_unit", "min"),
            nearest_miles=("road_miles", "min"),
        )
        .reset_index()
    )
    return r.sort_values("fcs_within_2day")


def structural_service_ceiling(lanes: pd.DataFrame,
                               region_weights: dict) -> float:
    """
    Compute the maximum service level achievable given the FC footprint,
    ignoring inventory and capacity entirely.

    Any region with zero 2-day-capable FCs contributes its full demand share
    to the miss bucket no matter how well the optimizer routes. Comparing
    this ceiling against the 93% target reveals whether the target is even
    attainable before a single variable is solved.
    """
    reach = region_reachability(lanes).set_index("region_id")
    total_w = sum(region_weights.values())

    unreachable_w = sum(
        w for region, w in region_weights.items()
        if reach.loc[region, "fcs_within_2day"] == 0
    )
    return round(1.0 - unreachable_w / total_w, 4)


if __name__ == "__main__":
    lanes = build_lane_matrix()

    print(f"Built {len(lanes)} lanes "
          f"({lanes['fc_id'].nunique()} FCs x {lanes['region_id'].nunique()} regions)\n")

    print("FC COVERAGE (regions reachable within 2 days)")
    print(coverage_report(lanes).to_string(index=False))

    print("\nREGIONS WITH WEAKEST COVERAGE")
    print(region_reachability(lanes).head(8).to_string(index=False))

    print("\nZONE DISTRIBUTION")
    print(lanes["zone"].value_counts().sort_index().to_string())

    weights = {r: v["weight"] for r, v in DEMAND_REGIONS.items()}
    ceiling = structural_service_ceiling(lanes, weights)
    print(f"\nSTRUCTURAL SERVICE CEILING: {ceiling:.2%}")
    print(f"Service target from config:  {0.93:.2%}")
    print("Target is attainable." if ceiling >= 0.93
          else "Target exceeds ceiling. Footprint cannot support it.")