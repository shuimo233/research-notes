"""Check probability, drift, infeasibility, and budget certificates using exact arithmetic."""

import argparse
from collections import Counter, defaultdict
from fractions import Fraction as F
import gzip
from hashlib import sha1
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from joint_odds_check import bounds, check_case, from_axes, read_source

PIN = "95627713067283caaf7967952fcc55f924ac1689"


def read_published(joint):
    data = joint.read_bytes()
    assert sha1(f"blob {len(data)}\0".encode() + data).hexdigest() == PIN
    return json.loads(gzip.decompress(data))


def reconstruct(prior):
    views = prior["views"]
    axes = [
        tuple(from_axes(view, mask) for view, mask in zip(views, mode, strict=True))
        for mode in prior["modes"]
    ]
    caps = [F(view["certificate"]["ratio"]) for view in views]
    thresholds = [F(1, 2 * len(view["labels"])) for view in views]
    floors = {(i, j): F(p) for i, j, p in prior["floor"]}
    return axes, caps, thresholds, floors


def validate_dual(axes, caps, thresholds, floors, ratio, cert, expected):
    coefficients = defaultdict(F)
    value = F(0)
    seen = set()
    for name, raw in cert:
        token, *key = name
        price = F(raw)
        assert (
            price > 0 and tuple(name) not in seen and all(type(k) is int for k in key)
        )
        seen.add(tuple(name))
        if token == "ground":
            i, j = key
            value += price * floors[i, j]
            coefficients["pair", i, j] += price
            continue
        x, *index = key
        assert 0 <= x < len(axes)
        u, v = axes[x]
        if token == "total":
            (sign,) = index
            assert sign in (1, -1)
            value += price * sign
            for i in u:
                for j in v:
                    coefficients["world", x, i, j] += price * sign
            continue
        if token in ("pair_min", "pair_max"):
            i, j = index
            assert i in u and j in v
            if token == "pair_min":
                coefficients["world", x, i, j] += price
                coefficients["pair", i, j] -= price
            else:
                coefficients["world", x, i, j] -= price
                coefficients["pair", i, j] += price * ratio
            continue
        side, label = index
        assert side in (0, 1) and label in axes[x][side]
        axis = axes[x][side]
        sign = -1 if token in ("axis_max", "keep_max", "service") else 1
        for i in u:
            for j in v:
                if (i, j)[side] == label:
                    coefficients["world", x, i, j] += price * sign
        if token == "axis_min":
            coefficients["view", side, label] -= price
        elif token == "axis_max":
            coefficients["view", side, label] += price * caps[side]
        elif token in ("keep_min", "keep_max"):
            value += price * sign * axis[label]
            coefficients["delta"] += price
        elif token == "truth":
            assert label >= 0
            value += price * thresholds[side]
        else:
            assert token == "service" and label == -1 and len(axis) > 1
            value -= price / 2
    if expected is None:
        assert value > 0 and all(c <= 0 for c in coefficients.values())
    else:
        assert value == expected and all(
            c <= int(key == "delta") for key, c in coefficients.items()
        )


def validate_policy(axes, caps, thresholds, floors, ratio, proof):
    rows = []
    drift = F(0)
    revised = [[], []]
    for (left, right), packed in zip(axes, proof["rows"], strict=True):
        keys = sorted((i, j) for i in left for j in right)
        row = dict(zip(keys, map(F, packed), strict=True))
        assert (
            all(x >= floors[cell] for cell, x in row.items()) and sum(row.values()) == 1
        )
        rows.append(row)
        for side, axis in enumerate((left, right)):
            distribution = {
                label: sum(x for cell, x in row.items() if cell[side] == label)
                for label in axis
            }
            assert all(
                p >= thresholds[side] for label, p in distribution.items() if label >= 0
            )
            if len(axis) > 1:
                assert distribution[-1] <= F(1, 2)
            drift = max(drift, *(abs(axis[j] - p) for j, p in distribution.items()))
            revised[side].append(distribution)
    for cap, distributions in zip(caps, revised, strict=True):
        assert bounds(distributions)[0] <= cap
    assert bounds(rows)[0] == F(proof["actual_joint"]) <= ratio
    assert drift == F(proof["drift"])
    return drift, rows


