"""Independently verify the fixed-marginal benchmark without optimization software."""

import argparse
from collections import defaultdict
from fractions import Fraction
import gzip
from hashlib import sha1
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from denial_odds_check import dual
from public_optimality_check import model
from selection_odds_check import independent_patterns

PIN = "6a2816703f9a7569cce1c98f061fa5bc5fb5321b"


def read_source(path):
    content = path.read_bytes()
    if sha1(f"blob {len(content)}\0".encode() + content).hexdigest() != PIN:
        raise ValueError("not the frozen public catalogue")
    return json.loads(gzip.decompress(content))


def from_axes(axis, mask):
    if mask == 0:
        return {-1: Fraction(1)}
    weights = list(map(Fraction, axis["certificate"]["weights"]))
    selected = {j: w for j, w in enumerate(weights) if mask & (1 << j)}
    Z = sum(selected.values())
    scale = max(Fraction(1), Fraction(1, 2) / Z)
    return {-1: 1 - scale * Z, **{j: w * scale for j, w in selected.items()}}


def bounds(channels):
    maximum = {}
    minimum = {}
    for channel in channels:
        for j, p in channel.items():
            maximum[j] = max(p, maximum.get(j, p))
            minimum[j] = min(p, minimum.get(j, p))
    return max(maximum[j] / p for j, p in minimum.items()), minimum


def verify_negative(worlds, floors, ratio, rows):
    residual = defaultdict(Fraction)
    weighted_gap = Fraction(0)
    assert rows
    for index, L, R, p in rows:
        p = Fraction(p)
        assert type(index) is int and 0 <= index < len(worlds) and p > 0
        left, right = worlds[index]
        assert len(set(L)) == len(L) and len(set(R)) == len(R)
        assert set(L) <= left.keys() and set(R) <= right.keys()
        weighted_gap += p * (sum(left[i] for i in L) - sum(right[j] for j in R))
        for i in left:
            for j in right:
                if i in L and j not in R:
                    residual[i, j] += p * ratio
                if i not in L and j in R:
                    residual[i, j] -= p
    assert all(x <= 0 for x in residual.values())
    assert weighted_gap > sum(x * floors[c] for c, x in residual.items())


def verify_feasible(worlds, floors, ratio, data):
    weights = dict(zip(floors, map(Fraction, data["weights"]), strict=True))
    assert all(weights[c] >= f for c, f in floors.items())
    rows = []
    for (u, v), values in zip(worlds, data["rows"], strict=True):
        row = dict(
            zip(
                sorted((i, j) for i in u for j in v), map(Fraction, values), strict=True
            )
        )
        assert all(
            weights[cell] <= p <= ratio * weights[cell] for cell, p in row.items()
        )
        for i, p in u.items():
            assert sum(row[i, j] for j in v) == p
        for j, p in v.items():
            assert sum(row[i, j] for i in u) == p
        rows.append(row)
    actual, _ = bounds(rows)
    assert actual == Fraction(data["actual_ratio"]) <= ratio
    return rows


def mixture(worlds, opposite):
    result = []
    for left, right in worlds:
        both = (
            max(0, 1 - left[-1] - right[-1])
            if opposite
            else 1 - max(left[-1], right[-1])
        )
        outcome = {}
        for i, p in left.items():
            for j, q in right.items():
                if i < 0 and j < 0:
                    block = left[-1] + right[-1] + both - 1
                elif i < 0:
                    block = 1 - right[-1] - both
                elif j < 0:
                    block = 1 - left[-1] - both
                else:
                    block = both
                u = left[-1] if i < 0 else 1 - left[-1]
                v = right[-1] if j < 0 else 1 - right[-1]
                outcome[i, j] = (1 + block / (u * v)) * p * q / 2
        result.append(outcome)
    return result


def check_diagnostics(worlds, floors, targets, diagnostics):
    assert set(targets) == set(diagnostics)
    cells = {cell: [] for cell in floors}
    for L, R in worlds:
        for i, x in L.items():
            for j, y in R.items():
                row = sum(floors[i, k] for k in R if k != j)
                col = sum(floors[k, j] for k in L if k != i)
                outside = sum(floors[k, l] for k in L if k != i for l in R if l != j)
                cells[i, j].append(
                    (max(floors[i, j], x + y - 1 + outside), min(x - row, y - col))
                )
    for key, report in diagnostics.items():
        ratio = Fraction(key)
        required = {
            c: max(floors[c], max(a for a, _ in intervals) / ratio)
            for c, intervals in cells.items()
        }
        ceiling = {c: min(b for _, b in intervals) for c, intervals in cells.items()}
        if report is None:
            assert all(required[c] <= ceiling[c] for c in cells)
            assert all(
                all(sum(required[i, j] for j in R) <= x for i, x in L.items())
                and all(sum(required[i, j] for i in L) <= y for j, y in R.items())
                for L, R in worlds
            )
            continue
        assert targets[key]["status"] == "infeasible"
        if report["kind"] == "cell":
            c = tuple(report["cell"])
            forced, available = required[c], ceiling[c]
        else:
            L, R = worlds[report["world"]]
            k = report["label"]
            assert report["kind"] in ("left", "right")
            if report["kind"] == "left":
                forced, available = sum(required[k, j] for j in R), L[k]
            else:
                forced, available = sum(required[i, k] for i in L), R[k]
        assert (
            forced
            == Fraction(report["required"])
            > Fraction(report["available"])
            == available
        )


