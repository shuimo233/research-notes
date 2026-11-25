"""Verify the held-out CI screen with raw difference constraints and exact certificates."""

import argparse
from collections import Counter, defaultdict
from fractions import Fraction as F
import gzip
from hashlib import sha1
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from denial_odds_check import dual
from joint_odds_check import bounds, from_axes
from public_optimality_check import model
from retuned_odds_check import validate_dual, validate_policy, verify_budget
from selection_odds_check import independent_patterns
from slack_certificate_check import potential

PIN = "38632c54456c76ff237bb8bf4cf66257ed6041e7"


def sample(source):
    raw = source.read_bytes()
    assert sha1(f"blob {len(raw)}\0".encode() + raw).hexdigest() == PIN
    groups = defaultdict(list)
    for p in json.loads(gzip.decompress(raw)):
        groups[p["repo"]].append(p)
    return [
        p
        for repo in sorted(groups)
        for p in sorted(groups[repo], key=lambda p: (int(p["run"]), int(p["job"])))[:12]
    ]


def verify_case(packet, row):
    assert all(packet[k] == row[k] for k in ("repo", "run", "job"))
    n, _, _, _, base, closed, _ = model(packet)
    edges = list(base)
    labels = []
    positions = sorted(set((u, v) for u, v, _ in packet["archive"]["targets"]))
    for u, v in positions:
        lo, hi = -closed[v][u], closed[u][v]
        if lo == hi:
            continue
        c = (lo + hi + 1) // 2
        constraint = (u, v, c - 1)
        if potential(n, [*edges, constraint]) is not None:
            edges.append(constraint)
            labels.append([u, v, c])
            if len(labels) == 6:
                break
    assert row["labels"] == labels
    incidence = {
        v: [i for i, (u, w, _) in enumerate(labels) if v in (u, w)] for v in range(1, n)
    }
    focus = []
    for event in sorted(incidence, key=lambda v: (-len(incidence[v]), v)):
        if incidence[event] and incidence[event] not in [ids for _, ids in focus]:
            focus.append((event, incidence[event]))
            if len(focus) == 2:
                break
    if len(focus) < 2:
        assert row == {k: packet[k] for k in ("repo", "run", "job")} | dict(
            status="one_or_no_views", labels=labels
        )
        return None
    assert row["status"] == "scored"
    axes = row["views"]
    for axis, (event, ids) in zip(axes, focus, strict=True):
        assert axis["event"] == event and axis["labels"] == ids
    raw = independent_patterns(n, base, [{"comparison": q} for q in labels])
    modes = sorted(
        {
            tuple(
                sum(2**i for i, p in enumerate(ids) if z // 2**p % 2)
                for _, ids in focus
            )
            for z in raw
        }
    )
    assert raw[0] == 0 and row["modes"] == [list(m) for m in modes]
    truth = [F(1, 2 * len(axis["labels"])) for axis in axes]
    for side, axis in enumerate(axes):
        possible = sorted({m[side] for m in modes} - {0})
        cert = axis["certificate"]
        assert cert["service"] == "1/2"
        dual(cert, len(axis["labels"]), possible, truth[side], True)
    worlds = [
        tuple(from_axes(axis, mask) for axis, mask in zip(axes, m, strict=True))
        for m in modes
    ]
    caps = [F(axis["certificate"]["ratio"]) for axis in axes]
    maxima = [bounds([p[k] for p in worlds])[0] for k in (0, 1)]
    assert caps == maxima
    independent, minima = bounds(
        [
            {(i, j): a * b for i, a in left.items() for j, b in right.items()}
            for left, right in worlds
        ]
    )
    floors = {c: a / 2 for c, a in minima.items()}
    marginal = max(caps)
    midpoint = (independent + marginal) / 2
    assert (row["independent"], row["marginal"], row["midpoint"]) == tuple(
        map(str, (independent, marginal, midpoint))
    )
    targets = row["targets"]
    assert set(targets) == set(map(str, (marginal, midpoint, independent)))
    for tag, record in targets.items():
        r = F(tag)
        screen = record["refusal_budget"]
        verify_budget(worlds, caps, truth, floors, r, screen)
        if record["status"] == "feasible":
            assert screen is None
            d, _ = validate_policy(worlds, caps, truth, floors, r, record)
            validate_dual(worlds, caps, truth, floors, r, record["dual"], d)
            if r == independent:
                assert d == 0
        else:
            assert record["status"] == "infeasible" and r != independent
            validate_dual(worlds, caps, truth, floors, r, record["dual"], None)
    return (
        tuple(len(axis["labels"]) for axis in axes),
        tuple(modes),
        list(targets.values()),
        targets[str(midpoint)],
    )


def count(targets):
    feasible = sum(t["status"] == "feasible" for t in targets)
    screened = sum(t["refusal_budget"] is not None for t in targets)
    return dict(
        targets=len(targets),
        feasible=feasible,
        infeasible=len(targets) - feasible,
        screened=screened,
    )


def check(source, output):
    packages = json.loads(
        gzip.decompress((output / "retuned-odds-ci-policies.json.gz").read_bytes())
    )
    summary = json.loads((output / "retuned-odds-ci-results.json").read_bytes())
    totals, midpoints, layouts = [], [], set()
    repositories = Counter()
    modes_count = 0
    for packet, row in zip(sample(source), packages, strict=True):
        verified = verify_case(packet, row)
        if verified is not None:
            widths, modes, targets, mid = verified
            totals.extend(targets)
            midpoints.append(mid)
            modes_count += len(modes)
            layouts.add((widths, modes))
            repositories[packet["repo"]] += 1
    all_targets = count(totals)
    assert summary == dict(
        sampled=len(packages),
        scored=len(midpoints),
        modes=modes_count,
        distinct_layouts=len(layouts),
        by_repository=dict(repositories),
        all_targets=all_targets,
        midpoints=count(midpoints),
        gate=(
            len(midpoints) >= 40
            and all_targets["screened"] >= 10
            and all_targets["screened"] * 2 >= all_targets["infeasible"]
        ),
    )
    return summary | {"verified": True}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    if not __debug__:
        raise RuntimeError("enable assertions")
    print(json.dumps(check(args.source, args.output)))
