"""Replay all-window audit plans for multi-label public release catalogues."""

import argparse
from collections import Counter, defaultdict
from fractions import Fraction
import gzip
from hashlib import sha1, sha256
from itertools import permutations, product
import json
from math import prod
from pathlib import Path

from conclusion_replay_inquiry import parse
from incomparable_odds import WindowAudit
from multi_odds_run import SOURCES
from public_optimality import PublicAudit
from selection_odds import patterns


def read(path, domain):
    data = path.read_bytes()
    if sha1(f"blob {len(data)}\0".encode() + data).hexdigest() != SOURCES[domain]:
        raise ValueError("expected registered archive")
    ordered = sorted(
        json.loads(gzip.decompress(data)),
        key=lambda p: (p["repo"], int(p["run"]), int(p["job"])),
    )
    taken = Counter()
    for p in ordered:
        key = p["repo"] if domain == "CI" else domain
        taken[key] += 1
        if taken[key] <= (12 if domain == "CI" else 72):
            yield p


def labels_of(packet, width=4):
    fibre = PublicAudit(*parse(packet["archive"]), packet["certificate"]).fibre
    labels = []
    for u, v in sorted({tuple(x[:2]) for x in packet["archive"]["targets"]}):
        L, U = -fibre[v][u], fibre[u][v]
        if U - L < 2:
            continue
        h = (U - L - 1) // 3
        labels.extend(([v, u, -(U - h - 1)], [u, v, L + h + 1]))
        if len(labels) == 2 * width:
            break
    return labels, fibre


def weights(m):
    base, tilted = [], []
    for k in range(4):
        mask = (m >> (2 * k)) & 3
        if mask == 0:
            raise ValueError("the registered truth supports always permit an answer")
        if mask == 3:
            base.append({0: 4, 1: 2, 2: 2})
            tilted.append({0: 2, 1: 1, 2: 5})
        elif mask == 1:
            base.append({0: 4, 1: 4})
            tilted.append({0: 4, 1: 4})
        else:
            base.append({0: 4, 2: 4})
            tilted.append({0: 2, 2: 6})
    return {
        answer: prod(q[a] for q, a in zip(base, answer, strict=True))
        + prod(q[a] for q, a in zip(tilted, answer, strict=True))
        for answer in product(*base)
    }


def policy_audit(modes):
    audit = WindowAudit([weights(m) for m in modes])
    whole = prior = correct = Fraction(1)
    full_count = reduced = missed = missed_full = 0
    raw = sha256()
    sample = maximum = None
    nested = incomparable = 0
    for i, j in permutations(range(len(modes)), 2):
        lx, ly = audit.support[i], audit.support[j]
        common = [len(x & y) for x, y in zip(lx, ly, strict=True)]
        full_count += prod(1 + c for c in common)
        nested += sum(y < x and len(y) > 1 for x, y in zip(lx, ly, strict=True))
        incomparable += sum(
            not x <= y and not y <= x for x, y in zip(lx, ly, strict=True)
        )
        found, num, witness = audit.directed(i, j)
        old, _, _ = audit.directed(i, j, binary_heuristic=True)
        all_only, _, _ = audit.directed(i, j, (15,))
        assert old <= found and all_only <= found
        raw.update(f"{i},{j},{found}\n".encode())
        reduced += num
        if found > correct:
            correct = found
            maximum = dict(
                numerator=i, denominator=j, window=witness[0], message=list(witness[1])
            )
        whole = max(whole, all_only)
        prior = max(prior, old)
        missed += old < found
        missed_full += all_only < found
        if sample is None and old < found:
            sample = dict(
                numerator=i,
                denominator=j,
                window=witness[0],
                message=list(witness[1]),
                correct=str(found),
                heuristic=str(old),
            )
    return dict(
        odds=str(correct),
        heuristic_odds=str(prior),
        full_only_odds=str(whole),
        comparisons=full_count,
        retained=reduced,
        pair_digest=raw.hexdigest(),
        wrong_heuristic_pairs=missed,
        wrong_full_pairs=missed_full,
        reverse_nested_coordinates=nested,
        incomparable_coordinates=incomparable,
        witness=sample,
        maximum=maximum,
    )


def evaluate(domain, p, cache):
    labels, dbm = labels_of(p)
    fields = dict(
        domain=domain, repo=p["repo"], run=p["run"], job=p["job"], labels=labels
    )
    if len(labels) != 8:
        return fields | dict(status="fewer_than_four")
    modes, empty, _ = patterns(dbm, labels)
    assert not empty
    key = tuple(modes)
    if key not in cache:
        cache[key] = policy_audit(modes)
    return fields | dict(status="scored", modes=modes, **cache[key])


def summarize(records):
    totals = defaultdict(Counter)
    seen = defaultdict(set)
    for row in records:
        for k in ("all", row["domain"]):
            c = totals[k]
            c["sampled"] += 1
            if row["status"] == "scored":
                c["scored"] += 1
                seen[k].add(tuple(row["modes"]))
                c["worlds"] += len(row["modes"])
                for field in (
                    "comparisons",
                    "retained",
                    "wrong_heuristic_pairs",
                    "wrong_full_pairs",
                    "reverse_nested_coordinates",
                    "incomparable_coordinates",
                ):
                    c[field] += row[field]
                c["has_heuristic_miss"] += row["wrong_heuristic_pairs"] > 0
                c["has_full_miss"] += row["wrong_full_pairs"] > 0
                c["underestimated_by_heuristic"] += Fraction(
                    row["heuristic_odds"]
                ) < Fraction(row["odds"])
                c["underestimated_by_full"] += Fraction(
                    row["full_only_odds"]
                ) < Fraction(row["odds"])
    measures = {
        k: dict(v, distinct_mode_families=len(seen[k])) for k, v in totals.items()
    }
    a = totals["all"]
    return dict(
        results=measures,
        reduction=str(Fraction(a["comparisons"], a["retained"])),
        gate=a["scored"] >= 50
        and 2 * a["comparisons"] >= 3 * a["retained"]
        and a["has_heuristic_miss"] >= 10,
    )


def run(ci, bart, out):
    cache = {}
    records = [
        evaluate(k, p, cache)
        for k, file in (("CI", ci), ("BART", bart))
        for p in read(file, k)
    ]
    report = summarize(records)
    out.mkdir(parents=True, exist_ok=True)
    (out / "incomparable-odds-policies.json.gz").write_bytes(
        gzip.compress(
            json.dumps(records, separators=(",", ":"), ensure_ascii=True).encode(),
            mtime=0,
        )
    )
    (out / "incomparable-odds-results.json").write_text(
        json.dumps(report, indent=2) + "\n", encoding="utf-8", newline="\n"
    )
    print(json.dumps(report))


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("ci", type=Path)
    p.add_argument("bart", type=Path)
    p.add_argument("output", type=Path)
    a = p.parse_args()
    run(a.ci, a.bart, a.output)
