"""Independently check the ordered threshold against splits and archived replies."""

from argparse import ArgumentParser
from base64 import b64encode
from collections import Counter
from hashlib import sha256, sha512
from itertools import accumulate, combinations, combinations_with_replacement
import json
from pathlib import Path, PurePosixPath
import tarfile

from weighted_batches_check import possible_at
from weighted_rounds import execute_rounds, ordered_plan


def cut_cost(costs, errors, candidate):
    ordered = sorted(range(len(costs)), key=lambda i: (-costs[i], i))
    blocks, tail = candidate["blocks"], candidate["tail"]
    assert [i for a in (*blocks, tail) for i in a] == ordered
    spent = 0
    options = []
    for batch in blocks:
        assert batch
        spent += sum(costs[i] for i in batch)
        options.append(spent + errors * max(costs[i] for i in batch))
    options.append(spent + (errors + 1) * sum(costs[i] for i in tail))
    return max(options)


def independent_dp(costs, errors, rounds):
    q = sorted(costs, reverse=True)
    n = len(q)
    sums = [0]
    for p in q:
        sums.append(sums[-1] + p)
    # This DP evaluates all next block endpoints, independent of cap feasibility.
    values = [sums[i] + (errors + 1) * (sums[-1] - sums[i]) for i in range(n + 1)]
    for _ in range(rounds - 1):
        values = [
            min(
                values[i],
                *(max(sums[j] + errors * q[i], values[j]) for j in range(i + 1, n + 1)),
            )
            if i < n
            else sums[n]
            for i in range(n + 1)
        ]
    return values[0]


def answer_oracle(plan, n, f):
    max_queries = max(
        sum(map(len, plan.blocks)) + (f + 1) * len(plan.tail),
        sum(map(len, plan.blocks)) + f,
    )
    states = 0
    for stale in range(n):
        v = execute_rounds(plan, n, f, lambda keys: [int(i == stale) for i in keys])
        assert v.family == "old" and v.possible_old == (stale,)
        states += 1
    for k in range(f + 1):
        for hits in combinations(range(max_queries), k):
            count = 0

            def reply(keys):
                nonlocal count
                out = [int(i in hits) for i in range(count, count + len(keys))]
                count += len(keys)
                return out

            v = execute_rounds(plan, n, f, reply)
            assert v.family == "extension" and not v.possible_old
            states += 1
    return states


def small():
    checked, histories = 0, 0
    for size in range(1, 7):
        for costs in combinations_with_replacement(range(1, 6), size):
            for f in (0, 1, 2):
                A = independent_dp(costs, f, size)
                for r in range(1, min(5, size + 1) + 1):
                    p = ordered_plan(costs, f, r)
                    assert p.worst_cost == independent_dp(costs, f, r)
                    assert len(p.blocks) + bool(p.tail) <= r
                    assert (
                        cut_cost(costs, f, {"blocks": p.blocks, "tail": p.tail})
                        == p.worst_cost
                    )
                    den = 1 + (r - 1) * (f + 1)
                    assert den * p.worst_cost <= (den + f) * A
                    if f == 1 and r == 3:
                        assert 11 * p.worst_cost <= 13 * A
                    if size <= 4:
                        histories += answer_oracle(p, size, f)
                    checked += 1
    ks = (2, 3, 5, 10, 25, 100)
    for k in ks:
        costs = [5 * k, 3 * k, k, k] + [1] * (k - 1)
        assert independent_dp(costs, 1, 3) == 13 * k - 2
        assert ordered_plan(costs, 1, 3).worst_cost == 13 * k - 2
    return {
        "exact_cost_and_bound_cases": checked,
        "explicit_reply_histories": histories,
        "three_round_tight_family_cases": len(ks),
    }


def check_files(cache, row):
    results = []
    for src in row["sources"]:
        tgz = cache / src["file"]
        assert (
            src["integrity"]
            == "sha512-" + b64encode(sha512(tgz.read_bytes()).digest()).decode()
        )
        allowed = {}
        with tarfile.open(tgz, mode="r:gz") as a:
            for m in a.getmembers():
                parts = m.name.split("/")
                if (
                    m.isfile()
                    and m.size > 0
                    and parts[0] == "package"
                    and len(parts) > 1
                    and ".." not in parts
                    and PurePosixPath(parts[-1]).suffix in (".js", ".cjs", ".mjs")
                    and not any(
                        s.lower()
                        in (
                            "test",
                            "tests",
                            "spec",
                            "fixtures",
                            "docs",
                            "benchmark",
                            "benchmarks",
                            "examples",
                        )
                        for s in parts[1:]
                    )
                ):
                    assert m.name not in allowed
                    allowed[m.name] = (
                        m.size,
                        sha256(a.extractfile(m).read()).hexdigest(),
                    )
        results.append(allowed)
    a, b = results
    names = [i for i in sorted(set(a) & set(b)) if a[i] != b[i]]
    assert names == [m["path"] for m in row["members"]]
    for item in row["members"]:
        x, y = a[item["path"]], b[item["path"]]
        assert item["size"] == [x[0], y[0]]
        assert item["sha256"] == [x[1], y[1]]
        assert item["price"] == max(item["size"])