def verify_budget(axes, caps, thresholds, floors, ratio, certificate):
    assert any(set(L) == set(R) == {-1} for L, R in axes)
    minimum = []
    for side in (0, 1):
        supports = [set(world[side]) - {-1} for world in axes]
        minimum.append(
            {
                j: max(thresholds[side], F(1, 2) / caps[side] if {j} in supports else 0)
                for j in set().union(*supports)
            }
        )

    values = {}
    for x, axis in enumerate(axes):
        for side in (0, 1):
            known = axis[side]
            if len(known) == 1:
                continue
            other = 1 - side
            right_labels = axis[other].keys() - {-1}
            forced = max(floors[-1, -1], 1 / ratio)
            other_sets = [set(w[other]) - {-1} for w in axes if len(w[side]) == 1]
            for j in right_labels:
                low = (
                    F(1, 2)
                    if {j} in other_sets
                    else minimum[other][j]
                    if any(j in labels for labels in other_sets)
                    else F(0)
                )
                forced += max(low / ratio, floors[(-1, j) if side == 0 else (j, -1)])
            available = min(F(1, 2), 1 - sum(minimum[side][j] for j in known if j >= 0))
            if forced > available:
                values[x, side] = dict(
                    world=x, side=side, required=str(forced), capacity=str(available)
                )
    if certificate is None:
        assert not values
    else:
        assert values[certificate["world"], certificate["side"]] == certificate


def check_result(source, prior, current):
    check_case(source, prior)
    assert current["job"] == prior["job"] and current["status"] == prior["status"]
    if current["status"] != "scored":
        assert current == {"job": prior["job"], "status": prior["status"]}
        return None
    notes = current["targets"]
    assert set(notes) == set(prior["targets"])
    axes, caps, thresholds, floors = reconstruct(prior)
    both = any(all(len(a) > 1 for a in world) for world in axes)
    assert current["all_independent_lower"] == ("4" if both else "1")
    solutions = {}
    for limit, proof in notes.items():
        ratio = F(limit)
        original = prior["targets"][limit]["status"]
        verify_budget(axes, caps, thresholds, floors, ratio, proof["refusal_budget"])
        if proof["status"] == "feasible":
            assert proof["refusal_budget"] is None
            d, rows = validate_policy(axes, caps, thresholds, floors, ratio, proof)
            validate_dual(axes, caps, thresholds, floors, ratio, proof["dual"], d)
            assert (d == 0) == (original == "feasible")
            solutions[limit] = (d, rows)
        else:
            assert proof["status"] == "infeasible" and original == "infeasible"
            validate_dual(axes, caps, thresholds, floors, ratio, proof["dual"], None)
    return solutions


def check(source, joint, output):
    packets = read_source(source)
    fixed = read_published(joint)
    changed = json.loads(
        gzip.decompress((output / "retuned-odds-policies.json.gz").read_bytes())
    )
    reported = json.loads((output / "retuned-odds-results.json").read_bytes())
    c = Counter()
    for packet, old, new in zip(packets, fixed, changed, strict=True):
        valid = check_result(packet, old, new)
        if valid is None:
            continue
        c["scored"] += 1
        c["certified_targets"] += len(new["targets"])
        c["feasible_targets"] += len(valid)
        c["post_hoc_budget_rejections"] += sum(
            row["refusal_budget"] is not None for row in new["targets"].values()
        )
        threshold = F(new["all_independent_lower"])
        c["beats_every_independent_at_target"] += sum(F(r) < threshold for r in valid)
        mid = old["midpoint"]
        if old["targets"][mid]["status"] == "infeasible":
            c["prior_midpoint_failures"] += 1
            if mid in valid:
                c["rescued_midpoints"] += 1
                if valid[mid][0] <= F(1, 10):
                    c["rescued_within_budget"] += 1
                    c["rescued_within_budget_beats_independent"] += F(mid) < threshold
    assert reported == dict(c) | {"gate": c["rescued_within_budget"] >= 5}
    return reported | {"verified": True}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("joint", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    if not __debug__:
        raise RuntimeError("enable assertions")
    print(json.dumps(check(args.source, args.joint, args.output)))
