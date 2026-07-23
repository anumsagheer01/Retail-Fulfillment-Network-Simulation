"""
analyze.py
Turns simulation output into the findings and figures that go in the README.

Four analyses run here:
  1. Headline scenario comparison table.
  2. Peak-day stress analysis, which is where the strategies separate.
  3. FC utilization and the placement-versus-routing decomposition.
  4. Sensitivity sweep on the service target, producing the cost-service
     frontier.

Figures are written to outputs/figures/ as PNG.
"""

import os
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")          # non-interactive backend, required for saving
import matplotlib.pyplot as plt

from config import (
    FULFILLMENT_CENTERS, RESULTS_DIR, FIGURES_DIR, RAW_DATA_DIR,
    SERVICE_LEVEL_TARGET,
)

plt.rcParams.update({
    "figure.dpi": 130,
    "font.size": 9,
    "axes.grid": True,
    "grid.alpha": 0.25,
    "axes.spines.top": False,
    "axes.spines.right": False,
})

SCENARIO_ORDER = [
    "S1_nearest_fc", "S2_cost_min",
    "S3_service_constrained", "S4_pooled_forward",
]
SHORT_LABEL = {
    "S1_nearest_fc": "S1 Nearest FC",
    "S2_cost_min": "S2 Cost MIP",
    "S3_service_constrained": "S3 Service MIP",
    "S4_pooled_forward": "S4 Forward Pos.",
}
COLORS = {
    "S1_nearest_fc": "#94a3b8",
    "S2_cost_min": "#60a5fa",
    "S3_service_constrained": "#3b82f6",
    "S4_pooled_forward": "#1d4ed8",
}


def load():
    """Load simulation outputs written by run_simulation.py."""
    metrics = pd.read_csv(f"{RESULTS_DIR}/scenario_metrics.csv",
                          parse_dates=["date"])
    summary = pd.read_csv(f"{RESULTS_DIR}/scenario_summary.csv")
    detail = pd.read_csv(f"{RESULTS_DIR}/lane_detail.csv",
                         parse_dates=["date"])
    return metrics, summary, detail


# ---------------------------------------------------------------------------
# Analysis 1: headline comparison
# ---------------------------------------------------------------------------

def headline_table(summary: pd.DataFrame) -> pd.DataFrame:
    """The table that goes at the top of the README."""
    s = summary.set_index("scenario").loc[SCENARIO_ORDER].reset_index()
    out = pd.DataFrame({
        "Strategy": s["scenario_label"],
        "Miles/Unit": s["miles_per_unit"].round(1),
        "vs Baseline": s["miles_vs_baseline_pct"].map(lambda v: f"{v:+.1f}%"),
        "2-Day Service": s["service_level"].map(lambda v: f"{v:.1%}"),
        "Landed $/Unit": s["landed_cost_per_unit"].map(lambda v: f"${v:.2f}"),
        "Cost vs Base": s["cost_vs_baseline_pct"].map(lambda v: f"{v:+.1f}%"),
        "Avg FCs Open": s["avg_fcs_open"].round(1),
    })
    return out


# ---------------------------------------------------------------------------
# Analysis 2: peak-day stress
# ---------------------------------------------------------------------------

def peak_analysis(metrics: pd.DataFrame, top_n: int = 4) -> pd.DataFrame:
    """
    Compare performance on the heaviest days against ordinary days.

    This separates the strategies. On normal volume the network has capacity
    headroom and every approach performs similarly. Under peak load the
    well-placed FCs saturate and routing quality starts to matter.
    """
    daily_demand = metrics.groupby("date")["demand_units"].first()
    peak_dates = set(daily_demand.nlargest(top_n).index)

    metrics = metrics.copy()
    metrics["day_type"] = np.where(
        metrics["date"].isin(peak_dates), "Peak", "Normal"
    )

    g = metrics.groupby(["scenario", "day_type"]).apply(
        lambda d: pd.Series({
            "miles_per_unit": d["total_miles"].sum() / d["total_units_shipped"].sum(),
            "service_level": (
                (d["service_level"] * d["total_units_shipped"]).sum()
                / d["total_units_shipped"].sum()
            ),
            "cost_per_unit": (
                (d["total_ship_cost"].sum() + d["total_fixed_cost"].sum())
                / d["total_units_shipped"].sum()
            ),
            "avg_demand": d["demand_units"].mean(),
        }),
        include_groups=False,
    ).reset_index()

    return g


