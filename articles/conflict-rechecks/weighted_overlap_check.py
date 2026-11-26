"""Verify overlapping reply portfolios directly from archives and response signatures."""

from argparse import ArgumentParser
from collections import Counter
from functools import cache
from hashlib import sha256
from heapq import heappop, heappush
from itertools import combinations, product
import json
from math import inf
from pathlib import Path, PurePosixPath
from random import Random
from stat import S_ISLNK
from zipfile import ZipFile

from weighted_overlap import Diagnostic


def oracle(prices, masks, n, errors, first_repeats=1, *, repeat_only=False):
    @cache
    def cover(old, hits):
        wanted = tuple(hits for _ in old)
        initial = (0,) * len(old)
        complete = {initial: 0}
        queue = [(0, initial)]
        while queue:
            cost, status = heappop(queue)
            if complete[status] != cost:
                continue
            if status == wanted:
                return cost
            for price, mask in zip(prices, masks, strict=True):
                update = tuple(
                    min(hits, s + ((mask >> j) & 1))
                    for s, j in zip(status, old, strict=True)
                )
                if cost + price < complete.get(update, inf):
                    complete[update] = cost + price
                    heappush(queue, (cost + price, update))
        return inf

    best = all_hit = inf
    for counts in product(range(first_repeats + 1), repeat=len(masks)):
        spent = sum(x * p for x, p in zip(counts, prices, strict=True))
        if spent >= max(best, all_hit):
            continue
        picked = [i for i, c in enumerate(counts) for _ in range(c)]
        groups = {}
        for i in range(n):
            bits = tuple(bool(masks[q] & (1 << i)) for q in picked)
            groups.setdefault(bits, []).append(i)
        worst = 0
        for bits, old in groups.items():
            used = sum(bits)
            if used <= errors:
                now = errors + 1 - used
                if repeat_only and used:
                    rest = now * min(
                        prices[q] for q, b in zip(picked, bits, strict=True) if b
                    )
                else:
                    rest = cover(tuple(old), now)
                worst = max(worst, rest)
        total = spent + worst
        best = min(best, total)
        if all(any(bits) for bits in groups):
            all_hit = min(all_hit, total)

    @cache
    def adaptive(old, f):
        if not old or f < 0:
            return 0
        ceiling = inf
        for price, mask in zip(prices, masks, strict=True):
            no = tuple(j for j in old if not (mask & (1 << j)))
            yes = tuple(j for j in old if mask & (1 << j))
            if yes:
                ceiling = min(
                    ceiling, price + max(adaptive(no, f), adaptive(yes, f - 1))
                )
        return ceiling

    all_old = tuple(range(n))
    return best, all_hit, cover(all_old, errors + 1), adaptive(all_old, errors)


def verify_all_replies(d, plan, f):
    checked = 0
    full_queries = (f + 1) * max(1, d.old_count) + len(plan.first)
    for j in range(d.old_count + 1):
        changes = (
            [()]
            if j < d.old_count
            else [a for k in range(f + 1) for a in combinations(range(full_queries), k)]
        )
        for flips in changes:
            read = 0

            def sensor(queries):
                nonlocal read
                levels = [
                    int(bool(d.masks[q] & (1 << j))) ^ int(read + i in flips)
                    for i, q in enumerate(queries)
                ]
                read += len(queries)
                return levels

            r = d.run(plan, f, sensor)
            assert len(r.observations) <= 2
            assert r.family == ("old" if j < d.old_count else "extension")
            assert j in r.possible_old if j < d.old_count else r.extension_possible
            assert read <= full_queries
            checked += 1
    return checked


def theory():
    tested = histories = 0
    rng = Random(509112)
    for n in (1, 2, 3):
        universe = range(1, 1 << n)
        for m in range(1, min(4, len(universe)) + 1):
            for masks in combinations(universe, m):
                union = 0
                for mask in masks:
                    union |= mask
                if union != (1 << n) - 1:
                    continue
                prices = tuple(rng.randrange(1, 15) for _ in masks)
                d = Diagnostic(n, masks, prices)
                for f in (0, 1, 2):
                    exact, cover, fixed, adaptive = oracle(
                        prices, masks, n, f, first_repeats=f + 1
                    )
                    assert d.compile(f).worst == exact
                    assert d.compile(f, cover_first=True).worst == cover
                    assert d.fixed(d.full, f + 1)[0] == fixed
                    assert d.adaptive(f) == adaptive
                    if f == 1:
                        r = d.compile_repeat()
                        assert r.worst == exact
                        assert d.compile_repeat(cover_first=True).worst == cover
                        histories += verify_all_replies(d, r, f)
                    histories += verify_all_replies(d, d.compile(f), f)
                    tested += 1
    masks, prices = (1, 6, 2, 4), (3, 11, 10, 5)
    direct = oracle(prices, masks, 3, 2)[0]
    repeat = oracle(prices, masks, 3, 2, repeat_only=True)[0]
    assert (direct, repeat) == (31, 33)
    return {
        "small_catalogs_across_allowances": tested,
        "reply_histories": histories,
        "two_error_trigger_counterexample": {
            "masks": masks,
            "prices": prices,
            "unrestricted": 31,
            "trigger_only": 33,
        },
    }


