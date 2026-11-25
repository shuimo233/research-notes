"""Verify simplex cover certificates directly from the frozen model gates."""

from collections import Counter, defaultdict
import csv
from fractions import Fraction as F
from functools import cache
import gzip
from hashlib import sha1
from itertools import combinations, product
import json
from math import prod
from pathlib import Path
from struct import unpack

WIDTHS = (0, 16, 24, 32, 48, 64, 96, 128)
B, H, DELTA, EPS = F(21, 20), F(1, 2), F(1, 4), F(1, 1000)
BUDGET = 96
NAMES = ("audit-runtime-drift-policies.json.gz", "audit-runtime-drift-results.json")
LOGITS = "e1002444bf4be9c91336a33b4c58358d6f48645c"
PREVIOUS = "30ce968781a96a0fd4542987de68778d2f9dd914"


def pinned(raw, expected):
    assert sha1(f"blob {len(raw)}\0".encode() + raw).hexdigest() == expected
    return raw


def inputs(ledger, previous):
    table = {}
    for row in csv.DictReader(
        pinned(ledger.read_bytes().replace(b"\r\n", b"\n"), LOGITS)
        .decode()
        .splitlines(),
        delimiter="\t",
    ):
        rates = []
        for width in WIDTHS:
            score = [
                F(unpack(">f", bytes.fromhex(row[f"w{width}_{c}"]))[0]) for c in "ENC"
            ]
            sign = 1 if row["gold"] == "entailment" else -1
            rates.append(sign * (score[0] - max(score[1:])))
        table[row["subset"], row["id"]] = (row["gold"], tuple(rates))
    assert len(table) == 1672

    for i, (split, threshold, kind, law) in enumerate(
        json.loads(gzip.decompress(pinned(previous.read_bytes(), PREVIOUS)))
    ):
        cutoff = F(threshold)
        pairs = [[table[split, tag] for tag in p] for p in law["pairs"]]
        assert len(pairs) == 4 and all(
            {a[0], b[0]} == {"entailment", "neutral"} for a, b in pairs
        )
        rates = tuple(
            tuple(
                tuple(F(1, 20) if x > 0 and x >= cutoff else F(19, 20) for x in margin)
                for _, margin in direction
            )
            for direction in zip(*pairs, strict=True)
        )
        yield (i, split, threshold, kind, F(law["safe"])), rates


def budget_from_slope(s, cap, maximum):
    return min(maximum, (cap - 1) / s) if s > 0 else maximum


def windows(w):
    return [s for size in range(2, w + 1) for s in combinations(range(w), size)]


def laws(rates, subset, weights, cap=B):
    masses = []
    for world in rates:
        conditional = [world[i] for i in subset]
        independent = prod(
            sum(p * x for p, x in zip(weights, row, strict=True)) for row in conditional
        )
        dependent = sum(
            p * prod(c)
            for p, c in zip(weights, zip(*conditional, strict=True), strict=True)
        )
        masses.append(dependent / independent - 1)
    x, y = masses
    return max(x - cap * y, y - cap * x)


def inventory(rates, center):
    seen = {}
    for subset in windows(len(rates[0])):
        tables = []
        for world in rates:
            relevant = tuple(
                sorted(world[i] for i in subset if max(world[i]) > min(world[i]))
            )
            tables.append(relevant if len(relevant) > 1 else ())
        first, second = tables
        if not first and not second:
            continue
        prefix, suffix = (
            tuple(zip(*first)) if first else ((),) * len(center),
            tuple(zip(*second)) if second else ((),) * len(center),
        )
        labels = tuple(a + b for a, b in zip(prefix, suffix, strict=True))
        classes = sorted(set(labels))
        masses = tuple(
            sum(k for k, l in zip(center, labels, strict=True) if l == c)
            for c in classes
        )
        a = [tuple(t[i] for t in classes) for i in range(len(first))]
        b = [tuple(t[i + len(first)] for t in classes) for i in range(len(second))]
        seen.setdefault((len(first), tuple(classes), masses), (a, b, masses))
    return list(seen.values())


def convolution(a, b):
    out = defaultdict(F)
    for (x, v), (y, w) in product(a.items(), b.items()):
        out[tuple(i + j for i, j in zip(x, y, strict=True))] += v * w
    return dict(out)