def check_case(source, result):
    catalogue = source["catalogue"]
    assert result["job"] == catalogue["job"]
    n, _, _, _, base, _, _ = model(catalogue["packet"])
    raw = independent_patterns(n, base, catalogue["entries"])
    assert raw == [0, *source["patterns"]]
    links = [x["comparison"][:2] for x in catalogue["entries"]]
    incidence = {i: [j for j, l in enumerate(links) if i in l] for i in range(1, n)}
    incidences = [ids for ids in incidence.values() if ids]
    ordered = sorted(
        (i for i, ids in incidence.items() if ids),
        key=lambda i: (-len(incidence[i]), i),
    )
    if len({tuple(ids) for ids in incidences}) < 2:
        assert result == {"job": catalogue["job"], "status": "only_one_view"}
        return None
    first = ordered[0]
    second = next(i for i in ordered[1:] if incidence[i] != incidence[first])
    assert result["status"] == "scored"
    views = result["views"]
    for axis, event in zip(views, [first, second], strict=True):
        assert axis["event"] == event and axis["labels"] == incidence[event]
    modes = sorted(
        {
            tuple(
                sum(2**k for k, j in enumerate(incidence[event]) if rawmask // 2**j % 2)
                for event in (first, second)
            )
            for rawmask in raw
        }
    )
    assert [list(m) for m in modes] == result["modes"]
    for side, axis in enumerate(views):
        n = len(axis["labels"])
        nonzero = sorted({m[side] for m in modes if m[side]})
        assert axis["certificate"]["service"] == "1/2"
        dual(axis["certificate"], n, nonzero, Fraction(1, 2 * n), True)
    worlds = [
        tuple(from_axes(axis, m) for axis, m in zip(views, mode, strict=True))
        for mode in modes
    ]
    products = [
        {(i, j): x * y for i, x in L.items() for j, y in R.items()} for L, R in worlds
    ]
    independent, minima = bounds(products)
    floors = {cell: x / 2 for cell, x in sorted(minima.items())}
    published = {(i, j): Fraction(x) for i, j, x in result["floor"]}
    assert len(result["floor"]) == len(published) and floors == published
    true_marginal = max(bounds([w[side] for w in worlds])[0] for side in (0, 1))
    assert Fraction(result["independent"]) == independent
    assert Fraction(result["marginal"]) == true_marginal
    midpoint = (independent + true_marginal) / 2
    assert Fraction(result["midpoint"]) == midpoint
    for tag, opposite in (("shared", False), ("opposed", True)):
        alternative = mixture(worlds, opposite)
        actual, _ = bounds(alternative)
        assert Fraction(result["simple"][tag]) == actual
        for (L, R), row in zip(worlds, alternative, strict=True):
            assert all(p >= floors[c] for c, p in row.items())
            assert all(sum(row[i, j] for j in R) == p for i, p in L.items())
            assert all(sum(row[i, j] for i in L) == p for j, p in R.items())
    targets = result["targets"]
    assert set(targets) == set(map(str, (true_marginal, midpoint)))
    feasible = {}
    for key, data in targets.items():
        ratio = Fraction(key)
        if data["status"] == "infeasible":
            verify_negative(worlds, floors, ratio, data["certificate"])
        else:
            assert data["status"] == "feasible"
            feasible[key] = verify_feasible(worlds, floors, ratio, data)
    check_diagnostics(worlds, floors, targets, result["post_hoc_diagnostics"])
    return feasible


def check(source, output):
    packets = read_source(source)
    results = json.loads(
        gzip.decompress((output / "joint-odds-policies.json.gz").read_bytes())
    )
    reported = json.loads((output / "joint-odds-results.json").read_bytes())
    scored = []
    for packet, p in zip(packets, results, strict=True):
        feasible = check_case(packet, p)
        if feasible is not None:
            scored.append((p, feasible))
    improved = 0
    counts = defaultdict(int)
    ratios = []
    for p, yes in scored:
        independent, marginal, midpoint = (
            Fraction(p[k]) for k in ("independent", "marginal", "midpoint")
        )
        counts["baseline_gap"] += independent > marginal
        if independent > marginal and p["midpoint"] in yes:
            improved += 1
            counts["simpler_reaches_improvement"] += any(
                Fraction(k) <= midpoint for k in p["simple"].values()
            )
        counts["reach_marginal"] += p["marginal"] in yes
        counts["certified_targets"] += len(p["targets"])
        counts["modes"] += len(p["modes"])
        for d in p["post_hoc_diagnostics"].values():
            if d is not None:
                counts[
                    "rejected_by_cell_check"
                    if d["kind"] == "cell"
                    else "rejected_by_marginal_check"
                ] += 1
        ratios.append(
            (
                max(independent, marginal),
                max(
                    marginal, min([independent, *(bounds(s)[0] for s in yes.values())])
                ),
            )
        )
    assert reported == dict(
        catalogues=len(results),
        scored=len(scored),
        skipped=len(results) - len(scored),
        **{
            k: counts[k]
            for k in (
                "modes",
                "certified_targets",
                "baseline_gap",
                "reach_marginal",
                "simpler_reaches_improvement",
                "rejected_by_cell_check",
                "rejected_by_marginal_check",
            )
        },
        improved=improved,
        best_tested_worst_ratio=str(max(y for _, y in ratios)),
        independent_worst_ratio=str(max(x for x, _ in ratios)),
        gate=len(results) == 25 and improved >= 5,
    )
    return reported | {"verified": True}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    if not __debug__:
        raise RuntimeError("enable assertions")
    print(json.dumps(check(args.source, args.output)))
