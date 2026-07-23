"""
optimizer.py
The mixed-integer optimization model.

THE DECISION PROBLEM
--------------------
Given one day of demand across 25 regions and 12 SKUs, and 6 FCs each holding
limited inventory with limited daily throughput, choose:

    x[f, r, s] : units of SKU s shipped from FC f to region r  (continuous)
    y[f]       : whether FC f is activated today               (binary)
    u[r, s]    : units of demand left unserved                 (continuous)

so that total cost is minimized subject to capacity, inventory, and the
service-level promise.

WHY MIXED-INTEGER
-----------------
The x variables are continuous. At tens of thousands of units per day,
fractional units are a harmless relaxation. The y variables are binary: an FC
is either open for the day and incurs its full fixed cost, or it is not.
Mixing continuous and binary variables is what makes this a MIP rather than a
plain LP, and it is what lets the model answer whether a marginal building is
worth activating on a slow Tuesday.
"""

import time
import numpy as np
import pandas as pd
import pulp

from config import (
    FULFILLMENT_CENTERS, SERVICE_LEVEL_TARGET, LATE_DELIVERY_PENALTY,
    STOCKOUT_PENALTY_PER_UNIT,
    SOLVER_TIME_LIMIT, SOLVER_MIP_GAP, SOLVER_MSG,
)