def enclosure(model, vertices, drift, cap, separate=False):
    first, second, center = model
    n = len(vertices)
    basis = tuple(tuple(int(i == j) for i in range(n)) for j in range(n))
    one = {(0,) * n: F(1)}
    form = [
        tuple((1 - drift) * c + drift * v for c, v in zip(center, vertex, strict=True))
        for vertex in vertices
    ]
    a, b, lo, hi = [], [], [], []
    for world in (first, second):
        if not world:
            a.append(one)
            b.append(one)
            lo.append(F(0))
            hi.append(F(0))
            continue
        mean_vectors = [
            tuple(sum(row[i] * p[i] for i in range(n)) for p in form) for row in world
        ]
        joint_vector = tuple(
            sum(p[i] * prod(row[i] for row in world) for i in range(n)) for p in form
        )
        lo.append(min(joint_vector) / prod(max(v) for v in mean_vectors) - 1)
        hi.append(max(joint_vector) / prod(min(v) for v in mean_vectors) - 1)
        independent = one
        for values in mean_vectors:
            independent = convolution(
                independent, dict(zip(basis, values, strict=True))
            )
        shared = dict(zip(basis, joint_vector, strict=True))
        for _ in range(len(world) - 1):
            shared = convolution(shared, dict.fromkeys(basis, F(1)))
        a.append(independent)
        b.append(shared)
    coarse = max(hi[0] - cap * lo[1], hi[1] - cap * lo[0])
    if separate:
        return coarse
    denom = convolution(*a)
    numerator_p = convolution(b[0], a[1])
    numerator_q = convolution(b[1], a[0])
    assert min(denom.values()) > 0
    bernstein = max(
        (cap - 1)
        + max(
            (numerator_p[p] - cap * numerator_q[p]) / v,
            (numerator_q[p] - cap * numerator_p[p]) / v,
        )
        for p, v in denom.items()
    )
    return min(coarse, bernstein)


@cache
def certificate_bounds(rates, center, drift, cap, maximum, trace):
    models = inventory(rates, center)
    cuts = {}
    for model, path, i, j in trace:
        assert (
            type(model) is int
            and 0 <= model < len(models)
            and (model, path) not in cuts
        )
        assert isinstance(path, str) and set(path) <= set("01")
        cuts[model, path] = i, j
    seen = set()
    coarse, upper, peak_modes = F(0), F(0), 0

    def cover(k, path, vertices):
        key = k, path
        if key not in cuts:
            return enclosure(models[k], vertices, drift, cap)
        assert key not in seen
        seen.add(key)
        i, j = cuts[key]
        assert type(i) is int and type(j) is int and 0 <= i < j < len(vertices)
        mid = tuple((a + b) / 2 for a, b in zip(vertices[i], vertices[j], strict=True))
        lo = list(vertices)
        hi = list(vertices)
        lo[i] = mid
        hi[j] = mid
        return max(cover(k, path + "0", lo), cover(k, path + "1", hi))

    for k, m in enumerate(models):
        d = len(m[2])
        peak_modes = max(d, peak_modes)
        base = [tuple(F(a == b) for a in range(d)) for b in range(d)]
        coarse = max(coarse, enclosure(m, base, drift, cap, separate=True))
        upper = max(upper, cover(k, "", base))
    assert seen == set(cuts)
    return (
        budget_from_slope(upper, cap, maximum),
        budget_from_slope(coarse, cap, maximum),
        len(models),
        peak_modes,
    )


@cache
def sampled_baselines(rates, center, drift, cap, maximum):
    subsets = windows(len(rates[0]))
    vertices = [
        tuple((1 - drift) * w + drift * (j == i) for i, w in enumerate(center))
        for j in range(len(center))
    ]
    center_slope = max(laws(rates, s, center, cap) for s in subsets)
    vertex_slope = max(laws(rates, s, v, cap) for v in vertices for s in subsets)
    return budget_from_slope(center_slope, cap, maximum), budget_from_slope(
        vertex_slope, cap, maximum
    )


def proof(rates, report, drift=DELTA, cap=B, maximum=H, center=None, budget=BUDGET):
    n = len(rates[0][0])
    center = (F(1, n),) * n if center is None else tuple(map(F, center))
    assert len(rates) == 2 and len(rates[0]) == len(rates[1]) >= 2 and n > 0
    assert len(center) == n and min(center) >= 0 and sum(center) == 1
    assert all(len(v) == n and all(0 < p < 1 for p in v) for m in rates for v in m)
    assert (
        0 <= drift <= 1
        and cap >= 1
        and 0 < maximum <= 1
        and type(budget) is int
        and budget >= 0
    )
    limit = report["splits"]
    assert len(limit) <= budget
    lower, coarse, num_models, peak = certificate_bounds(
        rates, center, drift, cap, maximum, tuple(tuple(x) for x in limit)
    )
    nominal, vert = sampled_baselines(rates, center, drift, cap, maximum)
    witness = report["witness"]
    upper = maximum
    if witness is not None:
        u = tuple(map(F, witness["contamination"]))
        assert len(u) == n and min(u) >= 0 and sum(u) == 1
        s = tuple(witness["window"])
        assert s in windows(len(rates[0]))
        w = tuple((1 - drift) * a + drift * b for a, b in zip(center, u, strict=True))
        upper = budget_from_slope(laws(rates, s, w, cap), cap, maximum)
    assert coarse <= lower <= upper <= min(nominal, vert)
    assert (num_models, peak) == (report["models"], report["max_modes"])
    values = (nominal, vert, coarse, lower, upper)
    assert values == tuple(
        F(report[x])
        for x in ("center_cap", "vertex_cap", "separate_safe", "safe", "ceiling")
    )
    return values


