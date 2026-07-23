"""
generate_demand.py
Builds a synthetic but realistic year of e-commerce order history.

Why synthetic: real order-level retail data is proprietary. What matters for a
network design study is that the demand has the *shape* real demand has:
weekly rhythm, holiday peaks, regional skew, and SKU-level variance. This
module produces exactly that, reproducibly.

Output: data/raw/orders.csv          (one row per region-SKU-day)
        data/raw/demand_summary.csv  (per region-SKU mean/std)
        data/raw/sku_catalog.csv     (product master)
"""

import os
import numpy as np
import pandas as pd

from config import (
    RANDOM_SEED, SIM_START_DATE, SIM_DAYS, N_SKUS,
    DEMAND_REGIONS, RAW_DATA_DIR,
)


# ---------------------------------------------------------------------------
# Demand components
# ---------------------------------------------------------------------------

def weekly_multiplier(dates: pd.DatetimeIndex) -> np.ndarray:
    """
    E-commerce demand is not flat across the week.
    Monday/Tuesday are heaviest (weekend browsing converts), Saturday is the
    trough. Multipliers indexed by dayofweek where Monday == 0.
    """
    pattern = np.array([1.18, 1.12, 1.02, 0.98, 0.95, 0.82, 0.93])
    return pattern[dates.dayofweek.values]


def seasonal_multiplier(dates: pd.DatetimeIndex) -> np.ndarray:
    """
    Annual seasonality with a Q4 peak. Two pieces:
      1. A smooth sinusoid for the general summer-dip / winter-lift shape.
      2. Explicit event spikes for the days that actually matter in retail.
    """
    doy = dates.dayofyear.values
    # Smooth annual wave: trough around day 180 (late June), peak near year end
    smooth = 1.0 + 0.15 * np.cos(2 * np.pi * (doy - 350) / 365.0)

    # Event spikes. Approximate fixed dates for a non-leap simulation year.
    spike = np.ones(len(dates))
    events = {
        (11, 29): 3.10,   # Black Friday
        (11, 30): 2.40,   # Saturday after
        (12,  2): 3.60,   # Cyber Monday
        (12,  3): 2.20,
        (12,  4): 1.90,
        (7,  16): 2.30,   # mid-summer sale event (Prime-Day analog)
        (7,  17): 2.10,
        (12, 15): 1.55,   # last shipping cutoff rush
        (12, 16): 1.60,
        (12, 17): 1.45,
        (1,   2): 1.35,   # post-holiday returns/replacement buying
        (5,  10): 1.25,   # Mother's Day window
        (2,  12): 1.20,   # Valentine's window
    }
    months = dates.month.values
    days = dates.day.values
    for (m, d), mult in events.items():
        spike[(months == m) & (days == d)] = mult

    # General ramp into December
    december_ramp = np.where(
        months == 12, 1.0 + 0.012 * np.clip(20 - days, 0, 20), 1.0
    )

    return smooth * spike * december_ramp


def growth_trend(n_days: int, annual_growth: float = 0.18) -> np.ndarray:
    """Gentle compounding growth so the year isn't stationary."""
    daily = (1 + annual_growth) ** (1 / 365.0)
    return daily ** np.arange(n_days)


# ---------------------------------------------------------------------------
# SKU catalog
# ---------------------------------------------------------------------------

def build_sku_catalog(rng: np.random.Generator) -> pd.DataFrame:
    """
    12 SKUs across three velocity classes. Real catalogs are Pareto: a few
    SKUs carry most of the volume. We model that with an A/B/C split.

    unit_weight_lb : matters because shipping cost scales with it
    demand_share   : fraction of total company volume this SKU carries
    cv             : coefficient of variation, how spiky this SKU is
    """
    rows = []
    # A items: 3 SKUs, ~60% of volume, low variability
    # B items: 4 SKUs, ~30% of volume, medium variability
    # C items: 5 SKUs, ~10% of volume, high variability
    classes = (
        [("A", 0.60 / 3, 0.22)] * 3
        + [("B", 0.30 / 4, 0.38)] * 4
        + [("C", 0.10 / 5, 0.65)] * 5
    )
    for i, (cls, share, cv) in enumerate(classes, start=1):
        rows.append({
            "sku_id": f"SKU_{i:03d}",
            "abc_class": cls,
            "demand_share": share,
            "cv": cv,
            "unit_weight_lb": round(float(rng.uniform(0.5, 12.0)), 2),
            "unit_cost": round(float(rng.uniform(8.0, 95.0)), 2),
            "unit_price": 0.0,  # filled below
        })
    df = pd.DataFrame(rows)
    # Price = cost * margin multiplier, higher margin on slow-moving C items
    margin = df["abc_class"].map({"A": 1.45, "B": 1.70, "C": 2.10})
    df["unit_price"] = (df["unit_cost"] * margin).round(2)
    return df


