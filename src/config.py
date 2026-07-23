"""
config.py
Central configuration for the fulfillment network optimization project.

Everything a business analyst would want to change lives here so the model
code stays clean. Change a number here, rerun, get a new scenario.
"""

# ---------------------------------------------------------------------------
# Reproducibility
# ---------------------------------------------------------------------------
RANDOM_SEED = 42

# ---------------------------------------------------------------------------
# Simulation horizon
# ---------------------------------------------------------------------------
SIM_START_DATE = "2024-01-01"
SIM_DAYS = 365          # one full year of history
N_SKUS = 12             # product catalog size
N_DEMAND_REGIONS = 25   # customer demand zones (metro clusters)

# ---------------------------------------------------------------------------
# Fulfillment centers (six hypothetical FCs)
# lat/lon are real US metro coordinates so distances are realistic.
# fixed_cost_per_day  : cost to keep the building running (USD/day)
# capacity_units_day  : max units the FC can pick/pack/ship in a day
# storage_capacity    : max units of inventory the building can hold
# handling_cost_unit  : variable cost to touch one unit (USD)
# ---------------------------------------------------------------------------
FULFILLMENT_CENTERS = {
    "FC_ATL": {
        "name": "Atlanta, GA",
        "lat": 33.7490, "lon": -84.3880,
        "fixed_cost_per_day": 12000,
        "capacity_units_day": 9000,
        "storage_capacity": 120000,
        "handling_cost_unit": 1.10,
    },
    "FC_DFW": {
        "name": "Dallas, TX",
        "lat": 32.7767, "lon": -96.7970,
        "fixed_cost_per_day": 11500,
        "capacity_units_day": 8500,
        "storage_capacity": 110000,
        "handling_cost_unit": 1.05,
    },
    "FC_ONT": {
        "name": "Ontario, CA",
        "lat": 34.0633, "lon": -117.6509,
        "fixed_cost_per_day": 15000,
        "capacity_units_day": 11000,
        "storage_capacity": 150000,
        "handling_cost_unit": 1.35,
    },
    "FC_ORD": {
        "name": "Joliet, IL",
        "lat": 41.5250, "lon": -88.0817,
        "fixed_cost_per_day": 13000,
        "capacity_units_day": 10000,
        "storage_capacity": 135000,
        "handling_cost_unit": 1.15,
    },
    "FC_EWR": {
        "name": "Edison, NJ",
        "lat": 40.5187, "lon": -74.4121,
        "fixed_cost_per_day": 16000,
        "capacity_units_day": 9500,
        "storage_capacity": 125000,
        "handling_cost_unit": 1.45,
    },
    "FC_PHX": {
        "name": "Phoenix, AZ",
        "lat": 33.4484, "lon": -112.0740,
        "fixed_cost_per_day": 10500,
        "capacity_units_day": 7500,
        "storage_capacity": 95000,
        "handling_cost_unit": 1.00,
    },
}

# ---------------------------------------------------------------------------
# Demand regions: 25 US metros with a population weight that drives
# baseline demand share. Weight is roughly proportional to metro population.
# ---------------------------------------------------------------------------
DEMAND_REGIONS = {
    "NYC":    {"lat": 40.7128, "lon":  -74.0060, "weight": 18.9},
    "LAX":    {"lat": 34.0522, "lon": -118.2437, "weight": 13.2},
    "CHI":    {"lat": 41.8781, "lon":  -87.6298, "weight":  9.5},
    "DFW":    {"lat": 32.7767, "lon":  -96.7970, "weight":  7.6},
    "HOU":    {"lat": 29.7604, "lon":  -95.3698, "weight":  7.1},
    "DCA":    {"lat": 38.9072, "lon":  -77.0369, "weight":  6.3},
    "MIA":    {"lat": 25.7617, "lon":  -80.1918, "weight":  6.1},
    "PHL":    {"lat": 39.9526, "lon":  -75.1652, "weight":  6.1},
    "ATL":    {"lat": 33.7490, "lon":  -84.3880, "weight":  6.1},
    "BOS":    {"lat": 42.3601, "lon":  -71.0589, "weight":  4.9},
    "PHX":    {"lat": 33.4484, "lon": -112.0740, "weight":  4.9},
    "SFO":    {"lat": 37.7749, "lon": -122.4194, "weight":  4.7},
    "RIV":    {"lat": 33.9533, "lon": -117.3962, "weight":  4.6},
    "DET":    {"lat": 42.3314, "lon":  -83.0458, "weight":  4.4},
    "SEA":    {"lat": 47.6062, "lon": -122.3321, "weight":  4.0},
    "MSP":    {"lat": 44.9778, "lon":  -93.2650, "weight":  3.7},
    "SAN":    {"lat": 32.7157, "lon": -117.1611, "weight":  3.3},
    "TPA":    {"lat": 27.9506, "lon":  -82.4572, "weight":  3.2},
    "DEN":    {"lat": 39.7392, "lon": -104.9903, "weight":  3.0},
    "STL":    {"lat": 38.6270, "lon":  -90.1994, "weight":  2.8},
    "BWI":    {"lat": 39.2904, "lon":  -76.6122, "weight":  2.8},
    "CLT":    {"lat": 35.2271, "lon":  -80.8431, "weight":  2.7},
    "ORL":    {"lat": 28.5383, "lon":  -81.3792, "weight":  2.6},
    "SAT":    {"lat": 29.4241, "lon":  -98.4936, "weight":  2.6},
    "PDX":    {"lat": 45.5152, "lon": -122.6784, "weight":  2.5},
}

