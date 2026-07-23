"""Part 1 validation checks."""
import pandas as pd

o = pd.read_csv("data/raw/orders.csv", parse_dates=["date"])

assert len(o) == 106_880, f"Expected 106,880 rows, got {len(o):,}"
assert o["units"].sum() == 3_598_553, "Total units mismatch"

daily = o.groupby("date")["units"].sum()
print("Rows:            ", f"{len(o):,}")
print("Peak day:        ", daily.idxmax().date())
print("Peak day units:  ", f"{daily.max():,}")
print("Trough day units:", f"{daily.min():,}")

print("\nCV by ABC class (should rise A -> C):")
print(o.groupby("abc_class")["units"].agg(lambda x: x.std() / x.mean()).round(3))

print("\nDec/Jun ratio:",
      round(o[o.month == 12]["units"].sum() / o[o.month == 6]["units"].sum(), 2))

print("\nAll Part 1 checks passed.")