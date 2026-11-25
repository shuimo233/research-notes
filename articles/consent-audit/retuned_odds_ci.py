"""Replay refusal-budget screening on a preregistered sample of CI archives."""

import argparse
from collections import Counter
from fractions import Fraction
import gzip
from hashlib import sha1
import json
from pathlib import Path

from conclusion_replay_inquiry import parse
from denial_odds import distribution
from denial_odds_run import solve as single_policy
from joint_odds import focus, project, semantics
from public_optimality import PublicAudit
from retuned_odds import SERVICE, refusal_budget
from retuned_odds_run import solve
from selection_odds import patterns
from selection_protection import comparison

PIN = "38632c54456c76ff237bb8bf4cf66257ed6041e7"


def read(source):
    content = source.read_bytes()
    if sha1(f"blob {len(content)}\0".encode() + content).hexdigest() != PIN:
        raise ValueError("not the registered archive")
    packets = json.loads(gzip.decompress(content))
    counts = Counter()
    for p in sorted(packets, key=lambda p: (p["repo"], int(p["run"]), int(p["job"]))):
        counts[p["repo"]] += 1
        if counts[p["repo"]] <= 12:
            yield p


def select(packet):
    parsed = parse(packet["archive"])
    fibre = PublicAudit(*parsed, packet["certificate"]).fibre
    false_all = fibre
    labels = []
    for u, v in sorted({tuple(a[:2]) for a in packet["archive"]["targets"]}):
        low, high = -fibre[v][u], fibre[u][v]
        if low >= high:
            continue
        atom = [u, v, (low + high + 1) // 2]
        remaining = comparison(false_all, atom, False)
        if remaining is not None:
            labels.append(atom)
            false_all = remaining
        if len(labels) == 6:
            break
    return labels, fibre


def evaluate(packet):
    labels, fibre = select(packet)
    focus_views = focus([{"comparison": a} for a in labels])
    identity = {k: packet[k] for k in ("repo", "run", "job")}
    if not focus_views:
        return dict(**identity, status="one_or_no_views", labels=labels)
    masks, has_empty, _ = patterns(fibre, labels)
    assert has_empty
    modes = sorted(
        {tuple(project(mask, ids) for _, ids in focus_views) for mask in [0, *masks]}
    )
    views = []
    for side, (focus_event, ids) in enumerate(focus_views):
        cert = single_policy(len(ids), sorted({m[side] for m in modes} - {0}), SERVICE)
        views.append(dict(event=focus_event, labels=ids, certificate=cert))
    weights = [list(map(Fraction, a["certificate"]["weights"])) for a in views]
    worlds = [
        tuple(distribution(w, m, SERVICE) for w, m in zip(weights, mode, strict=True))
        for mode in modes
    ]
    floors, marginal, independent = semantics(worlds)
    caps = [Fraction(a["certificate"]["ratio"]) for a in views]
    label_floors = [Fraction(1, 2 * len(a["labels"])) for a in views]
    midpoint = (marginal + independent) / 2
    targets = {}
    for ratio in sorted({marginal, midpoint, independent}):
        screen = refusal_budget(worlds, caps, label_floors, floors, ratio)
        certificate = solve(worlds, caps, label_floors, floors, ratio)
        if screen is not None and certificate["status"] != "infeasible":
            raise ArithmeticError("the screen rejected a feasible policy")
        targets[str(ratio)] = certificate | {"refusal_budget": screen}
    assert targets[str(independent)]["status"] == "feasible"
    assert targets[str(independent)]["drift"] == "0"
    return dict(
        **identity,
        status="scored",
        labels=labels,
        views=views,
        modes=modes,
        targets=targets,
        midpoint=str(midpoint),
        marginal=str(marginal),
        independent=str(independent),
    )


def counts(results):
    fail = sum(p["status"] == "infeasible" for p in results)
    return dict(
        targets=len(results),
        feasible=len(results) - fail,
        infeasible=fail,
        screened=sum(p["refusal_budget"] is not None for p in results),
    )


def summarize(archive):
    scored = [p for p in archive if p["status"] == "scored"]
    all_targets = counts([t for p in scored for t in p["targets"].values()])
    return dict(
        sampled=len(archive),
        scored=len(scored),
        modes=sum(len(p["modes"]) for p in scored),
        distinct_layouts=len(
            {
                (
                    tuple(len(v["labels"]) for v in p["views"]),
                    tuple(map(tuple, p["modes"])),
                )
                for p in scored
            }
        ),
        by_repository=dict(Counter(p["repo"] for p in scored)),
        all_targets=all_targets,
        midpoints=counts([p["targets"][p["midpoint"]] for p in scored]),
        gate=len(scored) >= 40
        and all_targets["screened"] >= 10
        and 2 * all_targets["screened"] >= all_targets["infeasible"],
    )


def run(source, output):
    records = []
    for packet in read(source):
        try:
            records.append(evaluate(packet))
        except ArithmeticError as error:
            raise ArithmeticError(f"job {packet['job']}") from error
    summary = summarize(records)
    output.mkdir(parents=True, exist_ok=True)
    (output / "retuned-odds-ci-policies.json.gz").write_bytes(
        gzip.compress(
            json.dumps(records, separators=(",", ":"), ensure_ascii=True).encode(),
            mtime=0,
        )
    )
    (output / "retuned-odds-ci-results.json").write_text(
        json.dumps(summary, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    print(json.dumps(summary))


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("source", type=Path)
    p.add_argument("output", type=Path)
    a = p.parse_args()
    run(a.source, a.output)
