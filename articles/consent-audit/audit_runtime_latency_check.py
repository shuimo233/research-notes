"""Check the matched replay and derive all latency comparisons from nanoseconds."""

from collections import Counter, defaultdict
import csv
from fractions import Fraction as F
import gzip
from hashlib import sha1, sha256
from itertools import product
import json
from pathlib import Path
from statistics import median

MODES = (0, 16, 24, 32, 48, 64, 96, 128)
CASES = (0, 12, 24, 34, 48, 59)
ARMS = (
    "bucket_independent",
    "bucket_partition",
    "packed_independent",
    "packed_partition",
)
PANELS = "09efe9dbdb03c0826bfc884e6cc2228ebbd551b8"
PARTITIONS = "06cc9ac4fa4c04dff0b840475c5c0a34c3be5595"
GRAPH = "595bfd653973f8065c9e31cac909b5646f5cf4e0c8964c5c8683445b732f08fe"
TRACE = "audit-runtime-latency-trace.json.gz"
RESULTS = "audit-runtime-latency-results.json"


def locked(path, expected, normalize=False):
    raw = path.read_bytes()
    if normalize:
        raw = raw.replace(b"\r\n", b"\n")
    assert sha1(f"blob {len(raw)}\0".encode() + raw).hexdigest() == expected
    return raw


def load_records(ledger, plans):
    rows = defaultdict(list)
    for r in csv.DictReader(
        locked(ledger, PANELS, True).decode().splitlines(), delimiter="\t"
    ):
        i, j, k = (int(r[s]) for s in ("case", "world", "slot"))
        assert len(rows[i, j]) == k and 0 <= i < 60 and 0 <= j < 3 and 0 <= k < 8
        rows[i, j].append(r)
    assert set(rows) == set(product(range(60), range(3))) and all(
        len(v) == 8 for v in rows.values()
    )
    blocks = {}
    for r in json.loads(gzip.decompress(locked(plans, PARTITIONS))):
        if r["threshold"] == "0" and r["case"] in CASES:
            blocks[r["case"]] = r["new"]["blocks"]
    assert set(blocks) == set(CASES)
    return dict(rows), blocks


def expected(rows, modes):
    return b"".join(
        int(row[f"w{MODES[mode]}_{label}"], 16).to_bytes(4, "little")
        for row, mode in zip(rows, modes, strict=True)
        for label in "ENC"
    )


def semantic_order():
    for case, world, step in product(range(60), range(3), range(8)):
        yield case, world, [(case + slot + world + step) % 8 for slot in range(8)]


def exact_digest(rows):
    proof = sha256()
    for case, world, modes in semantic_order():
        proof.update(expected(rows[case, world], modes))
    return proof.hexdigest()


def process_cost(rows, modes):
    width = [
        max(int(row["length"]), MODES[i]) for row, i in zip(rows, modes, strict=True)
    ]
    return {
        "presets": len(set(modes)),
        "widths": len(set(width)),
        "tokens": sum(width),
        "squares": sum(w * w for w in width),
    }


def comparison(arm_a, arm_b):
    assert len(arm_a) == len(arm_b) and arm_a
    return {
        "paired_median_ratio": str(
            median([F(a, b) for a, b in zip(arm_a, arm_b, strict=True)])
        ),
        "p95_ratio": str(F(p95(arm_a), p95(arm_b))),
    }


