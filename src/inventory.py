"""
inventory.py
Decides how much of each SKU sits in each FC before the day starts.

This is the half of the problem that routing optimization cannot fix. The
optimizer can only ship what a building already holds, so placement made
yesterday bounds what routing can achieve today.

Three allocation policies are implemented, one per scenario family:

  proportional_to_demand : Each FC holds stock in proportion to the demand of
                           the regions for which it is the nearest FC. Simple,
                           extremely common in practice, and provably
                           suboptimal because it ignores cost and coverage.

  optimized              : Allocate in proportion to the demand an FC can
                           reach within the 2-day window, discounted by how
                           expensive that FC's lanes are. Cost-aware.

  forward_positioned     : Same as cost-aware but with a superlinear demand
                           term, which deliberately over-concentrates stock
                           near the largest markets.
"""

import numpy as np
import pandas as pd

from config import FULFILLMENT_CENTERS, SAFETY_STOCK_Z


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _region_demand_for_day(demand_day: pd.DataFrame) -> pd.Series:
    """Total units demanded per region on the given day."""
    return demand_day.groupby("region_id")["units"].sum()


# ---------------------------------------------------------------------------
# Policy 1: proportional to nearest-FC demand
# ---------------------------------------------------------------------------

def _fc_weights_proportional(lanes: pd.DataFrame,
                             region_demand: pd.Series) -> pd.Series:
    """
    Weight each FC by the demand of the regions for which it is the closest.

    This mirrors how networks grow organically. A building opens, and the
    demand around it gets assigned to it. No consideration of whether that
    building is expensive to operate or whether a neighbor could serve the
    same region within the promise window.
    """
    nearest = lanes.loc[lanes.groupby("region_id")["road_miles"].idxmin()]
    nearest = nearest.set_index("region_id")["fc_id"]

    weights = {f: 0.0 for f in FULFILLMENT_CENTERS}
    for region, units in region_demand.items():
        f = nearest.get(region)
        if f is not None:
            weights[f] += float(units)

    s = pd.Series(weights)

    # Every FC receives a small floor so no building sits completely empty.
    # An empty FC is useless as a fallback when a neighbor stocks out, and
    # the greedy heuristic in Part 3 depends on having somewhere to fall
    # through to.
    s = s + s.sum() * 0.02
    return s / s.sum()


# ---------------------------------------------------------------------------
# Policy 2: cost-aware coverage weighting
# ---------------------------------------------------------------------------

def _fc_weights_cost_aware(lanes: pd.DataFrame,
                           region_demand: pd.Series) -> pd.Series:
    """
    Weight each FC by the demand it can reach within 2 days, discounted by
    the cost of reaching it.

    An FC that can serve a lot of demand cheaply should hold more stock than
    one that can only serve the same demand expensively. Dividing by lane
    cost implements that: cheap lanes contribute more weight per unit of
    demand than expensive ones.

    Only lanes that meet the 2-day promise contribute. Stock placed for the
    purpose of serving a 4-day lane does not help the service metric.
    """
    weights = {}
    for f in FULFILLMENT_CENTERS:
        sub = lanes[(lanes["fc_id"] == f) & (lanes["meets_2day"] == 1)]
        score = 0.0
        for r in sub.itertuples():
            d = float(region_demand.get(r.region_id, 0.0))
            score += d / max(r.total_cost_per_unit, 0.01)
        weights[f] = score

    s = pd.Series(weights)
    if s.sum() == 0:
        s = pd.Series({f: 1.0 for f in FULFILLMENT_CENTERS})
    s = s + s.sum() * 0.03
    return s / s.sum()


# ---------------------------------------------------------------------------
# Policy 3: forward positioning
# ---------------------------------------------------------------------------

def _fc_weights_forward(lanes: pd.DataFrame,
                        region_demand: pd.Series) -> pd.Series:
    """
    Forward positioning. Identical to the cost-aware policy except demand
    enters with an exponent of 1.5 rather than 1.0.

    The exponent is the whole idea. Raising demand to a power above 1 makes
    large markets count disproportionately, which pulls inventory toward the
    FCs that cover NYC, LAX, and Chicago and away from FCs covering thin
    territory.

    The bet: most volume concentrates in a handful of metros, so placing
    stock physically close to those metros buys more service improvement per
    unit of inventory than spreading evenly.

    The risk: concentration reduces flexibility. If a heavily loaded FC hits
    its throughput ceiling, there is less stock elsewhere to fall back on.
    The simulation is what determines whether the bet pays.
    """
    weights = {}
    for f in FULFILLMENT_CENTERS:
        sub = lanes[(lanes["fc_id"] == f) & (lanes["meets_2day"] == 1)]
        score = 0.0
        for r in sub.itertuples():
            d = float(region_demand.get(r.region_id, 0.0))
            score += (d ** 1.5) / max(r.total_cost_per_unit, 0.01)
        weights[f] = score

    s = pd.Series(weights)
    if s.sum() == 0:
        s = pd.Series({f: 1.0 for f in FULFILLMENT_CENTERS})
    s = s + s.sum() * 0.02
    return s / s.sum()


