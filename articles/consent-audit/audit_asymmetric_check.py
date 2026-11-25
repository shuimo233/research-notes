"""Independently check asymmetric refusal odds certificates over finite boxes."""

from collections import Counter
from fractions import Fraction as F
import gzip
from hashlib import sha1
from itertools import combinations, product
import json
from math import comb, prod
from pathlib import Path

FLOOR = F(1, 2)
CAPS = (F(51, 50),)
TOLERANCE = F(51, 50)
SPLITS = 16
PIN = "7ff77c48087929f54a1c9cda41bd984b14ec5edf"
EXAMPLE = (
    (F(1, 10), F(3, 5), F(2, 5)),
    (F(9, 10), F(3, 5), F(2, 5)),
    (F(3, 5), F(9, 10), F(2, 5)),
    F(1, 5),
    (F(5, 4),),
)
PEAK = (F(18, 23), F(3, 5), F(2, 5))
PEAK_ODDS = F(880, 207)
LEVELS = (2, 3, 4, 8)


def dot(a, b):
    return sum(x * y for x, y in zip(a, b, strict=True))


def proof_value(first, second, floor, caps, proof):
    pairs = list(zip(first, second, strict=True))
    order = sorted(set(pairs))
    sizes = [pairs.count(p) for p in order]
    index = [order.index(p) for p in pairs]
    states = list(product(*(range(n + 1) for n in sizes)))
    n = len(states)
    assert type(proof["cells"]) is int and proof["cells"] == n
    examples = {}
    for d in range(2, len(caps) + 2):
        for sample in combinations(range(len(pairs)), d):
            seen = Counter(index[i] for i in sample)
            types = tuple(seen[j] for j in range(len(sizes)))
            examples.setdefault(types, sample)
    patterns = []
    for counts, example in sorted(examples.items()):
        c = caps[len(example) - 2]
        patterns.append((counts, example, c, 0))
        if c > 1:
            patterns.append((counts, example, c, 1))
    g = floor / (1 - floor)
    d = 2 * n + sum(c > 1 for _, _, c, _ in patterns)
    primal = [F(0)] * d
    for i, value in proof["support"]:
        assert type(i) is int and 0 <= i < d and not primal[i]
        primal[i] = F(value)
        assert primal[i] > 0
    dual = list(map(F, proof["dual"]))
    s = 2 + 2 * len(order)
    assert len(dual) == s + len(patterns)
    assert all(
        y >= 0 for y, (_, _, c, _) in zip(dual[s:], patterns, strict=True) if c > 1
    )
    lhs = [0] * len(dual)
    objective = F(0)
    for world, marginal in enumerate((first, second)):
        inverse = [
            1 / prod(marginal[i] for i in sample) for _, sample, _, _ in patterns
        ]
        for j, counts in enumerate(states):
            means = [
                v - m * p[world] for v, m, p in zip(counts, sizes, order, strict=True)
            ]
            column = [1 - 2 * world]
            for t in means:
                column.extend((0, t) if world else (t, 0))
            coefficient = g + (1 / prod(marginal) if j == n - 1 else 0)
            column.append(coefficient if world else 0)
            for (needed, _, c, direction), scale in zip(patterns, inverse, strict=True):
                b = scale * prod(
                    F(comb(v, r), comb(m, r))
                    for v, m, r in zip(counts, sizes, needed, strict=True)
                )
                if world == direction:
                    column.append(b + ((1 - c) * g if world else 0))
                else:
                    column.append(-c * b + ((1 - c) * g if world else 0))
            cost = 0 if world else coefficient
            assert dot(dual, column) >= cost
            weight = primal[world * n + j]
            if weight:
                objective += cost * weight
                lhs = [a + weight * b for a, b in zip(lhs, column, strict=True)]
    assert lhs[:s] == [0] * (s - 1) + [1]
    slacks = iter(primal[2 * n :])
    for x, (_, _, c, _) in zip(lhs[s:], patterns, strict=True):
        assert x + (next(slacks) if c > 1 else 0) == 0
    assert objective == dual[s - 1] == F(proof["odds"]) >= 1
    return objective