# ---------------------------------------------------------------------------
# Analysis 3: placement vs routing decomposition
# ---------------------------------------------------------------------------

def decompose_gains(summary: pd.DataFrame) -> pd.DataFrame:
    """
    Attribute the total improvement to its two sources.

    S1 -> S2 changes the routing method while holding allocation policy
    roughly constant. S3 -> S4 changes only the allocation policy while
    holding the routing model and the service constraint fixed. Comparing
    the two isolates how much each lever contributed.
    """
    s = summary.set_index("scenario")

    routing_miles = (
        100 * (s.loc["S2_cost_min", "miles_per_unit"]
               - s.loc["S1_nearest_fc", "miles_per_unit"])
        / s.loc["S1_nearest_fc", "miles_per_unit"]
    )
    placement_miles = (
        100 * (s.loc["S4_pooled_forward", "miles_per_unit"]
               - s.loc["S3_service_constrained", "miles_per_unit"])
        / s.loc["S3_service_constrained", "miles_per_unit"]
    )
    routing_service = 100 * (
        s.loc["S2_cost_min", "service_level"]
        - s.loc["S1_nearest_fc", "service_level"]
    )
    placement_service = 100 * (
        s.loc["S4_pooled_forward", "service_level"]
        - s.loc["S3_service_constrained", "service_level"]
    )

    return pd.DataFrame({
        "Lever": ["Routing (S1 to S2)", "Placement (S3 to S4)"],
        "Miles change": [f"{routing_miles:+.1f}%", f"{placement_miles:+.1f}%"],
        "Service change": [f"{routing_service:+.2f} pp",
                           f"{placement_service:+.2f} pp"],
    })


def fc_utilization(detail: pd.DataFrame) -> pd.DataFrame:
    """Share of volume handled by each FC under each strategy."""
    g = (
        detail.groupby(["scenario", "fc_id"])["units"].sum()
        .unstack(fill_value=0)
    )
    share = (100 * g.div(g.sum(axis=1), axis=0)).round(1)
    share.columns = [FULFILLMENT_CENTERS[c]["name"] for c in share.columns]
    return share.loc[[s for s in SCENARIO_ORDER if s in share.index]]


# ---------------------------------------------------------------------------
# Analysis 4: sensitivity sweep on the service target
# ---------------------------------------------------------------------------

def service_sensitivity(sample_days: int = 6,
                        targets=(0.90, 0.92, 0.93, 0.94, 0.95)) -> pd.DataFrame:
    """
    Re-solve at several service targets to trace the cost-service frontier.

    This answers the question a business stakeholder actually asks: what does
    each additional point of service cost. A single operating point does not
    answer that; a frontier does.
    """
    from network import build_lane_matrix
    from inventory import allocate_inventory
    from optimizer import FulfillmentOptimizer
    from run_simulation import stratified_day_sample

    orders = pd.read_csv(f"{RAW_DATA_DIR}/orders.csv", parse_dates=["date"])
    stats = pd.read_csv(f"{RAW_DATA_DIR}/demand_summary.csv")
    lanes = build_lane_matrix(save=False)
    days = stratified_day_sample(orders, n_days=sample_days)

    rows = []
    for target in targets:
        tot_units = tot_miles = tot_cost = tot_fast = 0.0
        infeasible = 0

        for d in days:
            dd = (
                orders[orders["date"] == d]
                .groupby(["region_id", "sku_id"], as_index=False)["units"].sum()
            )
            inv = allocate_inventory(lanes, dd, stats,
                                     policy="forward_positioned")
            res = (
                FulfillmentOptimizer(lanes, inv, dd, enforce_service=True,
                                     service_target=target)
                .build().solve().extract()
            )
            m = res["metrics"]
            if not m.get("feasible"):
                infeasible += 1
                continue
            tot_units += m["total_units_shipped"]
            tot_miles += m["total_miles"]
            tot_cost += m["total_ship_cost"] + m["total_fixed_cost"]
            tot_fast += m["service_level"] * m["total_units_shipped"]

        rows.append({
            "service_target": target,
            "achieved_service": round(tot_fast / tot_units, 4) if tot_units else 0,
            "miles_per_unit": round(tot_miles / tot_units, 1) if tot_units else 0,
            "cost_per_unit": round(tot_cost / tot_units, 3) if tot_units else 0,
            "infeasible_days": infeasible,
        })

    df = pd.DataFrame(rows)
    df.to_csv(f"{RESULTS_DIR}/service_sensitivity.csv", index=False)
    return df


