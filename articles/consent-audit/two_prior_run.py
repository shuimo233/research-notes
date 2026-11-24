"""Replay exact two-prior regret certificates and query their selected policies."""

import argparse
from collections import Counter, defaultdict
from fractions import Fraction as Q
import gzip
import json
from pathlib import Path
from random import Random
import sys

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
from mandatory_reuse_run import pair_data
from two_prior import controller_for, draw


def run(snapshot, wordnet, semcor, destination):
    rng = Random(20261124)
    rows = []
    report = defaultdict(Counter)
    with gzip.open(ROOT / "prior-reuse-ledger.jsonl.gz", "rt", encoding="utf-8") as f:
        independent = {tuple(x["task"]): x for x in map(json.loads, f)}
    for key, p, q, truth, weights in pair_data(snapshot, wordnet, semcor):
        frozen = independent.pop(key)
        solver = controller_for(p, q, weights)
        result = solver.solve()
        asserts = [
            solver.budgets[0] == Q(frozen["old_expected"]),
            solver.budgets[1] == Q(frozen["new_expected"]),
        ]
        assert all(asserts)
        selected = draw(result["policies"], rng)
        path, answers = solver.execute(selected, truth.__getitem__)
        if selected in (0, 1):
            assert path == frozen["paths"]["new" if selected else "old"]
        assert [[list(e), v] for e, v in answers.items()] == frozen["labels"]
        positive = result["worst_regret"] > 0
        beats = result["worst_regret"] < result["reference_regret"]
        for key_group in (key[0], "total"):
            c = report[key_group]
            c["tasks"] += 1
            c["positive_robust_regret"] += positive
            c["strictly_better_than_endpoint_lottery"] += beats
            c["uses_nonendpoint_policy"] += any(
                0 < x["prior"] < 1 for x in result["policies"]
            )
            c["randomized_policy"] += len(result["policies"]) == 2
            c["expected_regret_sum"] += float(result["worst_regret"])
            c["endpoint_regret_sum"] += float(result["reference_regret"])
            c["real_reads"] += len(path)
            c["nominal_old_reads"] += frozen["old_reads"]
            c["nominal_new_reads"] += frozen["new_reads"]
        rows.append(
            dict(
                task=key,
                selected=selected,
                trace=path,
                labels=frozen["labels"],
                **result,
            )
        )
        solver.clear()
    assert not independent
    for value in report.values():
        for k in ("expected_regret_sum", "endpoint_regret_sum"):
            value[k] = round(value[k], 9)
    stats = dict(by_source=report, gate=report["total"]["positive_robust_regret"] > 0)
    destination.mkdir(parents=True, exist_ok=False)
    ledger = "".join(
        json.dumps(row, default=str, separators=(",", ":")) + "\n" for row in rows
    ).encode()
    (destination / "two-prior-ledger.jsonl.gz").write_bytes(
        gzip.compress(ledger, mtime=0)
    )
    (destination / "two-prior-results.json").write_bytes(
        (json.dumps(stats, indent=2) + "\n").encode()
    )
    return stats


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    for key in ("snapshot", "wordnet", "semcor", "output"):
        p.add_argument(key, type=Path)
    a = p.parse_args()
    if not __debug__:
        raise RuntimeError("enable assertions")
    print(json.dumps(run(a.snapshot, a.wordnet, a.semcor, a.output), indent=2))
