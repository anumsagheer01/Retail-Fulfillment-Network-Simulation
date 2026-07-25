"""
eval_dataset.py
A labeled test set for the product matcher, written to stress it rather than
flatter it.

WHY THESE CASES ARE HARD
------------------------
The most important group is "adjacent but absent": queries for a product in a
category the catalog carries, but a variant the catalog does NOT stock. The
catalog has a 1/2 inch copper elbow; a query for a 3/4 inch copper elbow shares
almost every word and should still be declined, because shipping the wrong size
on a B2B order is a real failure. A lexical matcher is strongly tempted to match
these, so they are the true test of whether attribute discrimination works.

Also included: heavy abbreviations, dropped attributes, brand-only queries,
typos, cross-product collisions, one genuine ambiguity, and nonsense.

STRUCTURE
---------
Each case is (query, expected_sku, expect_status).
  expected_sku : the correct SKU, or None when nothing should confidently match
  expect_status: "matched" | "ambiguous" | "no_match"
"""

EVAL_CASES = [
    # --- clean baseline ---
    ("half inch copper elbow", "SKU_001", "matched"),
    ("12-2 romex 250ft", "SKU_003", "matched"),
    ("2x4x8 spf stud", "SKU_005", "matched"),
    ("5 gallon white interior paint", "SKU_011", "matched"),
    ("r13 fiberglass batt", "SKU_009", "matched"),
    ("36 inch prehung interior door", "SKU_012", "matched"),
    ("3/4 red pex 100ft", "SKU_002", "matched"),
    ("50lb fast set concrete", "SKU_008", "matched"),

    # --- heavy abbreviation / shorthand ---
    ("1/2 cu ell", "SKU_001", "matched"),
    ("2x4 x8 kd", "SKU_005", "matched"),
    ("wht int paint 5g", "SKU_011", "matched"),
    ("r13 unfaced", "SKU_009", "matched"),
    ("5/4 pt decking 12", "SKU_006", "matched"),
    ("20a sp brkr", "SKU_004", "matched"),

    # --- dropped / partial attributes (one product still fits best) ---
    ("copper elbow", "SKU_001", "matched"),
    ("romex", "SKU_003", "matched"),
    ("prehung door", "SKU_012", "matched"),
    ("deck board treated", "SKU_006", "matched"),
    ("concrete mix", "SKU_008", "matched"),

    # --- brand / trade-name queries (not in aliases) ---
    ("quikrete", "SKU_008", "matched"),
    ("sheetrock 4x8", "SKU_007", "matched"),

    # --- reordered + typo combos ---
    ("elbow 1/2 coper", "SKU_001", "matched"),
    ("stud kd 8ft 2x4", "SKU_005", "matched"),
    ("paint intror white 5gal", "SKU_011", "matched"),
    ("insluation r13 fiberglas", "SKU_009", "matched"),

    # --- adjacent but ABSENT: right category, variant not stocked -> decline ---
    ("3/4 copper elbow", None, "no_match"),
    ("copper tee 1/2", None, "no_match"),
    ("14-2 romex", None, "no_match"),
    ("30 amp breaker", None, "no_match"),
    ("2x6x8 stud", None, "no_match"),
    ("5/8 drywall", None, "no_match"),
    ("r19 insulation", None, "no_match"),
    ("exterior door 36", None, "no_match"),

    # --- genuine ambiguity ---
    ("1/2 fitting", None, "ambiguous"),

    # --- nonsense ---
    ("purple widget frobnicator", None, "no_match"),
    ("flux capacitor gigawatt", None, "no_match"),
    ("left handed hammer", None, "no_match"),
    ("bag of nothing", None, "no_match"),
    ("unicorn horn polish", None, "no_match"),
    ("magnetic paint stripper deluxe", None, "no_match"),
]


def stats():
    from collections import Counter
    return dict(Counter(status for _, _, status in EVAL_CASES))


if __name__ == "__main__":
    print(f"{len(EVAL_CASES)} labeled cases")
    for status, n in stats().items():
        print(f"  {status:>10}: {n}")