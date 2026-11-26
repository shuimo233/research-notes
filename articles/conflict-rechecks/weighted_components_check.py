"""Independent actual-response and archive verification for component rechecks."""

from argparse import ArgumentParser
from collections import Counter, defaultdict
from functools import cache
import gzip
from hashlib import sha256
from itertools import combinations, combinations_with_replacement, product
import json
from math import inf, prod
from pathlib import Path
from random import Random
import tarfile
import tomllib

from weighted_components import ComponentDiagnosis
from weighted_overlap import Diagnostic


def words(models, columns):
    masks = []
    for c, q in columns:
        masks.append(sum(1 << i for i, row in enumerate(models) if (q >> row[c]) & 1))
    return tuple(masks)


def raw_tree(masks, costs, old_n, errors):
    """Enumerate whole planned batches, including repeated queries."""
    menu = []
    for repeat in product(range(errors + 2), repeat=len(costs)):
        if not any(repeat):
            continue
        asks = tuple(i for i, k in enumerate(repeat) for _ in range(k))
        patterns = tuple(
            sum(1 << j for j, q in enumerate(asks) if (masks[q] >> world) & 1)
            for world in range(old_n)
        )
        menu.append((sum(costs[q] for q in asks), len(asks), patterns))
    menu.sort()

    @cache
    def visit(alive, left, cap):
        if not alive or left < 0:
            return 0
        if not cap:
            return inf
        best = visit(alive, left, cap - 1)
        for cost, n, patterns in menu:
            if cost >= best:
                break
            old = {}
            for j, bits in enumerate(patterns):
                if (alive >> j) & 1:
                    old[bits] = old.get(bits, 0) | (1 << j)
            outcomes = set(old)
            for k in range(min(left, n) + 1):
                outcomes.update(
                    sum(1 << j for j in subset) for subset in combinations(range(n), k)
                )
            v = max(
                visit(old.get(reply, 0), left - reply.bit_count(), cap - 1)
                for reply in outcomes
            )
            best = min(best, cost + v)
        return best

    return tuple(visit((1 << old_n) - 1, errors, r) for r in (1, 2, 3))


def theoretical():
    rng = Random(541813)
    configs = paths = 0
    for _ in range(54):
        ds = []
        for _ in range(2):
            n = rng.choice((1, 2))
            m = rng.choice((1, 2))
            masks = [rng.randrange(1, 1 << n) for _ in range(m - 1)]
            covered = 0
            for mask in masks:
                covered |= mask
            missing = ((1 << n) - 1) & ~covered
            masks.append(missing or rng.randrange(1, 1 << n))
            ds.append(Diagnostic(n, masks, [rng.randrange(1, 12) for _ in masks]))
        target = tuple(d.old_count for d in ds)
        full = [m for m in product(*(range(u + 1) for u in target)) if m != target]
        isolated = [m for m in full if sum(a != b for a, b in zip(m, target)) == 1]
        sliced = [m for m in full if m in isolated or rng.randrange(2)]
        coords = [(c, q) for c, d in enumerate(ds) for q in d.masks]
        costs = [x for d in ds for x in d.costs]
        D = ComponentDiagnosis(ds)
        for f in (0, 1, 2):
            a, b, c = (
                raw_tree(words(m, coords), costs, len(m), f)
                for m in (full, isolated, sliced)
            )
            assert a == b == c
            plan = D.compile(f)
            assert plan.worst == a[1] and D.fixed_cost(f) == a[0]
            configs += 1
            room = sum(len(p.first) for p in plan.profiles) + (f + 1) * sum(target)
            for world in (*full, target):
                variants = (
                    [()]
                    if world != target
                    else [c for k in range(f + 1) for c in combinations(range(room), k)]
                )
                for flips in variants:
                    sent = 0

                    def reader(test):
                        nonlocal sent
                        report = [
                            int(bool(ds[i].masks[j] & (1 << world[i])))
                            ^ int(sent + k in flips)
                            for k, (i, j) in enumerate(test)
                        ]
                        sent += len(test)
                        return report

                    got = D.run(plan, f, reader)
                    assert got.family == ("target" if world == target else "old")
                    assert len(got.observations) <= 2 and sent <= room
                    paths += 1
    return {
        "model_allowance_sets": configs,
        "full_raw_tree_comparisons": configs * 3,
        "executed_histories": paths,
    }