def box_value(lo, hi, q, floor, caps, report, limit):
    assert len(lo) == len(hi) == len(q) >= 2
    assert all(0 < l <= h < 1 and 0 < s < 1 for l, h, s in zip(lo, hi, q, strict=True))
    assert 0 < floor < 1 and len(caps) < len(lo) and all(x >= 1 for x in caps)
    splits = report["splits"]
    assert len(splits) <= limit
    visited = set()
    used = {}

    def norm(p):
        if p not in used:
            key = " ".join(map(str, p))
            used[p] = proof_value(p, q, floor, caps, report["points"][key])
        return used[p]

    def cover(path, a, b):
        if path not in splits:
            return norm(a) * prod(b) / prod(q)
        visited.add(path)
        i = splits[path]
        assert type(i) is int and 0 <= i < len(a) and a[i] < b[i]
        cut = (a[i] + b[i]) / 2
        return max(
            cover(path + "0", a, b[:i] + (cut,) + b[i + 1 :]),
            cover(path + "1", a[:i] + (cut,) + a[i + 1 :], b),
        )

    upper = cover("", lo, hi)
    assert visited == set(splits)
    witness = tuple(map(F, report["witness"].split()))
    assert all(a <= x <= b for a, x, b in zip(lo, witness, hi, strict=True))
    lower = norm(witness) * prod(witness) / prod(q)
    start = norm(lo) * prod(lo) / prod(q)
    root_bound = norm(lo) * prod(hi) / prod(q)
    high_end = norm(hi) * prod(hi) / prod(q)
    assert set(report["points"]) == {" ".join(map(str, p)) for p in used}
    assert (lower, upper) == (F(report["lower"]), F(report["upper"]))
    assert max(start, high_end) <= lower <= upper <= root_bound
    return start, root_bound, lower, upper


def archive_contracts(path):
    raw = path.read_bytes()
    assert sha1(f"blob {len(raw)}\0".encode() + raw).hexdigest() == PIN
    for row in json.loads(gzip.decompress(raw)):
        if row["status"] != "scored":
            continue
        rates = []
        selected = row["pair"][2][:4]
        assert len(selected) == len(set(selected)) == 4
        pair = row["pair"][:2]
        for i in selected:
            pair_labels = {mode >> (2 * i) & 3 for mode in pair}
            assert pair_labels == {1, 2}
            early, late = row["labels"][2 * i : 2 * i + 2]
            shared = 1 - early[2] - late[2]
            rates.append(
                F(9, 10) if shared <= 5 else F(4, 5) if shared <= 30 else F(3, 5)
            )
        uncertain = F(1, 20)
        rate_boxes = []
        for shift in (F(1, 40), -F(1, 40)):
            center = tuple(p + shift for p in rates)
            rate_boxes.append(
                (
                    (center[0] - uncertain,) + center[1:],
                    (center[0] + uncertain,) + center[1:],
                )
            )
        identity = [row[k] for k in ("domain", "repo", "run", "job")]
        yield identity, rate_boxes