class FulfillmentOptimizer:
    """
    Builds and solves the single-period fulfillment assignment MIP.

    Parameters
    ----------
    lanes : DataFrame
        Output of network.build_lane_matrix().
    inventory : DataFrame
        Columns [fc_id, sku_id, units_available].
    demand : DataFrame
        Columns [region_id, sku_id, units] for a single day.
    enforce_service : bool
        If True, add the hard 93% two-day constraint. If False, delivery
        speed influences the solution only through the soft penalty term.
    """

    def __init__(self, lanes, inventory, demand, enforce_service=True,
                 service_target=SERVICE_LEVEL_TARGET):
        self.lanes = lanes
        self.inventory = inventory
        self.demand = demand
        self.enforce_service = enforce_service
        self.service_target = service_target

        self.fcs = sorted(FULFILLMENT_CENTERS.keys())
        self.regions = sorted(demand["region_id"].unique())
        self.skus = sorted(demand["sku_id"].unique())

        # Lookup dictionaries built once up front.
        # Filtering a DataFrame inside a constraint loop is the single
        # biggest performance trap when writing PuLP models: it turns an
        # O(n) build into O(n^2). Dict lookups keep the build linear.
        self.cost = {
            (r.fc_id, r.region_id): r.total_cost_per_unit
            for r in lanes.itertuples()
        }
        self.miles = {
            (r.fc_id, r.region_id): r.road_miles for r in lanes.itertuples()
        }
        self.meets_2day = {
            (r.fc_id, r.region_id): r.meets_2day for r in lanes.itertuples()
        }
        self.inv = {
            (r.fc_id, r.sku_id): r.units_available
            for r in inventory.itertuples()
        }
        self.dem = {
            (r.region_id, r.sku_id): r.units for r in demand.itertuples()
        }

        self.model = None
        self.x = None
        self.y = None
        self.u = None
        self.solution = None
        self.solve_time = None
        self.status = None

    # -----------------------------------------------------------------
    # Model construction
    # -----------------------------------------------------------------
    def build(self):
        """Construct the PuLP model: variables, objective, constraints."""
        m = pulp.LpProblem("Fulfillment_Network_Optimization", pulp.LpMinimize)

        # --- Decision variables -------------------------------------
        # Create x variables only for (f, r, s) triples where demand exists
        # and the FC actually holds that SKU. The dense grid would be
        # 6 x 25 x 12 = 1800 variables, most of which are forced to zero by
        # the inventory constraint anyway. Sparse construction cuts the
        # variable count by roughly half and speeds up every solve.
        valid_keys = [
            (f, r, s)
            for (r, s) in self.dem.keys()
            for f in self.fcs
            if self.inv.get((f, s), 0) > 0
        ]

        x = pulp.LpVariable.dicts("ship", valid_keys, lowBound=0,
                                  cat="Continuous")

        # Binary activation variable, one per FC.
        y = pulp.LpVariable.dicts("open", self.fcs, cat="Binary")

        # Unmet demand. Always permitted, but priced painfully.
        # A model that cannot express failure will simply report INFEASIBLE
        # and tell the analyst nothing about where or why it broke. Adding a
        # heavily penalized slack variable converts "no answer" into
        # "here is the answer, and here is exactly what could not be served."
        # This is the single most important modeling habit in this file.
        u = pulp.LpVariable.dicts(
            "unmet", list(self.dem.keys()), lowBound=0, cat="Continuous"
        )

        # --- Objective ----------------------------------------------
        ship_handle = pulp.lpSum(
            self.cost[(f, r)] * x[(f, r, s)] for (f, r, s) in valid_keys
        )
        fixed = pulp.lpSum(
            FULFILLMENT_CENTERS[f]["fixed_cost_per_day"] * y[f]
            for f in self.fcs
        )
        late = pulp.lpSum(
            LATE_DELIVERY_PENALTY * x[(f, r, s)]
            for (f, r, s) in valid_keys
            if self.meets_2day[(f, r)] == 0
        )
        stockout = pulp.lpSum(
            STOCKOUT_PENALTY_PER_UNIT * u[k] for k in self.dem.keys()
        )

        m += ship_handle + fixed + late + stockout, "Total_Cost"

        # --- Constraint 1: demand satisfaction ----------------------
        # Shipments into a region-SKU plus unmet demand must equal demand.
        # Equality rather than <= is deliberate: with <=, the model could
        # quietly over-ship to burn down inventory, and with >= it could
        # under-serve without recording a shortfall.
        for (r, s) in self.dem.keys():
            m += (
                pulp.lpSum(
                    x[(f, r, s)] for f in self.fcs if (f, r, s) in x
                ) + u[(r, s)] == self.dem[(r, s)],
                f"demand_{r}_{s}",
            )

        # --- Constraint 2: inventory availability -------------------
        # Total outbound of a SKU from an FC cannot exceed what that FC holds.
        for f in self.fcs:
            for s in self.skus:
                avail = self.inv.get((f, s), 0)
                if avail <= 0:
                    continue
                m += (
                    pulp.lpSum(
                        x[(f, r, s)] for r in self.regions if (f, r, s) in x
                    ) <= avail,
                    f"inventory_{f}_{s}",
                )

        # --- Constraint 3: capacity and activation linking ----------
        # This constraint does two jobs at once. It caps daily throughput,
        # and because the right-hand side is multiplied by y[f], it forces
        # y[f] = 1 whenever the FC ships anything at all. If y[f] were 0 the
        # right side collapses to 0, so every x from that FC is driven to 0.
        # That linkage is what makes the fixed cost economically real. Without
        # it the model would activate no buildings and ship freely.
        for f in self.fcs:
            cap = FULFILLMENT_CENTERS[f]["capacity_units_day"]
            m += (
                pulp.lpSum(
                    x[(f, r, s)] for r in self.regions for s in self.skus
                    if (f, r, s) in x
                ) <= cap * y[f],
                f"capacity_{f}",
            )

        # --- Constraint 4: service level (optional) ------------------
        # At least `service_target` of shipped units must travel a lane that
        # delivers within 2 days. The natural way to write this is
        #     sum(fast) / sum(all) >= alpha
        # but that is a ratio, and ratios are nonlinear. Multiplying both
        # sides by the denominator gives
        #     sum(fast) >= alpha * sum(all)
        # which rearranges to a linear inequality the solver accepts:
        #     sum(fast) - alpha * sum(all) >= 0
        # Linearizing ratio constraints this way is a standard and important
        # technique in operations research modeling.
        if self.enforce_service:
            fast = pulp.lpSum(
                x[(f, r, s)] for (f, r, s) in valid_keys
                if self.meets_2day[(f, r)] == 1
            )
            total = pulp.lpSum(x[(f, r, s)] for (f, r, s) in valid_keys)
            m += (fast - self.service_target * total >= 0, "service_level")

        self.model, self.x, self.y, self.u = m, x, y, u
        return self

    # -----------------------------------------------------------------
    # Solve
    # -----------------------------------------------------------------
    def solve(self):
        """
        Solve with CBC, the open-source branch-and-cut solver bundled
        with PuLP.

        gapRel = 0.01 tells the solver to stop once it has a solution
        provably within 1% of the true optimum. Closing that last 1% of the
        gap often costs more time than the first 99%, and a 1% cost
        difference is well inside the noise of the input parameters.
        """
        if self.model is None:
            self.build()

        solver = pulp.PULP_CBC_CMD(
            msg=SOLVER_MSG,
            timeLimit=SOLVER_TIME_LIMIT,
            gapRel=SOLVER_MIP_GAP,
        )
        t0 = time.time()
        self.model.solve(solver)
        self.solve_time = time.time() - t0
        self.status = pulp.LpStatus[self.model.status]
        return self

    # -----------------------------------------------------------------
    # Extract results
    # -----------------------------------------------------------------
    def extract(self) -> dict:
        """
        Pull the solved variable values into tidy DataFrames.

        Returns a dict with the same shape whether or not the solve
        succeeded, so callers can always reach result["metrics"]["feasible"]
        without branching on status first.
        """
        if self.status != "Optimal":
            return {
                "metrics": {"status": self.status, "feasible": False},
                "shipments": pd.DataFrame(),
                "unmet": pd.DataFrame(),
                "open_fcs": [],
            }

        rows = []
        for (f, r, s), var in self.x.items():
            v = var.value()
            # Floating-point solvers return values like 1e-11 instead of
            # exact zero. Filtering on a small epsilon rather than != 0
            # keeps thousands of meaningless near-zero rows out of results.
            if v and v > 1e-6:
                rows.append({
                    "fc_id": f,
                    "region_id": r,
                    "sku_id": s,
                    "units": v,
                    "miles": self.miles[(f, r)],
                    "unit_cost": self.cost[(f, r)],
                    "ship_cost": v * self.cost[(f, r)],
                    "unit_miles": v * self.miles[(f, r)],
                    "meets_2day": self.meets_2day[(f, r)],
                })
        ship_df = pd.DataFrame(rows)

        unmet_rows = [
            {"region_id": r, "sku_id": s, "unmet_units": var.value()}
            for (r, s), var in self.u.items()
            if var.value() and var.value() > 1e-6
        ]
        unmet_df = pd.DataFrame(unmet_rows)

        open_fcs = [
            f for f in self.fcs
            if self.y[f].value() and self.y[f].value() > 0.5
        ]

        total_units = ship_df["units"].sum() if len(ship_df) else 0.0
        fast_units = (
            ship_df.loc[ship_df["meets_2day"] == 1, "units"].sum()
            if len(ship_df) else 0.0
        )

        metrics = {
            "status": self.status,
            "feasible": True,
            "solve_time_sec": round(self.solve_time, 2),
            "objective_value": round(pulp.value(self.model.objective), 2),
            "total_units_shipped": round(total_units, 0),
            "total_unmet_units": (
                round(unmet_df["unmet_units"].sum(), 0) if len(unmet_df) else 0.0
            ),
            "total_ship_cost": (
                round(ship_df["ship_cost"].sum(), 2) if len(ship_df) else 0.0
            ),
            "total_fixed_cost": sum(
                FULFILLMENT_CENTERS[f]["fixed_cost_per_day"] for f in open_fcs
            ),
            "total_miles": (
                round(ship_df["unit_miles"].sum(), 0) if len(ship_df) else 0.0
            ),
            "avg_miles_per_unit": (
                round(ship_df["unit_miles"].sum() / total_units, 1)
                if total_units > 0 else 0.0
            ),
            "cost_per_unit": (
                round(ship_df["ship_cost"].sum() / total_units, 3)
                if total_units > 0 else 0.0
            ),
            "service_level": (
                round(fast_units / total_units, 4) if total_units > 0 else 0.0
            ),
            "fc_count_open": len(open_fcs),
            "fcs_open": ",".join(open_fcs),
        }

        self.solution = {
            "metrics": metrics,
            "shipments": ship_df,
            "unmet": unmet_df,
            "open_fcs": open_fcs,
        }
        return self.solution