def independently_priced(probes, n, f):
    cheaper = {}
    for q in probes:
        cheaper[q["mask"]] = min(cheaper.get(q["mask"], inf), q["price"])
    offers = list(cheaper.items())

    @cache
    def cover(olds, k):
        if not olds:
            return 0
        best = inf
        for r in range(1, k * len(olds) + 1):
            for group in combinations_with_replacement(offers, r):
                if all(sum((m >> i) & 1 for m, _ in group) >= k for i in olds):
                    best = min(best, sum(p for _, p in group))
        return best

    options = []
    for repeat in product((0, 1), repeat=len(offers)):
        first = [(m, p) for b, (m, p) in zip(repeat, offers) if b]
        a = sum(p for _, p in first)
        groups = defaultdict(list)
        for j in range(n):
            bits = tuple(bool(m & (1 << j)) for m, _ in first)
            groups[bits].append(j)
        b = cover(
            tuple(j for bits, old in groups.items() if not any(bits) for j in old),
            f + 1,
        )
        d = max(
            (
                cover(tuple(v), f + 1 - sum(k))
                for k, v in groups.items()
                if 0 < sum(k) <= f
            ),
            default=0,
        )
        options.append((a, b, d))
    return options, cover(tuple(range(n)), f + 1)


def min_not_below(rows, quote, full):
    # Enumerate branch bounds on the independent local triples, without Pareto convolution.
    seen = 0
    has_equal = False

    def traverse(step, a, b, d):
        nonlocal seen, has_equal
        seen += 1
        lower = a + max(b, d)
        if lower > quote:
            return
        if step == len(rows):
            assert lower == quote
            has_equal = True
            return
        for x, y, z in rows[step]:
            if not full or y == 0:
                traverse(step + 1, a + x, b + y, max(d, z))

    traverse(0, 0, 0, 0)
    assert has_equal
    return seen


def mapping(cache, app):
    parts = []
    for row in app["anchors"]:
        p = cache / row["file"]
        assert sha256(p.read_bytes()).hexdigest() == row["sha256"]
        with tarfile.open(p, mode="r:gz") as z:
            key = row["name"] + "-" + row["version"] + "/Cargo.lock"
            fields = tomllib.loads(z.extractfile(z.getmember(key)).read().decode())
        table = defaultdict(list)
        for d in fields["package"]:
            if d.get(
                "source"
            ) == "registry+https://github.com/rust-lang/crates.io-index" and d.get(
                "checksum"
            ):
                table[d["name"]].append((d["version"], d["checksum"]))
        parts.append(table)
    expected = {}
    for name in sorted(parts[-1]):
        if not all(len(q[name]) == 1 for q in parts):
            continue
        current = parts[-1][name][0]
        older = sorted({a[name][0] for a in parts[:-1]} - {current})
        if older:
            expected[name] = [{"version": v, "sha256": h} for v, h in [*older, current]]
        if len(expected) == 8:
            break
    assert expected == app["choices"]
    return expected


def source_cells(cache, info):
    result = []
    for m in info["sources"]:
        file = cache / m["file"]
        raw = file.read_bytes()
        assert sha256(raw).hexdigest() == m["sha256"] and len(raw) == m["bytes"]
        here = {"@archive": (len(raw), m["sha256"])}
        prefix = f"{m['name']}-{m['version']}/src/"
        with tarfile.open(file, mode="r:gz") as z:
            for item in z.getmembers():
                name = item.name
                if (
                    item.isfile()
                    and item.size
                    and name.startswith(prefix)
                    and name.endswith(".rs")
                    and ".." not in name.split("/")
                ):
                    key = name.split("/", 1)[1]
                    assert key not in here
                    here[key] = (
                        item.size,
                        sha256(z.extractfile(item).read()).hexdigest(),
                    )
        result.append(here)
    fields = []
    for key in sorted(set.intersection(*(set(x) for x in result))):
        cols = [m[key] for m in result]
        sizes, stamps = map(list, zip(*cols, strict=True))
        mask = sum(1 << i for i, h in enumerate(stamps[:-1]) if h != stamps[-1])
        if mask:
            fields.append(
                {
                    "path": key,
                    "price": max(sizes),
                    "sha256": stamps,
                    "sizes": sizes,
                    "mask": mask,
                }
            )
    assert fields == info["rows"]


