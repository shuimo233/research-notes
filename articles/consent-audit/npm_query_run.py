"""Replay frozen npm version reads using independent uniform release-band priors."""

import argparse
from collections import Counter, defaultdict
from fractions import Fraction as Q
import gzip
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from npm_query import VersionInquiry


def tasks(path):
    return json.loads(gzip.decompress(path.read_bytes()))


def run(path, out):
    report = defaultdict(Counter)
    ledger = []
    for task in tasks(path):
        source = task["repo"]
        case = VersionInquiry(task)
        case.verify_projection()
        raw = sum(map(len, case.raw.values()))
        quotient = sum(len(set(m.values())) for m in case.representative.values())
        truth = {r["id"]: r["actual"] for r in task["vertices"]}
        actual = sorted(
            (u, v, grid[truth[e[0]], truth[e[1]]])
            for e, arcs in case.by_pair.items()
            for u, v, grid in arcs
        )
        required = len(case.service.pending(case.service.free))
        row = dict(
            repo=source,
            center=task["center"],
            raw_values=raw,
            equivalence_classes=quotient,
            variable_relations=required,
            labels=actual,
        )
        for group in (source, "total"):
            c = report[group]
            c["inspected_tasks"] += 1
            c["raw_values"] += raw
            c["equivalence_classes"] += quotient
            c["audited_directed_edges"] += len(task["relations"])
            c["scored"] += bool(required)
        if required:
            planner = case.batch
            budget = planner.optimum(planner.counts, case.initial_forced)[0]
            initial, fixed_budget = planner.fixed_cover(case.initial_forced)
            oracle = case.service.certificate(case.state(truth))
            paths = {}
            for mode in ("fixed", "greedy", "optimal"):
                path, labels = case.replay(truth.__getitem__, mode)
                assert labels == actual and len(path) >= len(oracle)
                paths[mode] = path
            assert paths["fixed"][: len(initial)] == [planner.names[i] for i in initial]
            counts = {
                "all_reads": sum(len(xs) > 1 for xs in case.raw.values()),
                "oracle": len(oracle),
                **{mode: len(path) for mode, path in paths.items()},
            }
            for group in (source, "total"):
                report[group].update(counts)
                report[group].update(
                    fixed_first_phase=len(initial),
                    fixed_followup=len(paths["fixed"]) - len(initial),
                    greedy_followup=len(paths["greedy"]) - 1,
                    optimal_followup=len(paths["optimal"]) - 1,
                )
            row.update(
                paths=paths,
                oracle=oracle,
                expected=str(budget),
                fixed_expected=str(fixed_budget),
                fixed_initial=len(initial),
            )
        else:
            trace, answers = case.replay(truth.__getitem__)
            assert not trace and answers == actual
        ledger.append(row)
    total = report["total"]
    result = dict(
        by_source=report,
        gate=total["scored"] >= 50
        and total["optimal"] < total["greedy"]
        and 200 * (total["fixed"] - total["optimal"]) >= total["fixed"],
    )
    result["fitted_expected_total"] = {
        field: round(float(sum(Q(r[field]) for r in ledger if field in r)), 8)
        for field in ("expected", "fixed_expected")
    }
    out.mkdir(parents=True, exist_ok=False)
    raw = "".join(json.dumps(r, separators=(",", ":")) + "\n" for r in ledger)
    (out / "npm-query-ledger.jsonl.gz").write_bytes(
        gzip.compress(raw.encode(), mtime=0)
    )
    (out / "npm-query-results.json").write_text(
        json.dumps(result, indent=2) + "\n", encoding="utf-8", newline="\n"
    )
    return result


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("fixtures", type=Path)
    p.add_argument("output", type=Path)
    a = p.parse_args()
    if not __debug__:
        raise RuntimeError("enable assertions")
    print(json.dumps(run(a.fixtures, a.output), indent=2))