# ---------------------------------------------------------------------------
# Main generator
# ---------------------------------------------------------------------------

def generate(total_annual_units: int = 3_600_000) -> tuple:
    """
    Generate the full order history.

    total_annual_units : company-wide units shipped in the simulated year.
                         3.6M units/yr ~ a mid-size DTC brand.
    """
    rng = np.random.default_rng(RANDOM_SEED)

    dates = pd.date_range(SIM_START_DATE, periods=SIM_DAYS, freq="D")
    skus = build_sku_catalog(rng)

    # Daily company-level demand curve
    base_daily = total_annual_units / SIM_DAYS
    daily_index = (
        weekly_multiplier(dates)
        * seasonal_multiplier(dates)
        * growth_trend(SIM_DAYS)
    )
    # Renormalize so the year still totals total_annual_units
    daily_index = daily_index / daily_index.mean()
    daily_total = base_daily * daily_index

    # Region weights normalized to shares
    region_ids = list(DEMAND_REGIONS.keys())
    region_w = np.array([DEMAND_REGIONS[r]["weight"] for r in region_ids])
    region_share = region_w / region_w.sum()

    records = []
    for si, sku in skus.iterrows():
        sku_daily = daily_total * sku["demand_share"]
        for ri, region in enumerate(region_ids):
            mean_series = sku_daily * region_share[ri]

            # Negative binomial via gamma-Poisson mixture.
            # Gives overdispersed counts, which is what real order data looks
            # like. Variance > mean, controlled by cv.
            shape = 1.0 / (sku["cv"] ** 2)
            scale = mean_series / shape
            lam = rng.gamma(shape=shape, scale=scale)
            units = rng.poisson(lam)

            records.append(pd.DataFrame({
                "date": dates,
                "region_id": region,
                "sku_id": sku["sku_id"],
                "units": units,
            }))

    orders = pd.concat(records, ignore_index=True)
    orders = orders[orders["units"] > 0].reset_index(drop=True)

    # Attach useful attributes
    orders = orders.merge(
        skus[["sku_id", "abc_class", "unit_weight_lb", "unit_cost", "unit_price"]],
        on="sku_id", how="left",
    )
    orders["revenue"] = (orders["units"] * orders["unit_price"]).round(2)
    orders["total_weight_lb"] = (orders["units"] * orders["unit_weight_lb"]).round(2)
    orders["dow"] = orders["date"].dt.dayofweek
    orders["month"] = orders["date"].dt.month
    orders["week"] = orders["date"].dt.isocalendar().week.astype(int)

    # Summary table used later for safety stock and allocation
    summary = (
        orders.groupby(["region_id", "sku_id"])["units"]
        .agg(mean_daily="mean", std_daily="std", total_units="sum",
             days_active="count")
        .reset_index()
    )
    summary["std_daily"] = summary["std_daily"].fillna(0.0)
    summary["cv"] = (
        (summary["std_daily"] / summary["mean_daily"])
        .replace([np.inf, -np.inf], 0)
        .fillna(0)
    )

    os.makedirs(RAW_DATA_DIR, exist_ok=True)
    orders.to_csv(f"{RAW_DATA_DIR}/orders.csv", index=False)
    summary.to_csv(f"{RAW_DATA_DIR}/demand_summary.csv", index=False)
    skus.to_csv(f"{RAW_DATA_DIR}/sku_catalog.csv", index=False)

    return orders, summary, skus


if __name__ == "__main__":
    orders, summary, skus = generate()
    print(f"Generated {len(orders):,} order-line rows")
    print(f"Total units:   {orders['units'].sum():,}")
    print(f"Total revenue: ${orders['revenue'].sum():,.0f}")
    print(f"Date range:    {orders['date'].min().date()} "
          f"to {orders['date'].max().date()}")
    print("\nUnits by month:")
    print(orders.groupby("month")["units"].sum().to_string())
    print("\nTop regions:")
    print(orders.groupby("region_id")["units"].sum().nlargest(5).to_string())