def check_events(components, policy, f):
    counts = Counter()
    all_fees = []
    target = [len(d["sources"]) - 1 for d in components]
    for ev in policy["events"]:
        w = ev["world"]
        first = [(c, q) for c, row in enumerate(policy["first"]) for q in row]
        obs = ev["observations"]
        assert len(obs) <= 2
        if first:
            assert first == [tuple(k) for k, b in obs[0]]
        flat = [(p, v) for layer in obs for p, v in layer]
        valid = [set(range(n + 1)) for n in target]
        charges = actual = bits = 0
        for j, ((c, q), b) in enumerate(flat):
            p = components[c]["rows"][q]
            true = (p["mask"] >> w[c]) & 1
            assert (true ^ int(j in ev["flips"])) == b
            charges += p["price"]
            actual += p["sizes"][w[c]]
            bits += b
            valid[c] = {i for i in valid[c] if ((p["mask"] >> i) & 1) == b}
        old = all(valid) and any(any(i != t for i in v) for v, t in zip(valid, target))
        if w == target:
            assert bits <= f and not old
        else:
            assert bits > f and old and all(x in v for x, v in zip(w, valid))
        assert charges == ev["paid"] and actual == ev["bytes"] <= charges
        all_fees.append(charges)
        counts["cases"] += 1
        counts["multiple_components"] += sum(a != b for a, b in zip(w, target)) > 1
    assert max(all_fees) == policy["cost"]
    assert max(e["bytes"] for e in policy["events"]) == policy["max_payload"]
    return counts


def test_ledger(cache, intake, result):
    counts = Counter()
    for app, row in result["applications"].items():
        source = intake["applications"][app]
        if "unavailable" in row:
            continue
        keys = mapping(cache, source)
        assert list(keys) == [p["name"] for p in row["components"]]
        n = []
        for comp in row["components"]:
            assert [
                {"version": d["version"], "sha256": d["sha256"]}
                for d in comp["sources"]
            ] == keys[comp["name"]]
            source_cells(cache, comp)
            n.append(len(comp["sources"]) - 1)
            counts["component_sets"] += 1
            counts["measured_probes"] += len(comp["rows"])
        assert prod(x + 1 for x in n) - 1 == row["non_target_worlds"]
        if "unsupported" in row:
            continue
        for fs, policies in row["quote"].items():
            f = int(fs)
            local, stat = map(
                list,
                zip(
                    *(
                        independently_priced(p["rows"], s, f)
                        for s, p in zip(n, row["components"], strict=True)
                    ),
                    strict=True,
                ),
            )
            assert sum(stat) == policies["fixed"]["cost"]
            for key, policy in policies.items():
                if key != "fixed":
                    counts["independent_price_nodes"] += min_not_below(
                        local, policy["cost"], key == "full_first"
                    )
                counts.update(check_events(row["components"], policy, f))
    for k, s in result["summary"].items():
        active = [a for a in result["applications"].values() if "quote" in a]
        assert len(active) == s["valid"]
        assert all(
            sum(a["quote"][k][m]["cost"] for a in active) == v
            for m, v in s["total"].items()
        )
        assert sum(len(a["components"]) >= 4 for a in active) == s["four_or_more"]
        assert (
            sum(
                a["quote"][k]["exact2"]["cost"] < a["quote"][k]["full_first"]["cost"]
                for a in active
            )
            == s["strict_better_full_first"]
        )
    p = result["summary"]["1"]
    assert result["passed_primary_gate"] == (
        p["four_or_more"] >= 3
        and p["strict_better_full_first"] >= 2
        and 100 * p["total"]["exact2"] <= 85 * p["total"]["fixed"]
    )
    return dict(counts)


if __name__ == "__main__":
    p = ArgumentParser(description=__doc__)
    for field in ("cache", "intake", "result", "output"):
        p.add_argument(field, type=Path)
    args = p.parse_args()
    report = {
        "theory": theoretical(),
        "ledger": test_ledger(
            args.cache,
            json.loads(args.intake.read_bytes()),
            json.loads(gzip.decompress(args.result.read_bytes())),
        ),
    }
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report))