def update(stats, values, row):
    nominal, vertex, coarse, low, high = values
    counts = stats["counts"]
    counts["profiles"] += 1
    counts["center_witness_fail"] += nominal > high
    counts["vertex_witness_fail"] += vertex > high
    counts["improved_over_separate"] += low > coarse
    counts["within_precision"] += high - low <= EPS
    counts["exact"] += low == high
    counts["mode_reduction"] += 0 < row["max_modes"] < 8
    counts["no_joint_effect"] += row["models"] == 0
    counts["max_splits"] = max(counts["max_splits"], len(row["splits"]))
    counts["max_effective_modes"] = max(counts["max_effective_modes"], row["max_modes"])
    stats["max_gap"] = max(stats["max_gap"], high - low)
    if nominal - high > stats["largest_proved_center_loss"]:
        stats["largest_proved_center_loss"] = nominal - high
        stats["largest_case"] = row["case"]


def summarize(ledger, previous, policies, verify):
    states = {}
    for (key, rates), row in zip(inputs(ledger, previous), policies, strict=True):
        index, split, threshold, kind, before = key
        assert row["case"] == index
        values = (
            proof(rates, row)
            if verify
            else tuple(
                F(row[x])
                for x in (
                    "center_cap",
                    "vertex_cap",
                    "separate_safe",
                    "safe",
                    "ceiling",
                )
            )
        )
        assert values[0] == before
        for scope in (kind, f"{kind}/{split}/{threshold}"):
            stat = states.setdefault(
                scope,
                {
                    "counts": Counter(),
                    "max_gap": F(0),
                    "largest_proved_center_loss": F(0),
                    "largest_case": None,
                },
            )
            update(stat, values, row)
    results = {}
    for label in sorted(states):
        state = states[label]
        results[label] = {
            k: (
                str(v) if isinstance(v, F) else dict(v) if isinstance(v, Counter) else v
            )
            for k, v in state.items()
        }
    relevant = [results[x]["counts"] for x in ("main", "diagnostic")]
    total = sum(a["profiles"] for a in relevant)
    within = sum(a["within_precision"] for a in relevant)
    assert total == 2508
    return {
        "sections": results,
        "precision_passed": within,
        "gate": F(within, total) >= F(19, 20),
    }


def verify(ledger, previous, output):
    packets = json.loads(gzip.decompress((output / NAMES[0]).read_bytes()))
    report = summarize(ledger, previous, packets, True)
    assert report == json.loads((output / NAMES[1]).read_bytes())
    print(
        json.dumps(
            {
                "verified": True,
                "precision_passed": report["precision_passed"],
                "gate": report["gate"],
            }
        )
    )


if __name__ == "__main__":
    import argparse

    cli = argparse.ArgumentParser(description=__doc__)
    for n in ("ledger", "previous"):
        cli.add_argument(n, type=Path)
    cli.add_argument("output", type=Path, nargs="?")
    cli.add_argument(
        "--contract",
        action="store_true",
        help="verify a JSON contract and evidence file",
    )
    options = cli.parse_args()
    if options.contract:
        data = json.loads(options.ledger.read_text(encoding="utf-8"))
        evidence = json.loads(options.previous.read_text(encoding="utf-8-sig"))
        rates = tuple(tuple(tuple(map(F, q)) for q in t) for t in data["rates"])
        _, _, _, low, high = proof(
            rates,
            evidence,
            F(data.get("drift", DELTA)),
            F(data.get("cap", B)),
            F(data.get("max_share", H)),
            data.get("center"),
            data.get("budget", BUDGET),
        )
        print(json.dumps({"verified": True, "safe": str(low), "ceiling": str(high)}))
    elif options.output is None:
        cli.error("an output directory is required in replay mode")
    else:
        verify(options.ledger, options.previous, options.output)
