"""Independent component-coordinate and small-world checks for archive records."""

from collections import Counter, defaultdict
import csv
import gzip
from hashlib import sha256
from itertools import combinations, product
import json
from pathlib import Path
from random import Random
import sys


PANELS = {
    "california": tuple(
        "USW000" + x for x in ("23234", "23230", "23293", "23232", "23213")
    ),
    "new_york": tuple(
        "USW000" + x for x in ("14732", "94789", "14734", "94741", "13739")
    ),
}
EDGES = ((0, 1), (0, 2), (0, 3), (0, 4), (1, 2), (3, 4))
PAIRS = tuple(combinations(range(5), 2))
SNAPSHOT = "c9f41b70deffbfd5a3b464a086078bbc931c97dd2da5e1999a79dc0366c118fa"


def components(n, intervals, reports, dropped):
    adjacency = [[] for _ in range(n)]
    for i, (u, v, delta) in enumerate(reports):
        if i not in dropped:
            adjacency[u].append((v, delta))
            adjacency[v].append((u, -delta))
    id_of, offset = [None] * n, [None] * n
    limits = []
    for root in range(n):
        if id_of[root] is not None:
            continue
        tag = len(limits)
        id_of[root], offset[root] = tag, 0
        queue = [root]
        for i in queue:
            for j, delta in adjacency[i]:
                implied = offset[i] + delta
                if id_of[j] is None:
                    id_of[j], offset[j] = tag, implied
                    queue.append(j)
                elif implied != offset[j]:
                    return None
        if intervals is None:
            limits.append(None)
            continue
        low = max(intervals[i][0] - offset[i] for i in queue)
        high = min(intervals[i][1] - offset[i] for i in queue)
        if low > high:
            return None
        limits.append((low, high))
    return id_of, offset, limits


