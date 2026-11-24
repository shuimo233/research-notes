"""Independently verify public pattern coverage, exact rates, and optimal dual certificates."""

import argparse
from fractions import Fraction
import gzip
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from public_optimality_check import model
from selection_odds_run import read
from slack_certificate_check import potential


def independent_patterns(n, edges, entries):
    valid = []
    for mask in range(1 << len(entries)):
        binary = []
        for j, item in enumerate(entries):
            u, v, c = item["comparison"]
            binary.append((v, u, -c) if mask & 1 << j else (u, v, c - 1))
        if potential(n, [*edges, *binary]) is not None:
            valid.append(mask)
    return valid


def score(weight, masks, floor=None):
    conditional = [[] for _ in weight]
    for j in masks:
        truth = [i for i in range(len(weight)) if (j >> i) & 1]
        normalizer = sum(weight[i] for i in truth)
        for i in truth:
            p = weight[i] / normalizer
            assert floor is None or p >= floor
            conditional[i].append(p)
    return max(max(p) / min(p) for p in conditional)


def check_dual(d, k, masks):
    weights = list(map(Fraction, d["weights"]))
    optimum = Fraction(d["lambda"])
    alpha = Fraction(d["floor"])
    lows = {m: Fraction(v) for m, v in d["lower_dual"]}
    highs = {m: Fraction(v) for m, v in d["upper_dual"]}
    assert len(weights) == k and alpha == Fraction(1, 2 * k)
    assert all(w >= alpha for w in weights)
    sums = [sum(w for i, w in enumerate(weights) if m & (1 << i)) for m in masks]
    assert min(sums) == optimum and max(sums) <= 1
    assert set(lows) | set(highs) <= set(masks)
    assert all(w > 0 for w in [*lows.values(), *highs.values()])
    assert sum(lows.values()) == 1
    lhs = []
    for i in range(k):
        b = 1 << i
        negative = sum(w for m, w in lows.items() if m & b)
        positive = sum(w for m, w in highs.items() if m & b)
        lhs.append(positive - negative)
    assert min(lhs) >= 0
    # The unshifted dual objective is capacity minus the explicit probability floors.
    assert sum(highs.values()) - alpha * sum(lhs) == optimum
    assert score(weights, masks, alpha) == Fraction(d["weighted_ratio"]) == 1 / optimum
    assert score([Fraction(1)] * k, masks, alpha) == Fraction(d["uniform_ratio"])


def check(source, output):
    entries = read(source)
    policies = json.loads(
        gzip.decompress((output / "selection-odds-policies.json.gz").read_bytes())
    )
    summary = json.loads((output / "selection-odds-results.json").read_bytes())
    by_scheme = []
    active_rows = dual_rows = enumerated = 0
    max_patterns = 0
    for default, returned in zip(entries, policies, strict=True):
        assert default == returned["catalogue"]
        n, _, _, _, edges, _, _ = model(default["packet"])
        k = len(default["entries"])
        valid = independent_patterns(n, edges, default["entries"])
        d = returned["odds"]
        assert d["no_release_possible"] == (0 in valid)
        masks = [m for m in valid if m]
        assert masks == d["patterns"]
        minimum = [m for m in masks if all(q == m or (q & m) != q for q in masks)]
        maximum = [m for m in masks if all(q == m or (q & m) != m for q in masks)]
        assert d["minimal"] == minimum and d["maximal"] == maximum
        check_dual(d, k, masks)
        assert len(d["lower_dual"]) + len(d["upper_dual"]) == len(
            set(
                (tag, x[0])
                for tag, rs in enumerate((d["lower_dual"], d["upper_dual"]))
                for x in rs
            )
        )
        by_scheme.append((Fraction(d["uniform_ratio"]), Fraction(d["weighted_ratio"])))
        active_rows += len(minimum) + len(maximum)
        dual_rows += len(d["lower_dual"]) + len(d["upper_dual"])
        enumerated += len(masks)
        max_patterns = max(max_patterns, len(masks))
    old, new = zip(*by_scheme, strict=True)
    assert all(a >= b for a, b in by_scheme)
    improve = sum(a > b for a, b in by_scheme)
    expected = dict(
        catalogues=len(policies),
        labels=sum(len(p["catalogue"]["entries"]) for p in policies),
        checked_cells=sum(p["odds"]["checked_cells"] for p in policies),
        feasible_nonempty_patterns=enumerated,
        max_patterns=max_patterns,
        active_extremal_rows=active_rows,
        dual_rows=dual_rows,
        strictly_improved=improve,
        neutral_uniform=old.count(1),
        neutral_optimum=new.count(1),
        worst_uniform=str(max(old)),
        worst_optimum=str(max(new)),
        mean_uniform=str(sum(old) / len(old)),
        mean_optimum=str(sum(new) / len(new)),
        gate=len(policies) == 25 and improve >= 5,
    )
    assert expected == summary
    return dict(
        catalogues=len(policies),
        patterns=enumerated,
        certifying_dual_rows=dual_rows,
        strictly_improved=improve,
        gate=summary["gate"],
    )


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("catalogue", type=Path)
    p.add_argument("replayed", type=Path)
    a = p.parse_args()
    if not __debug__:
        raise RuntimeError("enable assertions")
    print(json.dumps(check(a.catalogue, a.replayed), indent=2))