# ---------------------------------------------------------------------------
# Main allocation entry point
# ---------------------------------------------------------------------------

def allocate_inventory(lanes: pd.DataFrame,
                       demand_day: pd.DataFrame,
                       demand_stats: pd.DataFrame,
                       policy: str = "proportional_to_demand",
                       fill_rate_target: float = 1.15) -> pd.DataFrame:
    """
    Build the starting inventory position for one simulated day.

    Parameters
    ----------
    lanes : DataFrame
        FC x region lane table from network.build_lane_matrix().
    demand_day : DataFrame
        That day's demand, columns [region_id, sku_id, units].
    demand_stats : DataFrame
        Per region-SKU mean and standard deviation, from
        data/raw/demand_summary.csv. Used for safety stock sizing.
    policy : str
        One of proportional_to_demand, optimized, forward_positioned.
    fill_rate_target : float
        Stock the network to this multiple of expected demand. 1.15 means
        115% of what is expected to sell, roughly what a healthy DTC
        operation carries on hand for a same-day-ship model.

    Returns
    -------
    DataFrame with columns [fc_id, sku_id, units_available].
    """
    region_demand = _region_demand_for_day(demand_day)

    if policy == "proportional_to_demand":
        w = _fc_weights_proportional(lanes, region_demand)
    elif policy == "optimized":
        w = _fc_weights_cost_aware(lanes, region_demand)
    elif policy == "forward_positioned":
        w = _fc_weights_forward(lanes, region_demand)
    else:
        raise ValueError(f"Unknown allocation policy: {policy}")

    sku_demand = demand_day.groupby("sku_id")["units"].sum()

    # Safety stock uses the pooled standard deviation across regions.
    # Independent demands pool as the square root of the sum of variances,
    # not the sum of standard deviations. Summing standard deviations
    # directly would massively overstate required buffer, which is one of
    # the most common errors in inventory planning.
    sku_std = (
        demand_stats.groupby("sku_id")["std_daily"]
        .apply(lambda v: np.sqrt((v ** 2).sum()))
    )

    rows = []
    for sku, base_units in sku_demand.items():
        safety = SAFETY_STOCK_Z * float(sku_std.get(sku, 0.0))
        target_total = base_units * fill_rate_target + safety

        for f in FULFILLMENT_CENTERS:
            units = target_total * float(w.get(f, 0.0))
            rows.append({
                "fc_id": f,
                "sku_id": sku,
                "units_available": float(np.floor(units)),
            })

    inv = pd.DataFrame(rows)

    # Respect physical storage limits. If a policy tries to over-stuff a
    # building, scale that building's holdings back proportionally across
    # its SKUs. Scaling proportionally rather than truncating preserves the
    # SKU mix the policy intended.
    for f in FULFILLMENT_CENTERS:
        cap = FULFILLMENT_CENTERS[f]["storage_capacity"]
        mask = inv["fc_id"] == f
        held = inv.loc[mask, "units_available"].sum()
        if held > cap and held > 0:
            inv.loc[mask, "units_available"] = np.floor(
                inv.loc[mask, "units_available"] * (cap / held)
            )

    return inv


def inventory_report(inv: pd.DataFrame) -> pd.DataFrame:
    """Summary of where stock landed, with utilization against capacity."""
    rep = inv.groupby("fc_id")["units_available"].sum().reset_index()
    rep["storage_capacity"] = rep["fc_id"].map(
        lambda f: FULFILLMENT_CENTERS[f]["storage_capacity"]
    )
    rep["utilization_pct"] = (
        100 * rep["units_available"] / rep["storage_capacity"]
    ).round(1)
    rep["fc_name"] = rep["fc_id"].map(lambda f: FULFILLMENT_CENTERS[f]["name"])
    return rep.sort_values("units_available", ascending=False)


def compare_policies(lanes: pd.DataFrame,
                     demand_day: pd.DataFrame,
                     demand_stats: pd.DataFrame) -> pd.DataFrame:
    """
    Run all three policies on the same day and show where each puts stock.

    Useful as a diagnostic before running the full simulation, because the
    differences between policies should be visible in the allocation itself,
    not only in the downstream results.
    """
    out = {}
    for policy in ["proportional_to_demand", "optimized", "forward_positioned"]:
        inv = allocate_inventory(lanes, demand_day, demand_stats, policy=policy)
        out[policy] = inv.groupby("fc_id")["units_available"].sum()

    df = pd.DataFrame(out)
    df["fc_name"] = [FULFILLMENT_CENTERS[f]["name"] for f in df.index]
    # Share of total network inventory, which is the comparable number
    # across policies since totals differ slightly after capacity clipping.
    for c in ["proportional_to_demand", "optimized", "forward_positioned"]:
        df[f"{c}_pct"] = (100 * df[c] / df[c].sum()).round(1)
    return df