def source_days(path):
    assert sha256(path.read_bytes()).hexdigest() == SNAPSHOT
    reference, daily = defaultdict(list), defaultdict(dict)
    with gzip.open(path, "rt", encoding="ascii", newline="") as stream:
        for row in csv.DictReader(stream):
            sid, date, x = row["station"], row["date"], int(row["tmax_tenths"])
            if date < "2018":
                reference[sid, date[5:7]].append(x)
            elif date[:4] == "2025":
                assert sid not in daily[date]
                daily[date][sid] = x
    medians = {k: sorted(xs)[(len(xs) - 1) // 2] for k, xs in reference.items()}
    for panel, ids in PANELS.items():
        for date, xs in sorted(daily.items()):
            if set(ids) <= xs.keys():
                truth = tuple(xs[i] for i in ids)
                base = tuple(medians[i, date[5:7]] for i in ids)
                lower = tuple(
                    x - ((x - m) % 20) for x, m in zip(truth, base, strict=True)
                )
                yield panel, date, truth, tuple((x, x + 19) for x in lower)


def cut_oracle(intervals, reports):
    n = len(intervals)
    results = [[None, None] for _ in EDGES]
    for cost in range(len(reports) + 1):
        for erased in combinations(range(len(reports)), cost):
            feasible = components(n, intervals, reports, erased)
            if feasible is None:
                continue
            tags, offset, limits = feasible
            for (u, v), pair in zip(EDGES, results, strict=True):
                lo = hi = offset[v] - offset[u]
                if tags[u] != tags[v]:
                    a, b = limits[tags[u]]
                    c, d = limits[tags[v]]
                    lo += c - b
                    hi += d - a
                if lo < 10 and pair[0] is None:
                    pair[0] = cost
                if hi >= 10 and pair[1] is None:
                    pair[1] = cost
        if all(None not in pair for pair in results):
            break
    return results


def expand(ranges):
    values = {x for lo, hi in ranges for x in range(lo, hi + 1)}
    assert len(values) == sum(hi - lo + 1 for lo, hi in ranges)
    assert all(a <= b for a, b in ranges)
    assert all(a[1] + 1 < b[0] for a, b in zip(ranges, ranges[1:]))
    return values


def audit(path, output):
    ledger = json.loads(
        gzip.decompress((output / "interval-fault-cut-ledger.json.gz").read_bytes())
    )
    expected_rows = (
        (panel, date, actual, bands, noisy)
        for panel, date, actual, bands in source_days(path)
        for noisy in (False, True)
    )
    by_group = defaultdict(Counter)
    for row, (panel, date, actual, bands, noisy) in zip(
        ledger, expected_rows, strict=True
    ):
        assert (row["panel"], row["date"]) == (panel, date)
        reports = [(a, b, actual[b] - actual[a]) for a, b in EDGES]
        expected_fault = None
        if noisy:
            x, y, z, *_ = sha256((panel + "/" + date).encode()).digest()
            i = x % 6
            shift = [1, 5, 15][z % 3] * [-1, 1][y % 2]
            a, b, v = reports[i]
            reports[i] = (a, b, v + shift)
            expected_fault = [i, shift]
        assert row["injection"] == expected_fault
        states, offsets_without_bands = set(), set()
        for i in range(6):
            relative = components(5, None, reports, {i})
            if relative is None:
                continue
            tags, offset, _ = relative
            assert tags == [0] * 5
            offsets_without_bands.add(tuple(offset))
            for shift in range(
                max(a - v for (a, _), v in zip(bands, offset, strict=True)),
                min(b - v for (_, b), v in zip(bands, offset, strict=True)) + 1,
            ):
                states.add(tuple(v + shift for v in offset))
        assert actual in states
        costs = cut_oracle(bands, reports) if not noisy else [None] * 6
        kind = "injected" if noisy else "clean"
        groups = [kind, panel + "-" + kind]
        if noisy:
            groups.append(f"offset-{abs(expected_fault[1])}")
        for result, (s, t), cost in zip(row["targets"], EDGES, costs, strict=True):
            assert result["cut"] == cost
            probes = [p for p in PAIRS if p != (s, t)]
            models = [
                {x for x in states if (x[t] - x[s] >= 10) == flag}
                for flag in (False, True)
            ]
            flags = [bool(m) for m in models]
            interval_labels = [
                bands[t][0] - bands[s][1] < 10,
                bands[t][1] - bands[s][0] >= 10,
            ]
            relative_labels = [
                any((x[t] - x[s] >= 10) == flag for x in offsets_without_bands)
                for flag in (False, True)
            ]
            assert result["interval"] == interval_labels
            assert result["relative"] == relative_labels
            for i, witness in enumerate(result["witnesses"]):
                assert (witness is not None) == flags[i]
                if witness is not None:
                    assert tuple(witness) in models[i]
            sets = [[{x[b] - x[a] for x in m} for a, b in probes] for m in models]
            assert len(result["ranges"]) == 2
            for label in range(2):
                for saved, want in zip(
                    result["ranges"][label], sets[label], strict=True
                ):
                    assert expand(saved) == want
            decisive = [i for i in range(len(probes)) if not (sets[0][i] & sets[1][i])]
            choice = decisive[0] if all(flags) and decisive else None
            assert result["query"] == choice
            if choice is not None:
                u, v = probes[choice]
                answer = actual[v] - actual[u]
                assert [answer in m[choice] for m in sets] == [
                    actual[t] - actual[s] < 10,
                    actual[t] - actual[s] >= 10,
                ]
            for key in groups:
                c = by_group[key]
                c["tasks"] += 1
                c["interval_only"] += sum(interval_labels) == 1
                c["relative_only"] += sum(relative_labels) == 1
                c["joint"] += sum(flags) == 1
                c["joint_ambiguous"] += all(flags)
                c["guaranteed_queries"] += choice is not None
                c["cut_targets"] += cost is not None
    summary = json.loads((output / "interval-fault-cut-results.json").read_bytes())
    assert by_group == summary["counts"]
    inj = by_group["injected"]
    assert summary["passes"] == {
        "joint": (inj["joint"] - max(inj["relative_only"], inj["interval_only"])) * 20
        >= inj["tasks"],
        "cross_check": inj["joint_ambiguous"] >= 50
        and 10 * inj["guaranteed_queries"] >= inj["joint_ambiguous"],
    }
    return len(ledger), sum(by_group[k]["tasks"] for k in ("injected", "clean"))


def small_worlds():
    from interval_fault_cut import branches, clean_fault_count, inquire

    rng = Random(546784)
    attempts = 0
    for _ in range(130):
        n = rng.randrange(2, 6)
        intervals = [(rng.randint(-2, 0), rng.randint(0, 3)) for _ in range(n)]
        worlds = list(product(*(range(a, b + 1) for a, b in intervals)))
        reference = rng.choice(worlds)
        edges = [
            (u, v, rng.randint(1, 4))
            for u, v in combinations(range(n), 2)
            if rng.randrange(3) != 0
        ]
        s, t = rng.sample(range(n), 2)
        limit = rng.randint(-4, 5)
        probes = list(combinations(range(n), 2))
        for u, v, threshold in ((s, t, limit), (t, s, 1 - limit)):
            want = min(
                (
                    sum(
                        w
                        for a, b, w in edges
                        if x[b] - x[a] != reference[b] - reference[a]
                    )
                    for x in worlds
                    if x[v] - x[u] >= threshold
                ),
                default=float("inf"),
            )
            assert (
                clean_fault_count(reference, intervals, edges, u, v, threshold) == want
            )
            attempts += 1
        reports = [
            (u, v, reference[v] - reference[u] + rng.choice([0, 0, 0, -1, 2]))
            for u, v, _ in edges
        ]
        for budget in range(3):
            valid = [
                x
                for x in worlds
                if sum(x[v] - x[u] != d for u, v, d in reports) <= budget
            ]
            side = inquire(
                list(branches(n, intervals, reports, budget)), s, t, limit, probes
            )
            for flag, (witness, ranges) in enumerate(side):
                subset = [x for x in valid if (x[t] - x[s] >= limit) == flag]
                assert (witness is not None) == bool(subset)
                if subset:
                    assert tuple(witness) in subset
                for (u, v), ranges_for_probe in zip(probes, ranges, strict=True):
                    assert expand(ranges_for_probe) == {x[v] - x[u] for x in subset}
                attempts += 1
    return attempts


if __name__ == "__main__":
    ledger_rows, decisions = audit(*map(Path, sys.argv[1:]))
    print(
        json.dumps(
            {
                "ledger_rows": ledger_rows,
                "decisions": decisions,
                "exhaustive_cases": small_worlds(),
                "verified": True,
            }
        )
    )
