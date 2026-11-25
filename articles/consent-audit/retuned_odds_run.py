"""Certify minimum per-output policy changes at prescribed joint odds bounds."""

import argparse
from collections import defaultdict
from fractions import Fraction as F
import gzip
from hashlib import sha1
import json
from pathlib import Path

from denial_odds import ratio_of
from joint_odds_check import from_axes, read_source
from retuned_odds import refusal_budget
from selection_odds_run import rational

PIN = "95627713067283caaf7967952fcc55f924ac1689"
DRIFT = ("drift",)


def read_joint(path):
    raw = path.read_bytes()
    if sha1(f"blob {len(raw)}\0".encode() + raw).hexdigest() != PIN:
        raise ValueError("not the frozen joint study")
    return json.loads(gzip.decompress(raw))


def data(packet):
    worlds = [
        tuple(from_axes(v, m) for v, m in zip(packet["views"], mode, strict=True))
        for mode in packet["modes"]
    ]
    caps = tuple(F(v["certificate"]["ratio"]) for v in packet["views"])
    label_floor = tuple(F(1, 2 * len(v["labels"])) for v in packet["views"])
    floor = {(i, j): F(f) for i, j, f in packet["floor"]}
    return worlds, caps, label_floor, floor


def inequalities(worlds, caps, label_floor, floor, ratio):
    for i, j in floor:
        yield ("ground", i, j), {("joint", i, j): 1}, floor[i, j]
    for world, old in enumerate(worlds):
        L, R = old
        cells = [(i, j) for i in L for j in R]
        positions = {(i, j): ("cell", world, i, j) for i, j in cells}
        yield ("total", world, 1), dict.fromkeys(positions.values(), 1), 1
        yield ("total", world, -1), dict.fromkeys(positions.values(), -1), -1
        for (i, j), name in positions.items():
            a = ("joint", i, j)
            yield ("pair_min", world, i, j), {name: 1, a: -1}, 0
            yield ("pair_max", world, i, j), {name: -1, a: ratio}, 0
        for side, axis in enumerate(old):
            for label, p in axis.items():
                subset = [
                    name for cell, name in positions.items() if cell[side] == label
                ]
                mass = dict.fromkeys(subset, 1)
                lost = dict.fromkeys(subset, -1)
                idx = (world, side, label)
                a = ("view", side, label)
                yield ("axis_min", *idx), mass | {a: -1}, 0
                yield ("axis_max", *idx), lost | {a: caps[side]}, 0
                yield ("keep_min", *idx), mass | {DRIFT: 1}, p
                yield ("keep_max", *idx), lost | {DRIFT: 1}, -p
                if label >= 0:
                    yield ("truth", *idx), mass, label_floor[side]
                elif len(axis) > 1:
                    yield ("service", *idx), lost, -F(1, 2)


def check_linear(cuts, values, certificate):
    combined = defaultdict(F)
    target = F(0)
    for (_, coeff, rhs), y in zip(cuts, certificate, strict=True):
        if y < 0:
            return False
        if y:
            target += y * rhs
            for j, a in coeff.items():
                combined[j] += y * a
    if values is None:
        return target > 0 and all(v <= 0 for v in combined.values())
    return (
        target == values[DRIFT]
        and all(v <= int(j == DRIFT) for j, v in combined.items())
        and all(x >= 0 for x in values.values())
        and all(
            sum(v * values[k] for k, v in coeff.items()) >= rhs
            for _, coeff, rhs in cuts
        )
    )


