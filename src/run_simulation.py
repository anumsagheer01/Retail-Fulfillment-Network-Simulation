"""
run_simulation.py
The experiment harness. Runs all four strategies over a sample of days and
collects comparable metrics.

WHY SAMPLE DAYS RATHER THAN ALL 365
-----------------------------------
Each MIP solve takes roughly a second. 365 days times three MIP scenarios is
about 20 minutes, which is acceptable for a final run and painful during
development. Days are therefore sampled in a stratified way: every month is
represented, and the heaviest days of the year are force-included.

Forcing the peaks in is not a convenience. On a normal-volume day the service
constraint is slack, because short lanes are also cheap lanes and cost
minimization produces good service for free. The constraint only binds when
capacity at the well-placed FCs runs out. A sample that omitted peak days
would show all four strategies performing nearly identically and would hide
the entire point of the study.
"""

import os
import argparse
import numpy as np
import pandas as pd

from config import SCENARIOS, RESULTS_DIR, RAW_DATA_DIR, RANDOM_SEED
from network import build_lane_matrix
from inventory import allocate_inventory, inventory_report
from optimizer import FulfillmentOptimizer, nearest_fc_heuristic


def stratified_day_sample(orders: pd.DataFrame, n_days: int = 24) -> list:
    """
    Select representative days: spread across months, plus the annual peaks.

    Peak days matter disproportionately because that is when the network
    breaks. A strategy that only works in March is not a strategy.
    """
    rng = np.random.default_rng(RANDOM_SEED)
    daily = orders.groupby("date")["units"].sum().sort_values(ascending=False)

    # Force-include the four heaviest days of the year.
    peaks = list(daily.head(4).index)

    # Sample the remainder evenly across months so no season is missing.
    all_dates = sorted(orders["date"].unique())
    by_month = {}
    for d in all_dates:
        by_month.setdefault(pd.Timestamp(d).month, []).append(d)

    picked = list(peaks)
    per_month = max(1, (n_days - len(peaks)) // 12)
    for m in sorted(by_month):
        candidates = [d for d in by_month[m] if d not in picked]
        if not candidates:
            continue
        chosen = rng.choice(
            len(candidates),
            size=min(per_month, len(candidates)),
            replace=False,
        )
        picked.extend([candidates[i] for i in chosen])

    return sorted(set(picked))[:n_days]


def run_one_day(date, orders, lanes, demand_stats, scenario_key, scenario_cfg):
    """Run a single scenario on a single day."""
    demand_day = (
        orders[orders["date"] == date]
        .groupby(["region_id", "sku_id"], as_index=False)["units"].sum()
    )
    if demand_day.empty:
        return None

    inv = allocate_inventory(
        lanes=lanes,
        demand_day=demand_day,
        demand_stats=demand_stats,
        policy=scenario_cfg["allocation"],
    )

    if scenario_cfg["method"] == "heuristic":
        result = nearest_fc_heuristic(lanes, inv, demand_day)
    else:
        opt = FulfillmentOptimizer(
            lanes=lanes,
            inventory=inv,
            demand=demand_day,
            enforce_service=scenario_cfg.get("enforce_service_constraint", True),
        )
        opt.build().solve()
        result = opt.extract()

    # The feasibility flag lives inside the metrics dict. Both the heuristic
    # and the MIP extractor return that same shape, including on failure,
    # so this check never needs to branch on which method ran.
    if not result.get("metrics", {}).get("feasible"):
        return None

    m = dict(result["metrics"])
    m["date"] = pd.Timestamp(date)
    m["scenario"] = scenario_key
    m["scenario_label"] = scenario_cfg["label"]
    m["demand_units"] = float(demand_day["units"].sum())

    inv_rep = inventory_report(inv)
    m["avg_storage_utilization"] = round(inv_rep["utilization_pct"].mean(), 1)

    return {"metrics": m, "shipments": result["shipments"], "inventory": inv}


def run(n_days: int = 24, save_detail: bool = True, verbose: bool = True):
    """Run every scenario across the sampled days."""
    orders = pd.read_csv(f"{RAW_DATA_DIR}/orders.csv", parse_dates=["date"])
    demand_stats = pd.read_csv(f"{RAW_DATA_DIR}/demand_summary.csv")
    lanes = build_lane_matrix()

    days = stratified_day_sample(orders, n_days=n_days)
    if verbose:
        print(f"Simulating {len(days)} days x {len(SCENARIOS)} scenarios "
              f"= {len(days) * len(SCENARIOS)} runs\n")

    all_metrics = []
    lane_detail = []

    for i, date in enumerate(days, 1):
        if verbose:
            day_units = orders.loc[orders["date"] == date, "units"].sum()
            print(f"[{i:2d}/{len(days)}] {pd.Timestamp(date).date()} "
                  f"({day_units:>6,} units)", end="  ")

        for skey, scfg in SCENARIOS.items():
            out = run_one_day(date, orders, lanes, demand_stats, skey, scfg)
            if out is None:
                if verbose:
                    print(f"{skey}:FAIL", end=" ")
                continue

            all_metrics.append(out["metrics"])

            if save_detail and len(out["shipments"]):
                sd = out["shipments"].copy()
                sd["date"] = pd.Timestamp(date)
                sd["scenario"] = skey
                lane_detail.append(sd)

            if verbose:
                print(f"{skey.split('_')[0]}:{out['metrics']['service_level']:.0%}",
                      end=" ")
        if verbose:
            print()

    results = pd.DataFrame(all_metrics)

    os.makedirs(RESULTS_DIR, exist_ok=True)
    results.to_csv(f"{RESULTS_DIR}/scenario_metrics.csv", index=False)

    if lane_detail:
        detail = pd.concat(lane_detail, ignore_index=True)
        detail.to_csv(f"{RESULTS_DIR}/lane_detail.csv", index=False)

    return results


def summarize(results: pd.DataFrame) -> pd.DataFrame:
    """
    Aggregate daily runs into the headline comparison table.

    Note the weighting throughout: miles per unit and cost per unit are
    computed as total divided by total, never as the mean of daily ratios.
    Averaging ratios weights a 7,000-unit Tuesday the same as a 25,000-unit
    Cyber Monday, which understates exactly the days that matter most. This
    is one of the most common analytical errors in operations reporting.
    """
    g = results.groupby(["scenario", "scenario_label"], as_index=False).agg(
        days=("date", "count"),
        total_demand=("demand_units", "sum"),
        total_shipped=("total_units_shipped", "sum"),
        total_unmet=("total_unmet_units", "sum"),
        total_miles=("total_miles", "sum"),
        total_ship_cost=("total_ship_cost", "sum"),
        total_fixed_cost=("total_fixed_cost", "sum"),
        avg_fcs_open=("fc_count_open", "mean"),
        avg_storage_util=("avg_storage_utilization", "mean"),
        avg_solve_sec=("solve_time_sec", "mean"),
    )

    g["miles_per_unit"] = (g["total_miles"] / g["total_shipped"]).round(1)
    g["ship_cost_per_unit"] = (g["total_ship_cost"] / g["total_shipped"]).round(3)
    g["total_cost"] = g["total_ship_cost"] + g["total_fixed_cost"]
    g["landed_cost_per_unit"] = (g["total_cost"] / g["total_shipped"]).round(3)
    g["fill_rate"] = (1 - g["total_unmet"] / g["total_demand"]).round(4)

    # Volume-weighted service level, for the same reason as above.
    sl = []
    for s in g["scenario"]:
        sub = results[results["scenario"] == s]
        weighted = (
            (sub["service_level"] * sub["total_units_shipped"]).sum()
            / sub["total_units_shipped"].sum()
        )
        sl.append(round(weighted, 4))
    g["service_level"] = sl

    # Deltas against the baseline heuristic.
    base = g[g["scenario"] == "S1_nearest_fc"].iloc[0]
    g["miles_vs_baseline_pct"] = (
        100 * (g["miles_per_unit"] - base["miles_per_unit"])
        / base["miles_per_unit"]
    ).round(2)
    g["cost_vs_baseline_pct"] = (
        100 * (g["landed_cost_per_unit"] - base["landed_cost_per_unit"])
        / base["landed_cost_per_unit"]
    ).round(2)
    g["service_vs_baseline_pp"] = (
        100 * (g["service_level"] - base["service_level"])
    ).round(2)

    g = g.sort_values("scenario")
    g.to_csv(f"{RESULTS_DIR}/scenario_summary.csv", index=False)
    return g


def print_summary(g: pd.DataFrame):
    """Console rendering of the headline table."""
    print("\n" + "=" * 88)
    print("SCENARIO COMPARISON")
    print("=" * 88)

    disp = pd.DataFrame({
        "Strategy": g["scenario_label"],
        "Mi/Unit": g["miles_per_unit"],
        "Mi vs base": g["miles_vs_baseline_pct"].map(lambda v: f"{v:+.1f}%"),
        "Service": g["service_level"].map(lambda v: f"{v:.1%}"),
        "Cost/Unit": g["landed_cost_per_unit"].map(lambda v: f"${v:.2f}"),
        "Cost vs base": g["cost_vs_baseline_pct"].map(lambda v: f"{v:+.1f}%"),
        "Fill": g["fill_rate"].map(lambda v: f"{v:.1%}"),
        "FCs": g["avg_fcs_open"].round(1),
    })
    print(disp.to_string(index=False))
    print("=" * 88)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=24,
                    help="number of simulated days to sample")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()

    results = run(n_days=args.days, verbose=not args.quiet)
    summary = summarize(results)
    print_summary(summary)