"""Compile exact-reading certificates for the registered GitHub Actions study."""

import argparse
from collections import Counter, defaultdict
import gzip
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from conclusion_replay import closure, interval, necessary
from slack_certificate import (
    Cover,
    claims,
    classifications,
    minimal_rows,
    reduced_slack,
    reverse_delete,
    rows_for_claims,
    sequential,
    verify_report,
    visible,
)


NODE_LIMIT = 50_000


def archive_for(row):
    steps = row["steps"]
    truth = (0, *(t for _, a, b in steps for t in (a, b)))
    n = len(truth)
    bands = [(t // 60 * 60, t // 60 * 60 + 59) for t in truth[1:]]
    work = [(u, u + 1) for u in range(1, n, 2)]
    idle = [(u, u + 1) for u in range(2, n - 1, 2)]
    pairs = [(1, n - 1), *work, *idle]
    before = [
        (u, v, cuts)
        for (u, v), cuts in zip(
            pairs,
            [
                (0, 60, 600),
                *([(0, 1, 10, 60, 300)] * len(work)),
                *([(0, 1, 10)] * len(idle)),
            ],
            strict=True,
        )
    ]
    after = [
        (u, v, cuts)
        for (u, v), cuts in zip(
            pairs,
            [
                (30, 120, 300, 900),
                *([(1, 5, 30, 120)] * len(work)),
                *([(-1, 0, 2, 5)] * len(idle)),
            ],
            strict=True,
        )
    ]
    cold = closure(bands)
    archived = []
    for (u, v, cuts), k in zip(before, classifications(before, truth), strict=True):
        lo, hi = interval(cold, u, v)
        archived.append(
            (
                u,
                v,
                max(lo, cuts[k - 1]) if k else lo,
                min(hi, cuts[k] - 1) if k < len(cuts) else hi,
            )
        )
    return truth, bands, archived, after


def tasks(row):
    truth, bands, archived, after = archive_for(row)
    return truth, closure(bands, archived), after


def assess(row):
    truth, zone, targets = tasks(row)
    n = len(truth)
    labels = classifications(targets, truth)
    slack = reduced_slack(zone, truth)
    groups = [
        rows_for_claims(zone, slack, truth, claims([target], [k]))
        for target, k in zip(targets, labels, strict=True)
    ]
    raw = set().union(*groups)
    rows = minimal_rows(raw)
    cover = Cover(rows, n)
    fixed = necessary(zone, targets)
    seq = sequential(groups, n)
    rev = reverse_delete(rows, fixed)
    greedy = cover.greedy()
    optimum, lower, nodes, done = cover.minimum((greedy, rev, seq), NODE_LIMIT)
    paths = dict(
        all=tuple(range(1, n)),
        fixed=fixed,
        sequential=seq,
        reverse=rev,
        greedy=greedy,
        optimum=optimum,
    )
    for path in paths.values():
        proved = visible(path)
        assert all(proved & r for r in raw)
        verify_report(zone, targets, labels, [(i, truth[i]) for i in path])
    assert lower <= len(optimum)
    return dict(
        repo=row["repo"],
        run=row["run"],
        job=row["job"],
        timepoints=n - 1,
        labels=labels,
        paths=paths,
        raw_rows=len(raw),
        minimal_rows=len(rows),
        lower=lower,
        nodes=nodes,
        solved=done,
    )


def run(fixtures, output):
    rows = json.loads(gzip.decompress(fixtures.read_bytes()))
    results = defaultdict(Counter)
    ledger = []
    for fixture in rows:
        row = assess(fixture)
        ledger.append(row)
        for name in (row["repo"], "total"):
            c = results[name]
            c["jobs"] += 1
            c["labels"] += len(row["labels"])
            c["solved"] += row["solved"]
            c["lower"] += row["lower"]
            c["nodes"] += row["nodes"]
            c["raw_rows"] += row["raw_rows"]
            c["minimal_rows"] += row["minimal_rows"]
            c["max_timepoints"] = max(c["max_timepoints"], row["timepoints"])
            c["max_rows"] = max(c["max_rows"], row["minimal_rows"])
            c["max_nodes"] = max(c["max_nodes"], row["nodes"])
            c.update({k: len(p) for k, p in row["paths"].items()})
            if row["solved"]:
                c["solved_greedy"] += len(row["paths"]["greedy"])
                c["solved_optimum"] += len(row["paths"]["optimum"])
    c = results["total"]
    gates = dict(
        count=c["jobs"] >= 200,
        greedy_fixed=c["fixed"] > 0 and 10 * c["greedy"] <= 9 * c["fixed"],
        optimum_best=c["reverse"] > 0
        and c["sequential"] > 0
        and 100 * c["optimum"] <= 97 * min(c["reverse"], c["sequential"]),
        solved=100 * c["solved"] >= 99 * c["jobs"],
        greedy_optimum=100 * c["solved_greedy"] <= 105 * c["solved_optimum"],
    )
    report = dict(
        by_source=results, gates=gates, gate=all(gates.values()), node_limit=NODE_LIMIT
    )
    output.mkdir(parents=True, exist_ok=False)
    content = "".join(
        json.dumps(row, separators=(",", ":")) + "\n" for row in ledger
    ).encode()
    (output / "slack-certificate-ledger.jsonl.gz").write_bytes(
        gzip.compress(content, mtime=0)
    )
    (output / "slack-certificate-results.json").write_bytes(
        (json.dumps(report, indent=2) + "\n").encode()
    )
    return report


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("fixtures", type=Path)
    p.add_argument("output", type=Path)
    a = p.parse_args()
    if not __debug__:
        raise RuntimeError("enable assertions")
    print(json.dumps(run(a.fixtures, a.output), indent=2))
