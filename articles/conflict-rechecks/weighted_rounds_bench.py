"""Held-out npm release replay for priced diagnostic batching."""

import argparse
from base64 import b64encode
from concurrent.futures import ThreadPoolExecutor
import gzip
from hashlib import sha256, sha512
from io import BytesIO
import json
from pathlib import Path, PurePosixPath
import tarfile
from urllib.parse import urlparse

from weighted_batches import BatchPlan, execute, optimal, sequential_bound
from weighted_bench import fetch
from weighted_rounds import execute_rounds, ordered_plan

PACKAGES = (
    ("lodash", "4.17.20", "4.17.21"),
    ("express", "4.19.2", "4.21.2"),
    ("semver", "7.6.2", "7.7.1"),
    ("axios", "1.7.7", "1.8.4"),
    ("chalk", "5.3.0", "5.4.1"),
    ("js-yaml", "4.1.0", "4.1.1"),
    ("zod", "3.23.8", "3.24.2"),
    ("yargs", "17.7.1", "17.7.2"),
    ("commander", "12.1.0", "13.1.0"),
    ("webpack", "5.94.0", "5.98.0"),
)
EXCLUDED = {
    "test",
    "tests",
    "spec",
    "fixtures",
    "docs",
    "benchmark",
    "benchmarks",
    "examples",
}


def release(root, name, version):
    metadata = f"https://registry.npmjs.org/{name}/{version}"
    saved = root / f"{name}-{version}.json"
    if not saved.exists():
        fetch(metadata, saved)
    document = json.loads(saved.read_bytes())
    assert document["name"] == name and document["version"] == version
    dist = document["dist"]
    parsed = urlparse(dist["tarball"])
    assert parsed.scheme == "https" and parsed.netloc == "registry.npmjs.org"
    path = root / f"{name}-{version}.tgz"

    def valid():
        if not path.exists():
            return False
        encoded = b64encode(sha512(path.read_bytes()).digest()).decode("ascii")
        return dist["integrity"] == "sha512-" + encoded

    if not valid():
        fetch(dist["tarball"], path)
    if not valid():
        raise ValueError(f"registry digest mismatch for {name}@{version}")
    return {
        "metadata": metadata,
        "name": name,
        "version": version,
        "tarball": dist["tarball"],
        "integrity": dist["integrity"],
        "file": path.name,
    }


def contents(path):
    out = {}
    with tarfile.open(
        fileobj=BytesIO(gzip.decompress(path.read_bytes())), mode="r:"
    ) as archive:
        for item in archive:
            p = PurePosixPath(item.name)
            if (
                not item.isfile()
                or not item.size
                or len(p.parts) < 2
                or p.parts[0] != "package"
                or ".." in p.parts
                or p.suffix not in {".js", ".cjs", ".mjs"}
                or EXCLUDED.intersection(x.casefold() for x in p.parts[1:])
            ):
                continue
            if item.name in out:
                raise ValueError(f"duplicate archive member {item.name}")
            with archive.extractfile(item) as source:
                out[item.name] = source.read()
    return out


def replay(files, costs, compare, errors, plan, run, *, stale=None, inject=False):
    n = len(costs)
    calls = extra = opened = bought = payload = 0

    def read_batch(keys):
        nonlocal calls, extra, opened, bought, payload
        calls += 1
        replies = []
        for i in keys:
            data = files[i][0 if i == stale else 1]
            verdict = sha256(data).hexdigest() != compare[i]
            assert verdict == (i == stale)
            flip = (
                inject
                and extra < errors
                and (opened == 0 or calls >= 2 or len(set(keys)) < len(keys))
            )
            extra += flip
            bought += costs[i]
            payload += len(data)
            opened += 1
            replies.append(int(verdict ^ flip))
        return replies

    answer = run(plan, n, errors, read_batch)
    expected = "extension" if stale is None else "old"
    assert answer.family == expected and answer.possible_old == (
        () if stale is None else (stale,)
    )
    assert extra == (errors if inject else 0)
    assert payload <= bought <= plan.worst_cost
    return {
        "stale": stale,
        "flips": extra,
        "rounds": calls,
        "reads": opened,
        "reserved": bought,
        "payload": payload,
    }


