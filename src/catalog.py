"""
catalog.py
A home-improvement product catalog with the attributes and Pro-speak aliases
needed to resolve vague contractor queries into concrete SKUs.

WHY THIS EXISTS
---------------
A professional customer does not type "SKU_001". They type "half inch copper
elbow" or "12-2 romex 250ft". The sourcing agent has to turn that language into
a specific catalog item before the optimizer can do anything. This module holds
the catalog and the attribute vocabulary the matcher scores against.

The 12 abstract SKUs from generate_demand.py (SKU_001 .. SKU_012) are mapped
onto 12 real product families here, so the demand, inventory, and lane data
already built all continue to work unchanged. The optimizer never sees product
names; it still works on SKU ids. This module is the translation layer.
"""

CATALOG = {
    "SKU_001": {
        "name": "1/2 in. Copper Type L Elbow, 90 deg",
        "category": "plumbing_fittings",
        "attributes": {"material": "copper", "size_in": 0.5,
                       "fitting": "elbow", "angle_deg": 90, "type": "L"},
        "aliases": ["half inch copper elbow", "1/2 copper 90", "copper elbow",
                    "1/2in copper elbow 90", "half in cu elbow"],
        "unit": "each",
    },
    "SKU_002": {
        "name": "3/4 in. PEX-A Pipe, Red, 100 ft coil",
        "category": "plumbing_pipe",
        "attributes": {"material": "pex", "size_in": 0.75, "color": "red",
                       "length_ft": 100, "grade": "A"},
        "aliases": ["3/4 pex red", "pex a 3/4 hot", "red pex 100ft",
                    "three quarter pex", "3/4in pex coil"],
        "unit": "coil",
    },
    "SKU_003": {
        "name": "12-2 NM-B Romex Wire, 250 ft",
        "category": "electrical_wire",
        "attributes": {"gauge": 12, "conductors": 2, "type": "nm-b",
                       "length_ft": 250, "amp": 20},
        "aliases": ["12-2 romex", "12/2 wire 250", "romex 12 gauge",
                    "12-2 nmb 250ft", "12 2 wire"],
        "unit": "roll",
    },
    "SKU_004": {
        "name": "20 Amp Single-Pole Circuit Breaker",
        "category": "electrical_distribution",
        "attributes": {"amp": 20, "poles": 1, "type": "breaker"},
        "aliases": ["20 amp breaker", "single pole 20a", "20a breaker",
                    "20 amp single pole", "1 pole 20 amp breaker"],
        "unit": "each",
    },
    "SKU_005": {
        "name": "2x4x8 ft Kiln-Dried SPF Stud",
        "category": "lumber_framing",
        "attributes": {"nominal": "2x4", "length_ft": 8, "species": "spf",
                       "treatment": "kiln-dried"},
        "aliases": ["2x4 8ft", "2 by 4 stud", "8 foot 2x4", "spf stud",
                    "2x4x8", "kd stud"],
        "unit": "each",
    },
    "SKU_006": {
        "name": "5/4x6x12 ft Pressure-Treated Deck Board",
        "category": "lumber_decking",
        "attributes": {"nominal": "5/4x6", "length_ft": 12,
                       "treatment": "pressure-treated"},
        "aliases": ["5/4 deck board", "deck board 12ft", "pt decking",
                    "5/4x6 treated", "five quarter deck board"],
        "unit": "each",
    },
    "SKU_007": {
        "name": "1/2 in. Drywall Sheet, 4x8 ft",
        "category": "drywall",
        "attributes": {"thickness_in": 0.5, "size": "4x8", "type": "standard"},
        "aliases": ["1/2 drywall", "half inch sheetrock", "4x8 drywall",
                    "1/2in gyp board", "drywall sheet"],
        "unit": "sheet",
    },
    "SKU_008": {
        "name": "50 lb. Fast-Setting Concrete Mix",
        "category": "concrete",
        "attributes": {"weight_lb": 50, "set": "fast", "type": "concrete-mix"},
        "aliases": ["fast set concrete", "quikrete 50lb", "concrete mix bag",
                    "fast setting concrete 50", "50lb concrete"],
        "unit": "bag",
    },
    "SKU_009": {
        "name": "R-13 Fiberglass Insulation Batt, 15 in x 93 in",
        "category": "insulation",
        "attributes": {"r_value": 13, "width_in": 15, "type": "fiberglass-batt"},
        "aliases": ["r13 insulation", "r-13 batt", "fiberglass batt 15",
                    "wall insulation r13", "r13 fiberglass"],
        "unit": "bag",
    },
    "SKU_010": {
        "name": "3 in. Exterior Wood Screws, 5 lb box",
        "category": "fasteners",
        "attributes": {"length_in": 3, "type": "wood-screw", "use": "exterior",
                       "weight_lb": 5},
        "aliases": ["3in deck screws", "exterior wood screws", "3 inch screws",
                    "deck screws 5lb", "exterior screws"],
        "unit": "box",
    },
    "SKU_011": {
        "name": "White Interior Latex Paint, 5 gal",
        "category": "paint",
        "attributes": {"color": "white", "finish": "eggshell",
                       "base": "latex", "volume_gal": 5, "use": "interior"},
        "aliases": ["5 gallon white paint", "interior latex white",
                    "white paint 5gal", "eggshell white", "interior wall paint"],
        "unit": "pail",
    },
    "SKU_012": {
        "name": "36 in. 3-Panel Prehung Interior Door",
        "category": "doors",
        "attributes": {"width_in": 36, "panels": 3, "type": "prehung",
                       "use": "interior"},
        "aliases": ["36 inch interior door", "3 panel prehung", "36in door",
                    "prehung interior door", "3 foot door"],
        "unit": "each",
    },
}

