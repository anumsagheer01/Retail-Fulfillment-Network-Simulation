"""
eval_matcher.py
Scores the product matcher against the labeled test set.

WHAT IT MEASURES
----------------
A single accuracy number hides too much, so this reports several:

  Top-1 accuracy   : fraction of "matched" cases where the top candidate is the
                     correct SKU. This is the headline number.
  Top-3 recall     : fraction where the correct SKU appears anywhere in the top
                     three. The gap between top-1 and top-3 tells you whether
                     wrong answers are near-misses (rerankable) or true failures.
  Decision accuracy: fraction of ALL cases, including nonsense, where the
                     matcher returns the right STATUS (matched / ambiguous /
                     no_match). This measures the thing that actually matters in
                     production: does it know when to decline or ask.
  Match precision  : of the cases it chose to auto-match, how often was the SKU
                     right. High precision is the point of a B2B matcher, because
                     a confident wrong answer is the expensive failure mode.
  Nonsense declined: of the junk and out-of-catalog cases, how many were
                     correctly refused instead of force-matched.

WHY REPORT SEVERAL
------------------
Optimizing one metric silently sacrifices the others. A matcher that resolves
everything scores high recall and terrible precision; one that declines
everything is the reverse. Reporting the trade lets a reader judge whether the
operating point is sane, which is the honest way to present an evaluation.
"""

import json
import os

from match import resolve_line_item
from eval_dataset import EVAL_CASES
from config import RESULTS_DIR


def evaluate(verbose=True):
    rows = []

    for query, expected_sku, expect_status in EVAL_CASES:
        decision = resolve_line_item(query)
        cands = decision["candidates"]
        top_sku = cands[0]["sku_id"] if cands else None
        top3_skus = [c["sku_id"] for c in cands[:3]]

        top1_correct = (top_sku == expected_sku) if expected_sku else None
        top3_correct = (expected_sku in top3_skus) if expected_sku else None
        status_correct = (decision["status"] == expect_status)

        rows.append({
            "query": query,
            "expected_sku": expected_sku,
            "expect_status": expect_status,
            "got_status": decision["status"],
            "got_sku": decision["sku_id"],
            "top_sku": top_sku,
            "top_score": cands[0]["score"] if cands else 0.0,
            "top1_correct": top1_correct,
            "top3_correct": top3_correct,
            "status_correct": status_correct,
        })

    matched_cases = [r for r in rows if r["expect_status"] == "matched"]
    n_matched = len(matched_cases)

    top1 = sum(1 for r in matched_cases if r["top1_correct"]) / n_matched
    top3 = sum(1 for r in matched_cases if r["top3_correct"]) / n_matched
    decision_acc = sum(1 for r in rows if r["status_correct"]) / len(rows)

    auto_matched = [r for r in rows if r["got_status"] == "matched"]
    if auto_matched:
        precision = sum(
            1 for r in auto_matched if r["got_sku"] == r["expected_sku"]
        ) / len(auto_matched)
    else:
        precision = 0.0

    nonsense = [r for r in rows if r["expect_status"] == "no_match"]
    declined_ok = (
        sum(1 for r in nonsense if r["got_status"] == "no_match") / len(nonsense)
        if nonsense else 0.0
    )

    metrics = {
        "n_cases": len(rows),
        "n_matched_cases": n_matched,
        "top1_accuracy": round(top1, 4),
        "top3_recall": round(top3, 4),
        "decision_accuracy": round(decision_acc, 4),
        "match_precision": round(precision, 4),
        "nonsense_declined": round(declined_ok, 4),
    }

    if verbose:
        print("=" * 60)
        print("MATCHER EVALUATION")
        print("=" * 60)
        print(f"Cases:                {metrics['n_cases']}")
        print(f"Top-1 accuracy:       {metrics['top1_accuracy']:.1%}  "
              f"(correct SKU is the #1 pick)")
        print(f"Top-3 recall:         {metrics['top3_recall']:.1%}  "
              f"(correct SKU in top 3)")
        print(f"Match precision:      {metrics['match_precision']:.1%}  "
              f"(of auto-matched, how many right)")
        print(f"Decision accuracy:    {metrics['decision_accuracy']:.1%}  "
              f"(right matched/ambiguous/no_match call)")
        print(f"Nonsense declined:    {metrics['nonsense_declined']:.1%}  "
              f"(rejected junk instead of guessing)")

        failures = [r for r in rows
                    if (r["expect_status"] == "matched" and not r["top1_correct"])
                    or (not r["status_correct"])]
        if failures:
            print("\nFAILURES (for inspection):")
            for r in failures:
                print(f"  {r['query']!r}")
                print(f"      expected {r['expected_sku']} / {r['expect_status']}, "
                      f"got {r['top_sku']} / {r['got_status']} "
                      f"(score {r['top_score']})")
        else:
            print("\nNo failures.")
        print("=" * 60)

    os.makedirs(RESULTS_DIR, exist_ok=True)
    with open(f"{RESULTS_DIR}/matcher_eval.json", "w") as f:
        json.dump({"metrics": metrics, "cases": rows}, f, indent=2)

    return metrics, rows


if __name__ == "__main__":
    evaluate()