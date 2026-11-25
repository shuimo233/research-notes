"""Frozen two-error replay on NOAA weather archives and BART schedules."""

import argparse
from collections import Counter, defaultdict
import gzip
from hashlib import sha256
from itertools import combinations
import json
from math import comb
from pathlib import Path

from interval_fault_cut import branches, classify, disjoint, inquire
from interval_fault_cut_run import EDGES, days
from interval_fault_delta import compile_two, label_ranges, signed_sums


BART = "a915f1052755d1ae96c785852f9d9ae40f676324403c1ff2f6112e7656048a0f"
LEDGER = "interval-fault-delta-ledger.json.gz"
RESULTS = "interval-fault-delta-results.json"
WEATHER_GROUPS = ((0, 1, 4), (2, 3, 5))


def is_connected(size, edges):
    graph = [[] for _ in range(size)]
    for u, v in edges:
        graph[u].append(v)
        graph[v].append(u)
    seen, todo = {0}, [0]
    for u in todo:
        for v in graph[u]:
            if v not in seen:
                seen.add(v)
                todo.append(v)
    return len(todo) == size


def cases(weather, bart):
    for panel, date, truth, bands in days(weather):
        yield ("weather", f"weather/{panel}/{date}", truth, bands, EDGES, 10)
    raw = bart.read_bytes()
    if sha256(raw).hexdigest() != BART:
        raise ValueError("unexpected BART fixtures")
    for row in json.loads(gzip.decompress(raw)):
        truth = [e["second"] for e in row["events"]]
        site = f"bart/{row['station']}/{row['date']}/{row['start']}"
        edges = tuple((s - 1, t - 1) for s, t in row["pairs"])
        if not is_connected(len(truth), edges):
            yield ("bart", site, None, None, None, None)
            continue
        bands = [(t - t % 300, t - t % 300 + 299) for t in truth]
        yield ("bart", site, truth, bands, edges, 180)


def injected(kind, key, truth, edges):
    b = sha256(key.encode()).digest()
    if kind == "weather":
        selected = [group[b[j] % 3] for j, group in enumerate(WEATHER_GROUPS)]
        magnitudes = (1, 5, 15)
    else:
        first = b[0] % len(edges)
        options = [i for i in range(len(edges)) if i != first]
        selected = [first, options[b[1] % len(options)]]
        magnitudes = (60, 180, 300)
    changes = {
        i: magnitudes[b[j + 2] % 3] * (1 if b[j + 4] % 2 else -1)
        for j, i in enumerate(selected)
    }
    reports = [
        (u, v, truth[v] - truth[u] + changes.get(i, 0))
        for i, (u, v) in enumerate(edges)
    ]
    return reports, sorted(changes.items())


def digest(sides):
    return sha256(json.dumps(sides, separators=(",", ":")).encode()).hexdigest()


def tight_targets(packed, truth, bands, reports, edges, threshold):
    states = packed.repair_coordinates()
    sample_faults, reference = next(iter(states.items()))
    residuals = [
        reports[i][2] - (reference[reports[i][1]] - reference[reports[i][0]])
        for i in sample_faults
    ]
    envelope = signed_sums(residuals)
    pairs = list(combinations(range(len(bands)), 2))
    maximum = 0
    for u, v in pairs:
        attainable = packed.values(u, v, ignore_intervals=True)
        maximum = max(len(attainable), maximum)
        assert attainable <= {reference[v] - reference[u] + d for d in envelope}
    diagnoses = {(u, v) for u, v in pairs if len(packed.values(u, v)) == len(states)}
    records = []
    for s, t in edges:
        probes = [q for q in pairs if q != tuple(sorted((s, t)))]
        options = [
            label_ranges(packed.probe_labels(s, t, threshold, u, v)) for u, v in probes
        ]
        flags = [flag in packed.labels(s, t, threshold) for flag in (False, True)]
        relative = [
            flag in packed.labels(s, t, threshold, ignore_intervals=True)
            for flag in (False, True)
        ]
        records.append(
            target_record(
                s,
                t,
                threshold,
                truth,
                flags,
                relative,
                options,
                probes,
                bool(diagnoses.intersection(probes)),
            )
        )
    return records, maximum, len(states), sorted(sample_faults)