def solve(worlds, caps, label_floor, floor, ratio):
    from scipy import __version__
    from scipy.optimize import linprog
    from scipy.sparse import coo_matrix, hstack
    import numpy as np

    if __version__ != "1.16.3":
        raise RuntimeError("this replay pins scipy 1.16.3")
    cuts = list(inequalities(worlds, caps, label_floor, floor, ratio))
    names = list(dict.fromkeys((DRIFT, *(key for _, row, _ in cuts for key in row))))
    cols = {name: j for j, name in enumerate(names)}
    x, y, v = [], [], []
    for i, (_, row, _) in enumerate(cuts):
        for key, coeff in row.items():
            x.append(i)
            y.append(cols[key])
            v.append(-float(coeff))
    A = coo_matrix((v, (x, y)), shape=(len(cuts), len(names))).tocsr()
    b = [-float(rhs) for _, _, rhs in cuts]
    objective = [1] + [0] * (len(names) - 1)
    result = linprog(objective, A_ub=A, b_ub=b, method="highs")
    if result.status == 2:
        phase = hstack((A, coo_matrix(-np.ones((len(cuts), 1)))), format="csr")
        result = linprog([0] * len(names) + [1], A_ub=phase, b_ub=b, method="highs")
        if not result.success:
            raise ArithmeticError(
                "could not reconstruct phase-one certificate: " + result.message
            )
        values = None
    elif result.success:
        values = dict(zip(names, map(rational, result.x), strict=True))
    else:
        raise ArithmeticError(result.message)
    certificate = [-rational(p) for p in result.ineqlin.marginals]
    if not check_linear(cuts, values, certificate):
        raise ArithmeticError(
            "could not recover an exact primal or dual for " + str(ratio)
        )
    proof = [
        [list(key), str(value)]
        for (key, _, _), value in zip(cuts, certificate, strict=True)
        if value
    ]
    if values is None:
        return dict(status="infeasible", dual=proof)
    probabilities = []
    for x, (left, right) in enumerate(worlds):
        probabilities.append(
            {
                (i, j): values["cell", x, i, j]
                for i in sorted(left)
                for j in sorted(right)
            }
        )
    return dict(
        status="feasible",
        drift=str(values[DRIFT]),
        actual_joint=str(ratio_of(probabilities)),
        rows=[[str(v) for v in row.values()] for row in probabilities],
        dual=proof,
    )


def make(p):
    if p["status"] != "scored":
        return dict(job=p["job"], status=p["status"])
    worlds, caps, label_floor, floor = data(p)
    targets = {}
    for key, prior in p["targets"].items():
        row = solve(worlds, caps, label_floor, floor, F(key))
        diagnostic = refusal_budget(worlds, caps, label_floor, floor, F(key))
        if diagnostic is not None and row["status"] != "infeasible":
            raise ArithmeticError("diagnostic contradicts a feasible policy")
        row["refusal_budget"] = diagnostic
        d = F(row["drift"]) if row["status"] == "feasible" else None
        if (d == 0) != (prior["status"] == "feasible"):
            raise ArithmeticError("zero drift and fixed marginal results disagree")
        targets[key] = row
    both = any(len(left) > 1 and len(right) > 1 for left, right in worlds)
    return dict(
        job=p["job"],
        status="scored",
        targets=targets,
        all_independent_lower="4" if both else "1",
    )


def summarize(paired):
    counter = defaultdict(int)
    for old, new in paired:
        if new["status"] != "scored":
            continue
        counter["scored"] += 1
        for key, row in new["targets"].items():
            counter["certified_targets"] += 1
            counter["post_hoc_budget_rejections"] += row["refusal_budget"] is not None
            if row["status"] == "feasible":
                counter["feasible_targets"] += 1
                counter["beats_every_independent_at_target"] += F(key) < F(
                    new["all_independent_lower"]
                )
        key = old["midpoint"]
        if old["targets"][key]["status"] == "infeasible":
            counter["prior_midpoint_failures"] += 1
            row = new["targets"][key]
            if row["status"] == "feasible":
                counter["rescued_midpoints"] += 1
                if F(row["drift"]) <= F(1, 10):
                    counter["rescued_within_budget"] += 1
                    counter["rescued_within_budget_beats_independent"] += F(key) < F(
                        new["all_independent_lower"]
                    )
    keys = (
        "scored",
        "certified_targets",
        "feasible_targets",
        "beats_every_independent_at_target",
        "post_hoc_budget_rejections",
        "prior_midpoint_failures",
        "rescued_midpoints",
        "rescued_within_budget",
        "rescued_within_budget_beats_independent",
    )
    return {k: counter[k] for k in keys} | {
        "gate": counter["rescued_within_budget"] >= 5
    }


def run(source, joint, output):
    source_rows = read_source(source)
    packets = read_joint(joint)
    assert [s["catalogue"]["job"] for s in source_rows] == [p["job"] for p in packets]
    released = []
    for packet in packets:
        try:
            released.append(make(packet))
        except ArithmeticError as error:
            raise ArithmeticError(f"job {packet['job']}") from error
    summary = summarize(zip(packets, released, strict=True))
    output.mkdir(parents=True, exist_ok=True)
    (output / "retuned-odds-policies.json.gz").write_bytes(
        gzip.compress(
            json.dumps(released, separators=(",", ":"), ensure_ascii=True).encode(),
            mtime=0,
        )
    )
    (output / "retuned-odds-results.json").write_text(
        json.dumps(summary, indent=2) + "\n", encoding="utf-8", newline="\n"
    )
    print(json.dumps(summary))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("joint", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    run(args.source, args.joint, args.output)
