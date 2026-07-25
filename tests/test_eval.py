"""Part 8 checks: the matcher evaluation harness."""
import sys
sys.path.insert(0, "src")

from eval_matcher import evaluate
from eval_dataset import EVAL_CASES, stats

# The eval set must contain genuinely hard cases, not just easy ones.
comp = stats()
assert comp.get("no_match", 0) >= 10, "eval set needs many decline cases"
assert comp.get("ambiguous", 0) >= 1, "eval set needs an ambiguous case"
assert len(EVAL_CASES) >= 35, "eval set too small to be meaningful"
print(f"Eval set: {len(EVAL_CASES)} cases, composition {comp}")

metrics, rows = evaluate(verbose=False)

# Assert honest quality FLOORS, not perfection. These reflect the matcher's
# real measured performance with margin, so a genuine regression trips them but
# normal variation does not.
assert metrics["top1_accuracy"] >= 0.90, \
    f"top-1 accuracy dropped to {metrics['top1_accuracy']:.1%}"
assert metrics["top3_recall"] >= 0.95, \
    f"top-3 recall dropped to {metrics['top3_recall']:.1%}"
assert metrics["match_precision"] >= 0.75, \
    f"match precision dropped to {metrics['match_precision']:.1%}"
assert metrics["nonsense_declined"] >= 0.50, \
    f"nonsense rejection dropped to {metrics['nonsense_declined']:.1%}"

print(f"top-1 {metrics['top1_accuracy']:.0%}, "
      f"top-3 {metrics['top3_recall']:.0%}, "
      f"precision {metrics['match_precision']:.0%}, "
      f"nonsense declined {metrics['nonsense_declined']:.0%}")
print("\nAll Part 8 checks passed.")