# Category synonyms. A query may name a category loosely ("wire", "lumber")
# rather than a product. These help the matcher narrow before scoring.
CATEGORY_SYNONYMS = {
    "plumbing_fittings": ["fitting", "elbow", "coupling", "tee", "plumbing"],
    "plumbing_pipe": ["pipe", "pex", "tubing", "line", "plumbing"],
    "electrical_wire": ["wire", "romex", "cable", "conductor", "electrical"],
    "electrical_distribution": ["breaker", "panel", "electrical"],
    "lumber_framing": ["stud", "lumber", "framing", "2x4", "board"],
    "lumber_decking": ["deck", "decking", "lumber", "board"],
    "drywall": ["drywall", "sheetrock", "gypsum", "gyp", "board"],
    "concrete": ["concrete", "cement", "quikrete", "mix"],
    "insulation": ["insulation", "batt", "fiberglass", "r-value"],
    "fasteners": ["screw", "nail", "fastener", "bolt"],
    "paint": ["paint", "latex", "primer", "coating"],
    "doors": ["door", "prehung", "entry"],
}

# Units of measure a Pro might use, normalized to a canonical token.
UOM_NORMALIZE = {
    "ea": "each", "each": "each", "pc": "each", "pcs": "each", "piece": "each",
    "box": "box", "bx": "box", "boxes": "box",
    "bag": "bag", "bags": "bag",
    "roll": "roll", "rolls": "roll",
    "coil": "coil", "coils": "coil",
    "sheet": "sheet", "sheets": "sheet", "sht": "sheet",
    "gal": "pail", "gallon": "pail", "pail": "pail", "bucket": "pail",
}


def all_skus():
    """Return the list of SKU ids in the catalog."""
    return list(CATALOG.keys())


def get_product(sku_id):
    """Look up a product family by SKU id."""
    return CATALOG.get(sku_id)


def build_alias_index():
    """
    Flatten the catalog into (alias_text, sku_id, source) rows for the matcher.
    Includes the product name and every alias, so both the formal name and
    Pro-speak forms are searchable.
    """
    rows = []
    for sku_id, p in CATALOG.items():
        rows.append((p["name"].lower(), sku_id, "name"))
        for a in p["aliases"]:
            rows.append((a.lower(), sku_id, "alias"))
    return rows


if __name__ == "__main__":
    print(f"Catalog holds {len(CATALOG)} product families\n")
    for sku_id, p in CATALOG.items():
        print(f"{sku_id}  {p['name']}")
        print(f"        category: {p['category']}  unit: {p['unit']}")
        print(f"        aliases:  {', '.join(p['aliases'][:3])} ...")
    idx = build_alias_index()
    print(f"\nAlias index has {len(idx)} searchable surface forms")