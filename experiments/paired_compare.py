"""Paired comparison of two evaluated batches (proposal: McNemar + bootstrap).

    python -m experiments.paired_compare /data/runs/lite-pilot-pcr /data/runs/lite-pilot-single

Both directories need `official_eval.json` (experiments.official_eval) over the
SAME task list. A task counts as solved only if its status is `resolved`; every
other status (including no_prediction) counts as not solved. Batches with
harness errors are refused unless --allow-incomplete is given.

Outputs: the paired 2x2 table, the exact two-sided McNemar p-value on the
discordant pairs, and a percentile bootstrap CI for the difference in
resolution rate (A - B), resampling tasks with a fixed seed.
"""
from __future__ import annotations

import argparse
import json
from math import comb
from pathlib import Path
import random


def load_verdicts(batch: Path, *, allow_incomplete: bool = False) -> tuple[dict, dict[str, bool]]:
    path = Path(batch) / "official_eval.json"
    if not path.is_file():
        raise ValueError(f"{path} missing: run experiments.official_eval first")
    data = json.loads(path.read_text(encoding="utf-8"))
    if not data.get("complete") and not allow_incomplete:
        raise ValueError(f"{batch}: evaluation incomplete {data.get('status_counts')}; "
                         "rerun harness errors or pass --allow-incomplete")
    return data, {iid: status == "resolved" for iid, status in data["tasks"].items()}


def mcnemar_exact(b: int, c: int) -> float:
    """Two-sided exact McNemar p-value: binomial test of b vs. c at p = 0.5."""
    n = b + c
    if n == 0:
        return 1.0
    tail = sum(comb(n, k) for k in range(min(b, c) + 1)) / 2 ** n
    return min(1.0, 2 * tail)


def bootstrap_diff_ci(a: list[bool], b: list[bool], *, iterations: int = 10000,
                      seed: int = 7608, level: float = 0.95) -> tuple[float, float]:
    if len(a) != len(b) or not a:
        raise ValueError("Paired lists must be non-empty and the same length")
    rng = random.Random(seed)
    n = len(a)
    diffs = []
    for _ in range(iterations):
        idx = [rng.randrange(n) for _ in range(n)]
        diffs.append(sum(a[i] - b[i] for i in idx) / n)
    diffs.sort()
    lo = diffs[int((1 - level) / 2 * iterations)]
    hi = diffs[min(iterations - 1, int((1 + level) / 2 * iterations))]
    return round(lo, 4), round(hi, 4)


def compare(a: dict[str, bool], b: dict[str, bool], **bootstrap) -> dict:
    if set(a) != set(b):
        raise ValueError("The two batches were run on different task lists; pairing is invalid")
    ids = sorted(a)
    both = sum(1 for i in ids if a[i] and b[i])
    only_a = sum(1 for i in ids if a[i] and not b[i])
    only_b = sum(1 for i in ids if b[i] and not a[i])
    neither = len(ids) - both - only_a - only_b
    xa, xb = [a[i] for i in ids], [b[i] for i in ids]
    n = len(ids)
    return {
        "tasks": n,
        "resolved_a": both + only_a,
        "resolved_b": both + only_b,
        "rate_a": round((both + only_a) / n, 4),
        "rate_b": round((both + only_b) / n, 4),
        "diff_a_minus_b": round((only_a - only_b) / n, 4),
        "table": {"both": both, "only_a": only_a, "only_b": only_b, "neither": neither},
        "mcnemar_exact_p": round(mcnemar_exact(only_a, only_b), 6),
        "bootstrap_95ci_diff": bootstrap_diff_ci(xa, xb, **bootstrap),
        "per_task": {i: {"a": a[i], "b": b[i]} for i in ids},
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("batch_a")
    parser.add_argument("batch_b")
    parser.add_argument("--iterations", type=int, default=10000)
    parser.add_argument("--seed", type=int, default=7608)
    parser.add_argument("--allow-incomplete", action="store_true")
    parser.add_argument("--out", help="write the full result JSON here")
    args = parser.parse_args(argv)

    meta_a, a = load_verdicts(Path(args.batch_a), allow_incomplete=args.allow_incomplete)
    meta_b, b = load_verdicts(Path(args.batch_b), allow_incomplete=args.allow_incomplete)
    result = compare(a, b, iterations=args.iterations, seed=args.seed)
    result["a"] = {k: meta_a.get(k) for k in ("agent", "edit_format", "model", "run_id")} | {"dir": args.batch_a}
    result["b"] = {k: meta_b.get(k) for k in ("agent", "edit_format", "model", "run_id")} | {"dir": args.batch_b}
    for iid, pair in result["per_task"].items():
        print(f"{iid:45s} A={'Y' if pair['a'] else '.'}  B={'Y' if pair['b'] else '.'}")
    print(json.dumps({k: v for k, v in result.items() if k != "per_task"}, indent=2, ensure_ascii=False))
    if result["tasks"] < 50:
        print("NOTE: few paired tasks; treat p-values and CIs as indicative only.")
    if args.out:
        Path(args.out).write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