def archive(cache, pkg, sources):
    data = []
    for item in sources:
        path = cache / item["file"]
        assert sha256(path.read_bytes()).hexdigest() == item["sha256"]
        members = {}
        with ZipFile(path) as zf:
            for meta in zf.infolist():
                n = meta.filename
                parts = PurePosixPath(n).parts
                if (
                    meta.file_size <= 0
                    or meta.is_dir()
                    or S_ISLNK(meta.external_attr >> 16)
                    or ".." in parts
                ):
                    continue
                if (
                    len(parts) == 2
                    and parts[0].endswith(".dist-info")
                    and parts[1] == "METADATA"
                ):
                    key = ".dist-info/METADATA"
                elif (
                    parts[0] == pkg.lower()
                    and n.endswith(".py")
                    and all(
                        p.lower()
                        not in (
                            "tests",
                            "test",
                            "testing",
                            "docs",
                            "benchmarks",
                            "examples",
                        )
                        for p in parts
                    )
                ):
                    key = n
                else:
                    continue
                assert key not in members
                members[key] = (meta.file_size, sha256(zf.read(n)).hexdigest())
        data.append(members)
    common = set.intersection(*(set(d) for d in data))
    out = {}
    for q in sorted(common):
        parts = [row[q] for row in data]
        sizes, digests = map(list, zip(*parts, strict=True))
        mask = sum(1 << j for j, x in enumerate(digests[:-1]) if x != digests[-1])
        if mask:
            out[q] = {
                "mask": mask,
                "sizes": sizes,
                "sha256": digests,
                "price": max(sizes),
            }
    return out


def ledger(cache, record):
    summary = {}
    counted = Counter()
    for name, row in record["packages"].items():
        if "error" in row:
            continue
        observed = archive(cache, name, row["sources"])
        assert observed == row["members"]
        counted["members"] += len(observed)
        n = len(row["sources"]) - 1
        for scope in ("content", "with_metadata"):
            r = row[scope]
            expected = [
                x
                for x in observed
                if x != ".dist-info/METADATA" or scope == "with_metadata"
            ]
            assert r["paths"] == expected
            data = [observed[p] for p in expected]
            ms, ps = [q["mask"] for q in data], [q["price"] for q in data]
            cheapest = {}
            for m, p in zip(ms, ps, strict=True):
                cheapest[m] = min(p, cheapest.get(m, inf))
            compressed_masks = tuple(cheapest)
            compressed_prices = tuple(cheapest.values())
            impossible = [j for j in range(n) if not any(m & (1 << j) for m in ms)]
            assert r["count_masks"] == len(compressed_masks)
            overlap = any(
                sum(bool(m & (1 << j)) for m in compressed_masks) > 1 for j in range(n)
            )
            assert r["has_overlap"] == overlap
            if impossible:
                assert impossible == r["unsupported_old"]
                continue
            low = max(
                min(p for m, p in cheapest.items() if m & (1 << j)) for j in range(n)
            )
            universal = cheapest.get((1 << n) - 1)
            cert = r["universal_certificate"]
            assert (
                cert["bottleneck_min_price"] == low
                and cert["universal_price"] == universal
            )
            assert cert["optimal_for_any_round_count"] == (low == universal)
            counted["universal_optimal_arms"] += low == universal
            for errors, arm in r["by_errors"].items():
                f = int(errors)
                exact, full, fixed, adaptive = oracle(
                    compressed_prices, compressed_masks, n, f
                )
                assert (exact, full, fixed) == tuple(
                    arm["policies"][p]["quote"] for p in ("two", "cover_first", "fixed")
                )
                assert adaptive == arm["adaptive"]
                if low == universal:
                    assert exact == full == fixed == adaptive == (f + 1) * low
                totals = summary.setdefault(scope + "_" + errors, Counter())
                totals.update(
                    {
                        "two": exact,
                        "cover_first": full,
                        "fixed": fixed,
                        "adaptive": adaptive,
                        "comparable": 1,
                        "overlap": overlap,
                        "better_than_full_first": exact < full,
                    }
                )
                for key, policy in arm["policies"].items():
                    rates = []
                    for event in policy["events"]:
                        batches = event["batches"]
                        assert len(batches) <= 2
                        world = event["world"]
                        got = [p for batch in batches for p in batch]
                        assert (
                            (policy["first"] == [i for i, _ in batches[0]])
                            if policy["first"]
                            else True
                        )
                        for at, (q, y) in enumerate(got):
                            assert y == int(bool(ms[q] & (1 << world))) ^ int(
                                at in event["flip_input_positions"]
                            )
                        possible = [
                            j
                            for j in range(n)
                            if all(bool(ms[q] & (1 << j)) == b for q, b in got)
                        ]
                        e_ok = sum(bit for _, bit in got) <= f
                        assert (
                            (world in possible and not e_ok)
                            if world < n
                            else (e_ok and not possible)
                        )
                        bought = sum(ps[q] for q, _ in got)
                        actual = sum(data[q]["sizes"][world] for q, _ in got)
                        assert (
                            bought == event["charge"]
                            and actual == event["bytes"] <= bought
                        )
                        rates.append(bought)
                        counted["replayed"] += 1
                    assert max(rates) == policy["quote"]
    for key, totals in summary.items():
        existing = record["summary"][key]
        assert all(totals[k] == v for k, v in existing.items() if k != "totals")
        assert all(totals[k] == v for k, v in existing["totals"].items())
    metrics = summary["content_1"]
    passed = (
        metrics["overlap"] >= 5
        and metrics["better_than_full_first"] >= 3
        and 100 * metrics["two"] <= 90 * metrics["fixed"]
    )
    assert passed == record["passed_primary_gate"]
    return dict(counted)


if __name__ == "__main__":
    p = ArgumentParser(description=__doc__)
    for name in ("cache", "result", "output"):
        p.add_argument(name, type=Path)
    a = p.parse_args()
    report = {
        "theory": theory(),
        "ledger": ledger(a.cache, json.loads(a.result.read_bytes())),
    }
    a.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report))