def summarize(path, rows, counterexample, verify=True):
    totals = Counter()
    root = {level: Counter() for level in LEVELS}
    refined = {level: Counter() for level in LEVELS}
    worst = F(1)
    improvement = F(1)
    for (identity, boxes), row in zip(archive_contracts(path), rows, strict=True):
        assert row["id"] == identity
        totals["archives"] += 1
        for (lo, hi), (q, _), proof in zip(
            boxes, reversed(boxes), row["directions"], strict=True
        ):
            if verify:
                start, top, lower, upper = box_value(
                    lo, hi, q, FLOOR, CAPS, proof, SPLITS
                )
            else:
                start = (
                    F(proof["points"][" ".join(map(str, lo))]["odds"])
                    * prod(lo)
                    / prod(q)
                )
                top = start * prod(hi) / prod(lo)
                lower, upper = F(proof["lower"]), F(proof["upper"])
            other_end = (
                F(proof["points"][" ".join(map(str, hi))]["odds"]) * prod(hi) / prod(q)
            )
            totals["directions"] += 1
            totals["within_gate"] += upper <= TOLERANCE * lower
            totals["naive_endpoint_below_witness"] += start < lower
            totals["bound_tightened"] += upper < top
            totals["sampled_inside_better"] += lower > max(start, other_end)
            totals["threshold_3_resolved_by_other_endpoint"] += start <= 3 < other_end
            totals["max_splits"] = max(totals["max_splits"], len(proof["splits"]))
            worst = max(worst, upper / lower)
            improvement = max(improvement, top / upper)
            for level in LEVELS:
                root[level][
                    "pass" if top <= level else "fail" if start > level else "uncertain"
                ] += 1
                refined[level][
                    "pass"
                    if upper <= level
                    else "fail"
                    if lower > level
                    else "uncertain"
                ] += 1
    lo, hi, q, g, b = EXAMPLE
    if verify:
        first, _, lower, upper = box_value(*EXAMPLE, counterexample["box"], 64)
        inside = (
            proof_value(PEAK, q, g, b, counterexample["exact_peak"])
            * prod(PEAK)
            / prod(q)
        )
    else:
        report = counterexample["box"]
        first = F(report["points"][" ".join(map(str, lo))]["odds"]) * prod(lo) / prod(q)
        lower, upper = map(F, (report["lower"], report["upper"]))
        inside = F(counterexample["exact_peak"]["odds"]) * prod(PEAK) / prod(q)
    last = (
        F(counterexample["box"]["points"][" ".join(map(str, hi))]["odds"])
        * prod(hi)
        / prod(q)
    )
    assert lower <= inside <= upper and max(first, last) < inside == PEAK_ODDS
    assert (first, last) == (F(44, 81), F(319, 102))
    assert upper <= F(101, 100) * lower
    assert totals["archives"] == 81 and totals["directions"] == 162
    return {
        "counts": dict(totals),
        "worst_remaining_factor": str(worst),
        "greatest_tightening_factor": str(improvement),
        "decisions": {
            str(level): {
                name: {k: data[level][k] for k in ("pass", "fail", "uncertain")}
                for name, data in (("root", root), ("refined", refined))
            }
            for level in LEVELS
        },
        "example": {
            "endpoint_odds": [str(first), str(last)],
            "maximizer_first_refusal": str(PEAK[0]),
            "analytic_peak": str(inside),
            "certified_box": [str(lower), str(upper)],
        },
        "gate": totals["within_gate"] == totals["directions"],
    }


def main():
    import argparse

    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("source", type=Path)
    cli.add_argument("output", type=Path)
    cli.add_argument(
        "--contract", action="store_true", help="check a JSON contract and certificate"
    )
    cli.add_argument("--splits", type=int, default=128)
    a = cli.parse_args()
    if a.contract:
        data = json.loads(a.source.read_text(encoding="utf-8"))
        certs = json.loads(a.output.read_text(encoding="utf-8-sig"))
        report = {}
        for x, y in (("first", "second"), ("second", "first")):
            lo, hi = zip(*(tuple(map(F, row)) for row in data[x]), strict=True)
            q = tuple(F(row[0]) for row in data[y])
            key = f"{x}/{y}"
            _, _, lower, upper = box_value(
                lo,
                hi,
                q,
                F(data["floor"]),
                tuple(map(F, data["caps"])),
                certs[key],
                a.splits,
            )
            report[key] = {
                "lower": str(lower),
                "upper": str(upper),
                "factor": str(upper / lower),
            }
        print(json.dumps({"verified": True, "directions": report}))
        return
    d = json.loads(
        gzip.decompress((a.output / "audit-asymmetric-policies.json.gz").read_bytes())
    )
    answer = summarize(a.source, d["cases"], d["counterexample"])
    assert answer == json.loads(
        (a.output / "audit-asymmetric-results.json").read_text("utf-8")
    )
    print(
        json.dumps(
            {"verified": True, "counts": answer["counts"], "gate": answer["gate"]}
        )
    )


if __name__ == "__main__":
    main()