# ---------------------------------------------------------------------------
# Baseline heuristic (Scenario 1)
# ---------------------------------------------------------------------------

def nearest_fc_heuristic(lanes, inventory, demand):
    """
    The way most operations actually run, and the benchmark the MIP must beat.

    Rule: ship from the nearest FC that has stock. If it runs out, fall
    through to the next nearest. No cost awareness, no global view, greedy
    region by region.

    The pathology this exposes is worth understanding. Because the loop is
    greedy and processes region-SKU pairs in whatever order the DataFrame
    provides, early rows consume inventory at the good FCs and later rows are
    pushed onto expensive long-haul lanes. The result depends on row order,
    which means two runs on identical data can differ if the sort changes.
    Real warehouse management systems have exactly this pathology, which is
    part of why optimization is worth doing at all.

    Returns the same dict shape as FulfillmentOptimizer.extract().
    """
    inv = {
        (r.fc_id, r.sku_id): float(r.units_available)
        for r in inventory.itertuples()
    }
    cost = {
        (r.fc_id, r.region_id): r.total_cost_per_unit
        for r in lanes.itertuples()
    }
    miles = {
        (r.fc_id, r.region_id): r.road_miles for r in lanes.itertuples()
    }
    meets = {
        (r.fc_id, r.region_id): r.meets_2day for r in lanes.itertuples()
    }

    # Pre-sort FCs by distance for each region so the fallback order is
    # fixed and does not require re-sorting inside the main loop.
    fc_rank = {}
    for region_id, grp in lanes.groupby("region_id"):
        fc_rank[region_id] = grp.sort_values("road_miles")["fc_id"].tolist()

    # Track remaining daily throughput per FC.
    cap_left = {
        f: FULFILLMENT_CENTERS[f]["capacity_units_day"]
        for f in FULFILLMENT_CENTERS
    }

    rows, unmet_rows = [], []
    used_fcs = set()

    for d in demand.itertuples():
        remaining = float(d.units)
        for f in fc_rank[d.region_id]:
            if remaining <= 1e-9:
                break
            available = min(inv.get((f, d.sku_id), 0.0), cap_left[f])
            if available <= 0:
                continue
            take = min(remaining, available)
            inv[(f, d.sku_id)] -= take
            cap_left[f] -= take
            remaining -= take
            used_fcs.add(f)
            rows.append({
                "fc_id": f,
                "region_id": d.region_id,
                "sku_id": d.sku_id,
                "units": take,
                "miles": miles[(f, d.region_id)],
                "unit_cost": cost[(f, d.region_id)],
                "ship_cost": take * cost[(f, d.region_id)],
                "unit_miles": take * miles[(f, d.region_id)],
                "meets_2day": meets[(f, d.region_id)],
            })
        if remaining > 1e-9:
            unmet_rows.append({
                "region_id": d.region_id,
                "sku_id": d.sku_id,
                "unmet_units": remaining,
            })

    ship_df = pd.DataFrame(rows)
    unmet_df = pd.DataFrame(unmet_rows)

    total_units = ship_df["units"].sum() if len(ship_df) else 0.0
    fast_units = (
        ship_df.loc[ship_df["meets_2day"] == 1, "units"].sum()
        if len(ship_df) else 0.0
    )
    fixed_cost = sum(
        FULFILLMENT_CENTERS[f]["fixed_cost_per_day"] for f in used_fcs
    )
    unmet_units = unmet_df["unmet_units"].sum() if len(unmet_df) else 0.0
    late_units = total_units - fast_units

    # The heuristic does not optimize an objective, but the same objective
    # is computed here so the two approaches are compared on identical terms.
    # Scoring a heuristic with a different formula than the model it is
    # benchmarked against would make the comparison meaningless.
    metrics = {
        "status": "Heuristic",
        "feasible": True,
        "solve_time_sec": 0.0,
        "objective_value": (
            round(
                ship_df["ship_cost"].sum() + fixed_cost
                + LATE_DELIVERY_PENALTY * late_units
                + STOCKOUT_PENALTY_PER_UNIT * unmet_units, 2
            ) if len(ship_df) else 0.0
        ),
        "total_units_shipped": round(total_units, 0),
        "total_unmet_units": round(unmet_units, 0),
        "total_ship_cost": (
            round(ship_df["ship_cost"].sum(), 2) if len(ship_df) else 0.0
        ),
        "total_fixed_cost": fixed_cost,
        "total_miles": (
            round(ship_df["unit_miles"].sum(), 0) if len(ship_df) else 0.0
        ),
        "avg_miles_per_unit": (
            round(ship_df["unit_miles"].sum() / total_units, 1)
            if total_units > 0 else 0.0
        ),
        "cost_per_unit": (
            round(ship_df["ship_cost"].sum() / total_units, 3)
            if total_units > 0 else 0.0
        ),
        "service_level": (
            round(fast_units / total_units, 4) if total_units > 0 else 0.0
        ),
        "fc_count_open": len(used_fcs),
        "fcs_open": ",".join(sorted(used_fcs)),
    }

    return {
        "metrics": metrics,
        "shipments": ship_df,
        "unmet": unmet_df,
        "open_fcs": sorted(used_fcs),
    }