# ---------------------------------------------------------------------------
# Figures
# ---------------------------------------------------------------------------

def fig_scenario_comparison(summary: pd.DataFrame):
    """Three-panel bar chart: miles, service, cost."""
    s = summary.set_index("scenario").loc[SCENARIO_ORDER]
    labels = [SHORT_LABEL[i] for i in s.index]
    colors = [COLORS[i] for i in s.index]

    fig, axes = plt.subplots(1, 3, figsize=(11, 3.6))

    axes[0].bar(labels, s["miles_per_unit"], color=colors)
    axes[0].set_title("Shipping miles per unit")
    axes[0].set_ylabel("miles")
    for i, v in enumerate(s["miles_per_unit"]):
        axes[0].text(i, v + 1.5, f"{v:.0f}", ha="center", fontsize=8)

    axes[1].bar(labels, s["service_level"] * 100, color=colors)
    axes[1].axhline(SERVICE_LEVEL_TARGET * 100, color="#dc2626",
                    ls="--", lw=1.2, label="93% target")
    axes[1].set_title("2-day service level")
    axes[1].set_ylabel("percent")
    axes[1].set_ylim(88, 100)
    axes[1].legend(fontsize=7)
    for i, v in enumerate(s["service_level"] * 100):
        axes[1].text(i, v + 0.3, f"{v:.1f}", ha="center", fontsize=8)

    axes[2].bar(labels, s["landed_cost_per_unit"], color=colors)
    axes[2].set_title("Landed cost per unit")
    axes[2].set_ylabel("USD")
    for i, v in enumerate(s["landed_cost_per_unit"]):
        axes[2].text(i, v + 0.12, f"${v:.2f}", ha="center", fontsize=8)

    for ax in axes:
        ax.tick_params(axis="x", rotation=20, labelsize=7.5)

    fig.tight_layout()
    fig.savefig(f"{FIGURES_DIR}/scenario_comparison.png", bbox_inches="tight")
    plt.close(fig)


def fig_service_by_day(metrics: pd.DataFrame):
    """Service level against daily volume, showing where strategies diverge."""
    fig, ax = plt.subplots(figsize=(9, 4))

    for s in SCENARIO_ORDER:
        sub = metrics[metrics["scenario"] == s].sort_values("demand_units")
        if sub.empty:
            continue
        ax.plot(sub["demand_units"], sub["service_level"] * 100,
                "o-", ms=4, lw=1.4, label=SHORT_LABEL[s], color=COLORS[s])

    ax.axhline(SERVICE_LEVEL_TARGET * 100, color="#dc2626", ls="--", lw=1.2)
    ax.text(metrics["demand_units"].max() * 0.72,
            SERVICE_LEVEL_TARGET * 100 + 0.15, "93% target",
            color="#dc2626", fontsize=8)
    ax.set_xlabel("Daily demand (units)")
    ax.set_ylabel("2-day service level (%)")
    ax.set_title("Service degrades under peak load, and the gap widens")
    ax.legend(fontsize=8)

    fig.tight_layout()
    fig.savefig(f"{FIGURES_DIR}/service_by_volume.png", bbox_inches="tight")
    plt.close(fig)


