"""Check the two witness algorithms and the two finite hardness constructions."""

from itertools import combinations, product
import json
from pathlib import Path
from random import Random
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from conclusion_replay import closure
from public_optimality import PublicAudit
from slack_certificate import classifications, verify_report
from universal_witness import binary_compatible, outside, refutable


def sat_archive(n, clauses):
    count = n + 2 * len(clauses)
    facts, report, pins = [], [], []
    for j, clause in enumerate(clauses):
        u = n + 2 * j + 1
        v = u + 1
        for letter in clause:
            i = abs(letter)
            a, b = (u, i) if letter > 0 else (i, v)
            facts.append((a, b, -1, 0))
        report.append((u, v, (1,)))
        pins.append((u, 1))
    return (
        PublicAudit(
            closure([(0, 1)] * count, facts),
            report,
            dict(labels=[0] * len(report), disclosed=pins),
        ),
        set(range(n + 1, count + 1)),
    )


def colour_archive(k, per_colour, links):
    size = k * per_colour
    count = 2 * size + 4 * k
    facts, report, pins = [], [], []
    for c in range(k):
        u, v = 2 * size + 4 * c + 1, 2 * size + 4 * c + 2
        for i in range(c * per_colour + 1, (c + 1) * per_colour + 1):
            facts.extend(((u, i, -1, 0), (size + i, v + 2, -1, 0)))
        report.extend(((u, v, (1,)), (u + 2, v + 2, (1,))))
        pins.extend(((u, 1), (u + 2, 1)))
    for i, j in combinations(range(1, size + 1), 2):
        if (i - 1) // per_colour == (j - 1) // per_colour or (i, j) not in links:
            facts.extend(((size + j, i, -1, 0), (size + i, j, -1, 0)))
    return (
        PublicAudit(
            closure([(0, 1)] * count, facts),
            report,
            dict(labels=[0] * len(report), disclosed=pins),
        ),
        set(range(2 * size + 1, count + 1)),
    )


def verify_sample(audit, group, reading):
    assert all(reading[i] == x for i, x in audit.disclosed.items())
    assert all(
        reading[v] - reading[u] <= a
        for u, row in enumerate(audit.archive)
        for v, a in enumerate(row)
    )
    verify_report(
        audit.archive,
        audit.targets,
        audit.labels,
        [(i, reading[i]) for i in outside(audit, group)],
    )


def check_domains(rng):
    count = 0
    for _ in range(100):
        n = rng.randrange(2, 5)
        width = rng.choice((2, 3, 4))
        lo = 0 if width == 2 else -2
        support = range(lo, lo + width)
        x = (0, *(rng.choice(support) for _ in range(n)))
        facts, targets = [], []
        for u, v in combinations(range(n + 1), 2):
            d = x[v] - x[u]
            if rng.random() < 0.6:
                facts.append((u, v, d - rng.randrange(3), d + rng.randrange(3)))
            if rng.random() < 0.55:
                targets.append((u, v, tuple(sorted(rng.sample(range(-4, 5), 2)))))
        universe = [
            w
            for w in ((0, *p) for p in product(support, repeat=n))
            if all(a <= w[j] - w[i] <= b for i, j, a, b in facts)
        ]
        label = classifications(targets, x)
        good = [w for w in universe if classifications(targets, w) == label]
        okay = set(good)
        bad = [w for w in universe if w not in okay]
        selected = list(range(1, n + 1))
        rng.shuffle(selected)
        for point in selected[:]:
            rem = [i for i in selected if i != point]
            if not any(all(w[i] == x[i] for i in rem) for w in bad):
                selected = rem
        compatible = [w for w in good if all(w[i] == x[i] for i in selected)]
        audit = PublicAudit(
            closure([(support[0], support[-1])] * n, facts),
            targets,
            dict(labels=label, disclosed=[(i, x[i]) for i in selected]),
        )
        for size in (1, 2):
            for g in combinations(range(1, n + 1), size):
                free = [i for i in range(1, n + 1) if i not in g]
                wrong = {tuple(w[i] for i in free) for w in bad}
                sufficient_exists = any(
                    tuple(w[i] for i in free) not in wrong for w in compatible
                )
                for method in ("pairs", "providers"):
                    witness, _, limited = refutable(audit, frozenset(g), method)
                    assert not limited and (witness is not None) == sufficient_exists
                    if witness is not None:
                        verify_sample(audit, g, witness)
                if width == 2:
                    witness = binary_compatible(audit, g)
                    assert (witness is not None) == sufficient_exists
                    if witness is not None:
                        verify_sample(audit, g, witness)
                count += 1
    return count


def check_sat(rng):
    capped = 0
    for _ in range(100):
        n = 4
        clauses = [
            [
                i * rng.choice((-1, 1))
                for i in rng.sample(range(1, n + 1), rng.randrange(1, 4))
            ]
            for _ in range(rng.randrange(1, 10))
        ]
        ground = any(
            all(any(x[abs(i) - 1] == (i > 0) for i in clause) for clause in clauses)
            for x in product((False, True), repeat=n)
        )
        audit, hidden = sat_archive(n, clauses)
        result = binary_compatible(audit, hidden)
        reference, _, limited = refutable(audit, hidden, "pairs")
        assert (result is not None) == ground
        if limited:
            assert reference is None
            capped += 1
        else:
            assert (reference is not None) == ground
        if result is not None:
            verify_sample(audit, hidden, result)
    audit, group = sat_archive(1, [[1], [-1]])
    mask = sum(1 << i for i in group)
    assert len(audit.alternatives) == 2
    assert all(
        any(e & mask == 0 for e in edges) for edges in audit.alternatives.values()
    )
    assert refutable(audit, group, "providers")[0] is None
    return dict(total=100, bounded_search_capped=capped)


def check_clique(rng):
    for _ in range(70):
        k = rng.choice((2, 3, 4))
        width = rng.choice((2, 3))
        n = k * width
        edges = {p for p in combinations(range(1, n + 1), 2) if rng.random() < 0.45}
        expected = any(
            all(p in edges for p in combinations(items, 2))
            for items in product(
                *(range(c * width + 1, (c + 1) * width + 1) for c in range(k))
            )
        )
        audit, group = colour_archive(k, width, edges)
        result = binary_compatible(audit, group)
        assert (result is not None) == expected
        if result is not None:
            verify_sample(audit, group, result)
    return 70


if __name__ == "__main__":
    if not __debug__:
        raise RuntimeError("enable assertions")
    rng = Random(480821)
    print(
        json.dumps(
            dict(
                groups=check_domains(rng),
                sat_reductions=check_sat(rng),
                clique_reductions=check_clique(rng),
                changing_target=True,
            )
        )
    )