def p95(items):
    return sorted(items)[(95 * len(items) + 99) // 100 - 1]


def managed_arm(groups, arm, condition):
    return [x["timing"][arm] for x in groups if condition(x)]


def summarize(ledger, plans, data):
    rows, by_case = load_records(ledger, plans)
    assert data["semantic"] == {
        "scores": 34560,
        "graph": GRAPH,
        "score_sha256": exact_digest(rows),
    }
    batches = data["batches"]
    assert len(batches) == 576
    for (rep, c, w), chunk in zip(
        product(range(2), CASES, range(3)),
        (batches[k : k + 16] for k in range(0, len(batches), 16)),
        strict=True,
    ):
        hist = {
            key: [Counter() for _ in range(8)] for key in ("independent", "partition")
        }
        work = {key: Counter() for key in hist}
        for t, row in enumerate(chunk):
            assert row["key"] == [rep, c, w, t]
            modes = row["routes"]
            assert set(modes) == set(hist)
            for schedule, route in modes.items():
                assert len(route) == 8 and all(
                    type(x) is int and 0 <= x < 8 for x in route
                )
                for i, mode in enumerate(route):
                    hist[schedule][i][mode] += 1
                measured = process_cost(rows[c, w], route)
                assert row["work"][schedule] == measured
                work[schedule].update(
                    {"tokens": measured["tokens"], "squares": measured["squares"]}
                )
            if t < 8:
                assert modes["independent"] == modes["partition"]
            else:
                assert all(
                    len({modes["partition"][i] for i in group}) == 1
                    for group in by_case[c]
                )
            assert set(row["timing"]) == set(ARMS)
            assert all(type(v) is int and v > 0 for v in row["timing"].values())
            order = list(ARMS)
            shift = (rep + c + w + t) % 4
            assert row["order"] == order[shift:] + order[:shift]
            assert row["digest"] == {
                kind: sha256(expected(rows[c, w], routes)).hexdigest()
                for kind, routes in modes.items()
            }
        assert all(h == {k: 2 for k in range(8)} for cts in hist.values() for h in cts)
        assert work["independent"] == work["partition"]

    outputs = []
    for r in range(2):
        chunk = [b for b in batches if b["key"][0] == r]
        assert len(chunk) == 288
        pairs = (
            ("bucket_route", "bucket_partition", "bucket_independent"),
            ("packed_route", "packed_partition", "packed_independent"),
            ("packed_for_independent", "packed_independent", "bucket_independent"),
            ("packed_for_partition", "packed_partition", "bucket_partition"),
        )
        views = {}
        for name, a, b in pairs:
            views[name] = {
                label: comparison(
                    managed_arm(chunk, a, sel), managed_arm(chunk, b, sel)
                )
                for label, sel in (
                    ("whole", lambda x: True),
                    ("common_half", lambda x: x["key"][-1] < 8),
                    ("different_half", lambda x: x["key"][-1] >= 8),
                )
            }
        counts = {}
        for schedule in ("independent", "partition"):
            counts[schedule] = {
                f"mean_{k}": str(
                    F(sum(x["work"][schedule][k] for x in chunk), len(chunk))
                )
                for k in ("presets", "widths", "tokens", "squares")
            }
        arm_times = {
            name: {
                "median_ns": str(median(F(x["timing"][name]) for x in chunk)),
                "p95_ns": p95([x["timing"][name] for x in chunk]),
            }
            for name in ARMS
        }
        outputs.append(
            {"rank": r, "timing": views, "work": counts, "absolute": arm_times}
        )
    passing = {}
    for name in (
        "bucket_route",
        "packed_route",
        "packed_for_independent",
        "packed_for_partition",
    ):
        passing[name] = all(
            F(o["timing"][name]["whole"]["paired_median_ratio"]) <= F(19, 20)
            and F(o["timing"][name]["whole"]["p95_ratio"]) <= F(21, 20)
            for o in outputs
        )
    return {
        "semantic": data["semantic"],
        "platform": data["platform"],
        "batches": 576,
        "measurements": 4 * 576,
        "rounds": outputs,
        "passes_latency_gate": passing,
    }


def verify(ledger, plans, folder):
    data = json.loads(gzip.decompress((folder / TRACE).read_bytes()))
    report = summarize(ledger, plans, data)
    assert report == json.loads((folder / RESULTS).read_bytes())
    print(
        json.dumps(
            {
                "verified": True,
                "measurements": report["measurements"],
                "passes_latency_gate": report["passes_latency_gate"],
            }
        )
    )


if __name__ == "__main__":
    import argparse

    cli = argparse.ArgumentParser(description=__doc__)
    for n in ("ledger", "plans", "folder"):
        cli.add_argument(n, type=Path)
    a = cli.parse_args()
    verify(a.ledger, a.plans, a.folder)