def expected_trace(blocks, tail, f, stale, inject):
    if inject and blocks:
        return [blocks[0], [blocks[0][0]] * f]
    trace = []
    for a in blocks:
        trace.append(a)
        if stale in a:
            trace.append([stale] * f)
            return trace
    assert tail or stale is None
    if tail:
        trace.append([i for i in tail for _ in range(f + 1)])
    return trace


def check_replay(members, report, f):
    sizes = [m["size"] for m in members]
    costs = [max(s) for s in sizes]
    n = len(costs)
    assert not possible_at(costs, f, report["exact2"] - 1)
    first = report["exact2_first"]
    assert sorted(set(first)) == sorted(first)
    rest = [i for i in range(n) if i not in first]
    ordered = report["ordered"]["3"]
    stats = {}
    for name, blocks, tail, max_cost, max_round in (
        ("exact2", [first] if first else [], rest, report["exact2"], 2),
        ("ordered3", ordered["blocks"], ordered["tail"], ordered["cost"], 3),
    ):
        events = report["replays"][name]
        assert [r["stale"] for r in events] == [*range(n), None, None]
        for j, r in enumerate(events):
            inject = j == n + 1
            old = r["stale"]
            assert r["flips"] == (f if inject else 0)
            trace = expected_trace(blocks, tail, f, old, inject)
            counts = Counter(i for block in trace for i in block)
            assert r["rounds"] == len(trace) <= max_round
            assert r["reads"] == sum(counts.values())
            assert (
                r["reserved"]
                == sum(costs[i] * x for i, x in counts.items())
                <= max_cost
            )
            assert r["payload"] == sum(
                sizes[i][0 if old == i else 1] * x for i, x in counts.items()
            )
            # Along any stale source replay, enough matching positives remain
            # to exceed the extension budget. No other source can explain it.
            if old is not None:
                assert counts[old] > f
            else:
                assert all(counts.values())
        assert max(r["reserved"] for r in events) == max_cost
        stats[name] = len(events)
    return sum(stats.values())


def ledger(cache, result):
    counts = Counter()
    by_allowance = {}
    for row in result["packages"].values():
        check_files(cache, row)
        counts["members"] += len(row["members"])
        for fs, p in row["results"].items():
            f = int(fs)
            costs = [m["price"] for m in row["members"]]
            ordered = sorted(costs, reverse=True)
            assert (
                max(
                    s + f * c for s, c in zip(accumulate(ordered), ordered, strict=True)
                )
                == p["sequential"]
            )
            assert independent_dp(costs, f, 1) == p["fixed"]
            for k, a in p["ordered"].items():
                rounds = int(k)
                assert len(a["blocks"]) + bool(a["tail"]) <= rounds
                assert (
                    cut_cost(costs, f, a)
                    == a["cost"]
                    == independent_dp(costs, f, rounds)
                )
                den = 1 + (rounds - 1) * (f + 1)
                assert den * a["cost"] <= (den + f) * p["sequential"]
            counts["replay_costs_checked"] += check_replay(row["members"], p, f)
            acc = by_allowance.setdefault(fs, Counter())
            for key in ("fixed", "exact2", "sequential"):
                acc[key] += p[key]
            for k, v in p["ordered"].items():
                acc["ordered" + k] += v["cost"]
            cmp = p["ordered"]["3"]["cost"] - p["exact2"]
            acc["less" if cmp < 0 else "more" if cmp > 0 else "equal"] += 1
    for f, total in by_allowance.items():
        got = result["summary"]["by_allowance"][f]
        assert all(total[k] == v for k, v in got["totals"].items())
        assert all(total[k] == got[k] for k in ("less", "equal", "more"))
    primary = by_allowance["1"]
    assert result["summary"]["passed_primary_gate"] == (
        primary["less"] + primary["equal"] + primary["more"] == 10
        and primary["less"] >= 7
        and 100 * primary["ordered3"] <= 95 * primary["exact2"]
    )
    return dict(counts)


if __name__ == "__main__":
    p = ArgumentParser(description=__doc__)
    for k in ("cache", "record", "output"):
        p.add_argument(k, type=Path)
    a = p.parse_args()
    suite = {
        "ordered_frontier": small(),
        "holdout": ledger(a.cache, json.loads(a.record.read_bytes())),
    }
    a.output.write_text(json.dumps(suite, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(suite))