# ---------------------------------------------------------------------------
# Shipping / transportation economics
# Zone-based rate card, the way parcel carriers actually price.
# Zone is derived from distance. Cost = base + per_mile * miles, per unit.
# ---------------------------------------------------------------------------
SHIPPING_ZONES = [
    # (max_miles, zone_name, base_cost_per_unit, cost_per_mile_per_unit, transit_days)
    (150,   "Zone 2", 4.20, 0.0035, 1),
    (300,   "Zone 3", 4.85, 0.0038, 1),
    (600,   "Zone 4", 5.60, 0.0041, 2),
    (1000,  "Zone 5", 6.45, 0.0044, 2),
    (1400,  "Zone 6", 7.30, 0.0047, 3),
    (1800,  "Zone 7", 8.15, 0.0050, 3),
    (99999, "Zone 8", 9.40, 0.0054, 4),
]

# Orders must arrive within this many days to count as "on time"
DELIVERY_TARGET_DAYS = 2

# Service level we contractually promise. The model may miss the 2-day
# target on some orders, but at least this fraction must hit it.
SERVICE_LEVEL_TARGET = 0.93

# Penalty (USD/unit) applied in the objective when an order misses 2-day.
# A "soft" cost representing customer dissatisfaction / credits.
LATE_DELIVERY_PENALTY = 3.50

# ---------------------------------------------------------------------------
# Inventory
# ---------------------------------------------------------------------------
HOLDING_COST_PER_UNIT_DAY = 0.045     # capital + space + shrink
STOCKOUT_PENALTY_PER_UNIT = 22.00     # lost margin + customer damage
SAFETY_STOCK_Z = 1.65                 # ~95% cycle service level

# ---------------------------------------------------------------------------
# Optimization scenarios: the four strategies we compare
# ---------------------------------------------------------------------------
SCENARIOS = {
    "S1_nearest_fc": {
        "label": "Baseline: Nearest FC",
        "description": (
            "Heuristic. Every order ships from the geographically closest FC "
            "that has stock. No optimization, no cost awareness. This is how "
            "most small operations actually run."
        ),
        "method": "heuristic",
        "allocation": "proportional_to_demand",
    },
    "S2_cost_min": {
        "label": "Cost-Minimizing MIP",
        "description": (
            "Mixed-integer program. Minimize total landed cost (shipping + "
            "handling + fixed) subject to capacity and inventory. Delivery "
            "speed enters only as a soft penalty, not a hard constraint."
        ),
        "method": "mip",
        "allocation": "optimized",
        "enforce_service_constraint": False,
    },
    "S3_service_constrained": {
        "label": "Service-Constrained MIP",
        "description": (
            "Same MIP but adds a hard constraint that at least 93% of units "
            "must ship from an FC within 2-day range. Costs more, protects "
            "the customer promise."
        ),
        "method": "mip",
        "allocation": "optimized",
        "enforce_service_constraint": True,
    },
    "S4_pooled_forward": {
        "label": "Pooled Inventory + Forward Positioning",
        "description": (
            "Service-constrained MIP, but inventory allocation is re-optimized "
            "so stock is pushed toward high-demand regions ahead of time. "
            "Tests whether smarter placement beats smarter routing."
        ),
        "method": "mip",
        "allocation": "forward_positioned",
        "enforce_service_constraint": True,
    },
}

# ---------------------------------------------------------------------------
# Solver settings
# ---------------------------------------------------------------------------
SOLVER_TIME_LIMIT = 120      # seconds per solve
SOLVER_MIP_GAP = 0.01        # accept a solution within 1% of proven optimal
SOLVER_MSG = 0               # 0 = quiet, 1 = verbose

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
RAW_DATA_DIR = "data/raw"
PROCESSED_DATA_DIR = "data/processed"
RESULTS_DIR = "outputs/results"
FIGURES_DIR = "outputs/figures"