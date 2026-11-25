"""Check the binary shortcut on all admissible supports and on held-out CI evidence."""

from fractions import Fraction as F
import gzip
from itertools import combinations
import json
from pathlib import Path
import sys

from joint_odds import check_rows, semantics
from retuned_odds import binary_pair_policy
from retuned_odds_boundary_check import direct, marginal


def exhaustive():
    options = ((1, 0), (0, 1), (1, 1))
    tested = 0
    for size in range(1, 4):
        for group in combinations(options, size):
            if not all(any(mode[side] for mode in group) for side in (0, 1)):
                continue
            modes = [(0, 0), *group]
            worlds = [(marginal(x, 1), marginal(y, 1)) for x, y in modes]
            half, _, _ = semantics(worlds)
            for gamma in [F(1, 5), F(1, 2), F(2, 3), F(3, 4), F(1)]:
                floor = {cell: 2 * gamma * base for cell, base in half.items()}
                optimum, rows = binary_pair_policy(modes, gamma)
                check_rows(worlds, floor, optimum, rows)
                args = (worlds, [F(2)] * 2, [F(1, 2)] * 2, floor)
                assert direct(*args, optimum) == 0
                assert direct(*args, optimum - F(1, 100)) is None
                tested += 2
    return tested


def ci(path):
    rows = json.loads(gzip.decompress(path.read_bytes()))
    shortcuts = tests = covered = 0
    for row in rows:
        if row["status"] != "scored":
            continue
        if [len(a["labels"]) for a in row["views"]] != [1, 1]:
            covered += sum(
                p["refusal_budget"] is not None for p in row["targets"].values()
            )
            continue
        modes = list(map(tuple, row["modes"]))
        optimum, witness = binary_pair_policy(modes)
        worlds = [(marginal(x, 1), marginal(y, 1)) for x, y in modes]
        floors, _, _ = semantics(worlds)
        check_rows(worlds, floors, optimum, witness)
        shortcuts += 1
        for ratio, result in row["targets"].items():
            assert (F(ratio) >= optimum) == (result["status"] == "feasible")
            if result["status"] == "feasible":
                assert F(result["drift"]) == 0
            tests += 1
    return dict(
        binary_archives=shortcuts,
        binary_targets=tests,
        additionally_screened=covered,
        covered_without_lp=tests + covered,
    )


if __name__ == "__main__":
    if not __debug__:
        raise RuntimeError("enable assertions")
    print(json.dumps(dict(direct_targets=exhaustive(), **ci(Path(sys.argv[1])))))
