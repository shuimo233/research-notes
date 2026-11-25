"""Replay the preregistered NOAA archive fault exercise."""

import argparse
from collections import Counter, defaultdict
import csv
import gzip
from hashlib import sha256
from itertools import combinations
import json
from math import inf
from pathlib import Path

from interval_fault_cut import (
    branches,
    classify,
    clean_fault_count,
    closure,
    disjoint,
    inquire,
)


PANELS = {
    "california": ("23234", "23230", "23293", "23232", "23213"),
    "new_york": ("14732", "94789", "14734", "94741", "13739"),
}
EDGES = ((0, 1), (0, 2), (0, 3), (0, 4), (1, 2), (3, 4))
PAIRS = tuple(combinations(range(5), 2))
SNAPSHOT = "c9f41b70deffbfd5a3b464a086078bbc931c97dd2da5e1999a79dc0366c118fa"
LEDGER = "interval-fault-cut-ledger.json.gz"
RESULTS = "interval-fault-cut-results.json"


def days(path):
    raw = path.read_bytes()
    if sha256(raw).hexdigest() != SNAPSHOT:
        raise ValueError("unexpected source snapshot")
    months = defaultdict(Counter)
    by_day = defaultdict(dict)
    for row in csv.DictReader(gzip.decompress(raw).decode("ascii").splitlines()):
        station, stamp, value = row["station"][6:], row["date"], int(row["tmax_tenths"])
        if stamp < "2018":
            months[station, stamp[5:7]][value] += 1
        elif stamp.startswith("2025"):
            by_day[stamp][station] = value
    base = {}
    for key, histogram in months.items():
        remaining = (sum(histogram.values()) + 1) // 2
        for value, count in sorted(histogram.items()):
            remaining -= count
            if remaining <= 0:
                base[key] = value
                break
    for region, ids in PANELS.items():
        for stamp, readings in sorted(by_day.items()):
            if all(i in readings for i in ids):
                actual = tuple(readings[i] for i in ids)
                anchor = [base[i, stamp[5:7]] for i in ids]
                starts = [
                    a + 20 * ((x - a) // 20)
                    for a, x in zip(anchor, actual, strict=True)
                ]
                yield region, stamp, actual, [(x, x + 19) for x in starts]


def replay(region, stamp, actual, intervals, injected):
    reports = [(u, v, actual[v] - actual[u]) for u, v in EDGES]
    fault = None
    if injected:
        digest = sha256(f"{region}/{stamp}".encode()).digest()
        i = digest[0] % len(EDGES)
        offset = (1, 5, 15)[digest[2] % 3] * (1 if digest[1] % 2 else -1)
        u, v, value = reports[i]
        reports[i] = (u, v, value + offset)
        fault = [i, offset]
    dbms = list(branches(5, intervals, reports, 1))
    unbounded = list(branches(5, None, reports, 1))
    only_intervals = [closure(5, intervals, ())]
    base = closure(5, intervals, reports)
    targets = []
    for source, target in EDGES:
        probes = [p for p in PAIRS if p != (source, target)]
        outcomes = inquire(dbms, source, target, 10, probes)
        flags = [x[0] is not None for x in outcomes]
        # Ambiguity may survive verification of the queried numeric difference.
        choice = (
            next(
                (
                    i
                    for i, (a, b) in enumerate(
                        zip(outcomes[0][1], outcomes[1][1], strict=True)
                    )
                    if disjoint(a, b)
                ),
                None,
            )
            if all(flags)
            else None
        )
        for is_true, (witness, _) in enumerate(outcomes):
            if witness is not None:
                assert (
                    sum(witness[v] - witness[u] != delta for u, v, delta in reports)
                    <= 1
                )
                assert all(
                    a <= value <= b
                    for value, (a, b) in zip(witness, intervals, strict=True)
                )
                assert (witness[target] - witness[source] >= 10) == is_true
        actual_label = actual[target] - actual[source] >= 10
        assert flags[actual_label]
        if choice is not None:
            u, v = probes[choice]
            queried = actual[v] - actual[u]
            after = [
                any(a <= queried <= b for a, b in outcome[1][choice])
                for outcome in outcomes
            ]
            assert after == [not actual_label, actual_label]
        cut = None
        if base is not None:
            reference = base[5][:5]
            edges = [(u, v, 1) for u, v in EDGES]
            cut = [
                clean_fault_count(reference, intervals, edges, target, source, -9),
                clean_fault_count(reference, intervals, edges, source, target, 10),
            ]
            cut = [None if x == inf else x for x in cut]
        targets.append(
            {
                "interval": list(classify(only_intervals, source, target, 10)),
                "relative": list(classify(unbounded, source, target, 10)),
                "witnesses": [x[0] for x in outcomes],
                "ranges": [x[1] for x in outcomes],
                "query": choice,
                "cut": cut,
            }
        )
    return {"panel": region, "date": stamp, "injection": fault, "targets": targets}


def summarize(rows):
    counts = defaultdict(Counter)
    for row in rows:
        fault = row["injection"]
        kind = "injected" if fault else "clean"
        keys = [kind, row["panel"] + "-" + kind]
        if fault:
            keys.append(f"offset-{abs(fault[1])}")
        for target in row["targets"]:
            joint = sum(w is not None for w in target["witnesses"]) == 1
            for k in keys:
                c = counts[k]
                c["tasks"] += 1
                c["interval_only"] += sum(target["interval"]) == 1
                c["relative_only"] += sum(target["relative"]) == 1
                c["joint"] += joint
                c["joint_ambiguous"] += not joint
                c["guaranteed_queries"] += target["query"] is not None
                c["cut_targets"] += target["cut"] is not None
    inj = counts["injected"]
    gain = inj["joint"] - max(inj["relative_only"], inj["interval_only"])
    return {
        "counts": dict(sorted(counts.items())),
        "passes": {
            "joint": 20 * gain >= inj["tasks"],
            "cross_check": inj["joint_ambiguous"] >= 50
            and 10 * inj["guaranteed_queries"] >= inj["joint_ambiguous"],
        },
    }


def run(snapshot, output):
    records = [
        replay(region, stamp, actual, intervals, injected)
        for region, stamp, actual, intervals in days(snapshot)
        for injected in (False, True)
    ]
    result = summarize(records)
    output.mkdir(parents=True, exist_ok=True)
    (output / LEDGER).write_bytes(
        gzip.compress(json.dumps(records, separators=(",", ":")).encode(), mtime=0)
    )
    (output / RESULTS).write_text(
        json.dumps(result, indent=2) + "\n", encoding="utf-8", newline="\n"
    )
    return result


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("snapshot", type=Path)
    p.add_argument("output", type=Path)
    args = p.parse_args()
    result = run(args.snapshot, args.output)
    print(json.dumps({k: result["counts"][k] for k in ("clean", "injected")}))
    print(json.dumps(result["passes"]))