def evaluate(root, source):
    before, after = [contents(root / item["file"]) for item in source]
    names = [p for p in sorted(before.keys() & after) if before[p] != after[p]]
    pairs = [(before[p], after[p]) for p in names]
    costs = tuple(max(map(len, pair)) for pair in pairs)
    stamps = [tuple(sha256(x).hexdigest() for x in pair) for pair in pairs]
    files = [
        {"path": p, "size": list(map(len, data)), "sha256": digests, "price": cost}
        for p, data, digests, cost in zip(names, pairs, stamps, costs, strict=True)
    ]
    results = {}
    for errors in (1, 2):
        if not files:
            break
        fixed = BatchPlan((), (errors + 1) * sum(costs))
        two = optimal(costs, errors)
        ordered = {r: ordered_plan(costs, errors, r) for r in (2, 3, 4)}
        sequential = sequential_bound(costs, errors)
        holdout = {}
        for key, plan, engine, rounds in (
            ("exact2", two, execute, 2),
            ("ordered3", ordered[3], execute_rounds, 3),
        ):
            events = [
                replay(
                    pairs, costs, [s[1] for s in stamps], errors, plan, engine, stale=i
                )
                for i in range(len(names))
            ]
            events.extend(
                replay(
                    pairs,
                    costs,
                    [s[1] for s in stamps],
                    errors,
                    plan,
                    engine,
                    inject=corrupt,
                )
                for corrupt in (False, True)
            )
            assert max(r["rounds"] for r in events) <= rounds
            assert max(r["reserved"] for r in events) == plan.worst_cost
            holdout[key] = events
        results[str(errors)] = {
            "fixed": fixed.worst_cost,
            "exact2": two.worst_cost,
            "exact2_first": two.first,
            "ordered": {
                str(r): {"cost": p.worst_cost, "blocks": p.blocks, "tail": p.tail}
                for r, p in ordered.items()
            },
            "sequential": sequential,
            "replays": holdout,
        }
    return {"sources": source, "members": files, "results": results}


def summarize(packages):
    out = {}
    for label in ("1", "2"):
        valid = [
            row["results"][label]
            for row in packages.values()
            if label in row["results"]
        ]
        totals = {
            m: sum(r[m] for r in valid) for m in ("fixed", "exact2", "sequential")
        }
        for k in ("2", "3", "4"):
            totals["ordered" + k] = sum(r["ordered"][k]["cost"] for r in valid)
        diffs = [r["ordered"]["3"]["cost"] - r["exact2"] for r in valid]
        out[label] = {
            "comparable": len(valid),
            "less": sum(x < 0 for x in diffs),
            "equal": diffs.count(0),
            "more": sum(x > 0 for x in diffs),
            "totals": totals,
            "exact2_max_payload_sum": sum(
                max(a["payload"] for a in r["replays"]["exact2"]) for r in valid
            ),
            "ordered3_max_payload_sum": sum(
                max(a["payload"] for a in r["replays"]["ordered3"]) for r in valid
            ),
        }
    primary = out["1"]
    cost = primary["totals"]
    gate = (
        primary["comparable"] == len(PACKAGES)
        and primary["less"] >= 7
        and 100 * cost["ordered3"] <= 95 * cost["exact2"]
    )
    return {"by_allowance": out, "passed_primary_gate": gate}


def run(root):
    root.mkdir(parents=True, exist_ok=True)
    with ThreadPoolExecutor(max_workers=8) as pool:
        future = {
            name: [pool.submit(release, root, name, v) for v in (a, b)]
            for name, a, b in PACKAGES
        }
        sources = {name: [job.result() for job in fs] for name, fs in future.items()}
    records = {}
    for name, src in sources.items():
        records[name] = evaluate(root, src)
        print(name, len(records[name]["members"]), flush=True)
    return {"packages": records, "summary": summarize(records)}


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("cache", type=Path)
    p.add_argument("output", type=Path)
    args = p.parse_args()
    report = run(args.cache)
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report["summary"]))