def fig_fc_utilization(share: pd.DataFrame):
    """Stacked bar of volume share by FC across strategies."""
    fig, ax = plt.subplots(figsize=(9, 4))
    bottom = np.zeros(len(share))
    palette = ["#1e3a8a", "#2563eb", "#60a5fa", "#93c5fd", "#c7d2fe", "#e0e7ff"]

    for i, col in enumerate(share.columns):
        ax.bar([SHORT_LABEL[s] for s in share.index], share[col],
               bottom=bottom, label=col, color=palette[i % len(palette)])
        bottom += share[col].values

    ax.set_ylabel("share of shipped volume (%)")
    ax.set_title("Volume shifts toward well-placed FCs under optimization")
    ax.legend(fontsize=7.5, ncol=3, loc="lower center",
              bbox_to_anchor=(0.5, -0.32))
    ax.tick_params(axis="x", labelsize=8)

    fig.tight_layout()
    fig.savefig(f"{FIGURES_DIR}/fc_utilization.png", bbox_inches="tight")
    plt.close(fig)


def fig_sensitivity(sens: pd.DataFrame):
    """Cost-service frontier from the sensitivity sweep."""
    fig, ax = plt.subplots(figsize=(6.5, 4))

    ax.plot(sens["achieved_service"] * 100, sens["cost_per_unit"],
            "o-", color="#1d4ed8", lw=1.6, ms=6)
    for _, r in sens.iterrows():
        ax.annotate(f"{r['service_target']:.0%}",
                    (r["achieved_service"] * 100, r["cost_per_unit"]),
                    textcoords="offset points", xytext=(6, -9), fontsize=7.5)

    ax.set_xlabel("achieved 2-day service level (%)")
    ax.set_ylabel("landed cost per unit (USD)")
    ax.set_title("Cost-service frontier (labels show the target imposed)")

    fig.tight_layout()
    fig.savefig(f"{FIGURES_DIR}/cost_service_frontier.png", bbox_inches="tight")
    plt.close(fig)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main(run_sensitivity: bool = True):
    os.makedirs(FIGURES_DIR, exist_ok=True)
    metrics, summary, detail = load()

    print("=" * 84)
    print("HEADLINE COMPARISON")
    print("=" * 84)
    print(headline_table(summary).to_string(index=False))

    print("\n" + "=" * 84)
    print("PEAK VS NORMAL DAYS")
    print("=" * 84)
    peak = peak_analysis(metrics)
    piv = peak.pivot(index="scenario", columns="day_type",
                     values=["miles_per_unit", "service_level"])
    piv = piv.loc[[s for s in SCENARIO_ORDER if s in piv.index]]
    piv.index = [SHORT_LABEL[i] for i in piv.index]
    print(piv.round(3).to_string())

    print("\n" + "=" * 84)
    print("GAIN DECOMPOSITION: ROUTING VS PLACEMENT")
    print("=" * 84)
    print(decompose_gains(summary).to_string(index=False))

    print("\n" + "=" * 84)
    print("FC VOLUME SHARE (%)")
    print("=" * 84)
    share = fc_utilization(detail)
    share.index = [SHORT_LABEL[i] for i in share.index]
    print(share.to_string())

    fig_scenario_comparison(summary)
    fig_service_by_day(metrics)
    fig_fc_utilization(fc_utilization(detail))
    print(f"\nFigures written to {FIGURES_DIR}/")

    if run_sensitivity:
        print("\n" + "=" * 84)
        print("SERVICE TARGET SENSITIVITY")
        print("=" * 84)
        sens = service_sensitivity()
        print(sens.to_string(index=False))
        fig_sensitivity(sens)


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-sensitivity", action="store_true")
    args = ap.parse_args()
    main(run_sensitivity=not args.no_sensitivity)