def loose_targets(truth, bands, reports, edges, threshold):
    calibrated = list(branches(len(truth), bands, reports, 2))
    unbounded = list(branches(len(truth), None, reports, 2))
    pairs = list(combinations(range(len(bands)), 2))
    records = []
    for s, t in edges:
        probes = [q for q in pairs if q != tuple(sorted((s, t)))]
        result = inquire(calibrated, s, t, threshold, probes)
        flags = [entry[0] is not None for entry in result]
        relative = list(classify(unbounded, s, t, threshold))
        options = list(zip(result[0][1], result[1][1], strict=True))
        records.append(
            target_record(
                s, t, threshold, truth, flags, relative, options, probes, None
            )
        )
    return records


def target_record(s, t, threshold, truth, flags, relative, options, probes, identifies):
    found = (
        next((i for i, (no, yes) in enumerate(options) if disjoint(no, yes)), None)
        if all(flags)
        else None
    )
    actual = truth[t] - truth[s] >= threshold
    assert flags[actual] and relative[actual]
    if found is not None:
        u, v = probes[found]
        revealed = truth[v] - truth[u]
        possible = [any(a <= revealed <= b for a, b in side) for side in options[found]]
        assert possible == [not actual, actual]
    return [flags, relative, found, identifies, digest(options)]


def replay(kind, key, truth, bands, edges, threshold):
    if truth is None:
        return {"id": key, "excluded": True}
    reports, changes = injected(kind, key, truth, edges)
    packed = compile_two(bands, reports)
    assert packed.minimum <= 2
    if packed.minimum == 2:
        targets, maximum, states, reference = tight_targets(
            packed, truth, bands, reports, edges, threshold
        )
    else:
        targets = loose_targets(truth, bands, reports, edges, threshold)
        maximum = states = reference = None
    m = len(edges)
    return {
        "id": key,
        "errors": changes,
        "minimum": packed.minimum,
        "cycle": list(packed.cycle),
        "branches": len(packed.paths),
        "graph_branches": len(packed.graph_paths),
        "pairs_enumerated_by_oracle": 1 + m + comb(m, 2),
        "maximum_value_support": maximum,
        "distinct_banded_repairs": states,
        "reference_faults": reference,
        "targets": targets,
    }


def summarize(records):
    groups = defaultdict(Counter)
    max_cycle, max_support = 0, 0
    for r in records:
        source = r["id"].split("/")[0]
        if r.get("excluded"):
            groups[source]["disconnected"] += 1
            continue
        mode = "tight" if r["minimum"] == 2 else "loose"
        max_cycle = max(len(r["cycle"]), max_cycle)
        max_support = max(r["maximum_value_support"] or 0, max_support)
        for group in [source, source + "-" + mode, mode]:
            c = groups[group]
            c["archives"] += 1
            c["graph_cycle_branches"] += len(r["cycle"])
            c["band_feasible_branches"] += r["branches"]
            c["oracle_deletion_sets"] += r["pairs_enumerated_by_oracle"]
            c["largest_cycle"] = max(c["largest_cycle"], len(r["cycle"]))
            c["maximum_value_support"] = max(
                c["maximum_value_support"], r["maximum_value_support"] or 0
            )
            for flags, relative, query, identifies, _ in r["targets"]:
                c["tasks"] += 1
                c["graph_decided"] += sum(relative) == 1
                c["joint_decided"] += sum(flags) == 1
                c["ambiguous"] += all(flags)
                c["guaranteed_query"] += query is not None
                c["guaranteed_without_identifying"] += (
                    query is not None and identifies is False
                )
    tight = groups["tight"]
    return {
        "groups": dict(sorted(groups.items())),
        "largest_cycle": max_cycle,
        "maximum_value_support": max_support,
        "utility_gate": (
            tight["archives"] >= 300
            and tight["ambiguous"] >= 50
            and 10 * tight["guaranteed_query"] >= tight["ambiguous"]
        ),
    }


def run(weather, bart, output):
    records = [replay(*case) for case in cases(weather, bart)]
    summary = summarize(records)
    output.mkdir(parents=True, exist_ok=True)
    (output / LEDGER).write_bytes(
        gzip.compress(json.dumps(records, separators=(",", ":")).encode(), mtime=0)
    )
    (output / RESULTS).write_text(
        json.dumps(summary, indent=2) + "\n", encoding="utf-8", newline="\n"
    )
    return summary


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    for opt in ("weather", "bart", "output"):
        p.add_argument(opt, type=Path)
    opts = p.parse_args()
    report = run(opts.weather, opts.bart, opts.output)
    print(json.dumps(report))
