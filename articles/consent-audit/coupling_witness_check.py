"""Independent portfolio, orientation, and exact transport checks on the published audit."""

import argparse
from collections import Counter
from fractions import Fraction as Q
from functools import lru_cache
from itertools import product
import json
from pathlib import Path
import shutil
import sys
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
from cover_dependence_check import validate
from go_model_fetch import verify


def clock_sweep(groups, plan):
    names = list(groups)
    spans = []
    for u in names:
        end = Q(0)
        span = []
        for vs, p in groups[u]:
            span.append((end, end + p, set(vs)))
            end += p
        assert end == 1
        spans.append(span)
    cuts = sorted(
        {Q(0), Q(1)}
        | {x for span in spans for a, b, _ in span for x in (a, b, 1 - a, 1 - b)}
    )
    cells = []
    for a, b in zip(cuts, cuts[1:]):
        midpoint = (a + b) / 2
        cells.append(
            (
                b - a,
                [
                    [
                        next(vs for s, t, vs in span if s <= z < t)
                        for z in (midpoint, 1 - midpoint)
                    ]
                    for span in spans
                ],
            )
        )

    def replay(mask):
        marg = [Counter() for _ in names]
        value = Q(0)
        for width, sides in cells:
            sets = [sides[i][(mask >> i) & 1] for i in range(len(names))]
            value += width * len(set().union(*sets))
            for m, vs in zip(marg, sets):
                m[tuple(sorted(vs))] += width
        assert all(m == dict(groups[u]) for m, u in zip(marg, names))
        return value

    values = [replay(m) for m in range(1 << len(names))]
    probs = {
        v: [sum(p for vs, p in g if v in vs) for g in groups.values()]
        for v in set().union(*(set(vs) for g in groups.values() for vs, _ in g))
    }
    for ep, local, opt in (
        ("upper", sum(min(1, sum(p)) for p in probs.values()), max(values)),
        ("lower", sum(max(p) for p in probs.values()), min(values)),
    ):
        r = plan[ep + "_clock"]
        assert Q(r["local"]) == local and r["intervals"] == len(cells)
        wide = ep == "upper" and any(
            sum(p) >= 1
            and not any(v in f and v in g for f, g in sides)
            and sum((v in f) != (v in g) for f, g in sides) > 2
            for v, p in probs.items()
            for _, sides in cells
        )
        expected = (
            "wide" if wide else "witness" if opt == local else "unsat_in_clock_family"
        )
        assert r["status"] == expected
        if expected == "witness":
            reverse = r["reverse"]
            assert len(set(reverse)) == len(reverse) and set(reverse) <= set(names)
            assert values[sum(1 << names.index(u) for u in reverse)] == local
    return len(values)


def check(archive, folder):
    if not __debug__:
        raise RuntimeError("assertions must be enabled")
    import nltk
    from nltk.corpus import wordnet as wn

    verify(archive, "3c68cd207844f071a5206f7fbed23e5c607ec02f")

    def lines(path):
        return (json.loads(l) for l in path.read_bytes().splitlines())

    old = {
        (r["source"], r["sentence"]): r
        for r in lines(ROOT / "shared-sense-ledger.jsonl")
        if r["shared"]
    }
    rows = list(lines(folder / "coupling-witness-ledger.jsonl"))
    orientations = verified_plans = certs = 0
    with TemporaryDirectory() as temp:
        p = Path(temp) / "corpora"
        p.mkdir()
        shutil.copyfile(archive, p / "wordnet.zip")
        nltk.data.path.insert(0, temp)
        try:

            @lru_cache(None)
            def senses(w):
                return tuple(wn.synsets(w, pos="n"))

            @lru_cache(None)
            def ancestors(s):
                return {v for path in s.hypernym_paths() for v in path[:-1]}

            def label(x, y):
                return (
                    0
                    if x == y
                    else 1
                    if y in ancestors(x)
                    else 2
                    if x in ancestors(y)
                    else 3
                )

            for r in rows:
                o = old.pop((r["source"], r["sentence"]))
                words = o["words"]
                vertices = sorted(words)
                matrices = {
                    (u, v): {
                        (x.offset(), y.offset()): label(x, y)
                        for x, y in product(senses(words[u]), senses(words[v]))
                    }
                    for u, v, _ in o["queries"]
                }
                edges = [e for e, tab in matrices.items() if len(set(tab.values())) > 1]
                sets = [
                    frozenset(v for i, v in enumerate(vertices) if bits >> i & 1)
                    for bits in range(1 << len(vertices))
                ]
                covers = [s for s in sets if all(s.intersection(e) for e in edges)]
                minimal = [s for s in covers if not any(t < s for t in covers)]
                plans = r["plans"]
                assert {frozenset(p["cover"]) for p in plans} == set(minimal) and len(
                    plans
                ) == len(minimal)
                for plan in plans:
                    verified_plans += 1
                    paid = set(plan["cover"])
                    groups = {}
                    actual = set()
                    for u in sorted(paid):
                        freq = Counter()
                        for x in senses(words[u]):
                            forced = set()
                            for e, m in matrices.items():
                                if u not in e:
                                    continue
                                side = e.index(u)
                                v = e[1 - side]
                                if (
                                    v not in paid
                                    and len(
                                        {
                                            res
                                            for w, res in m.items()
                                            if w[side] == x.offset()
                                        }
                                    )
                                    > 1
                                ):
                                    forced.add(v)
                            freq[tuple(sorted(forced))] += 1
                            if x.offset() == o["truth"][u]:
                                actual.update(forced)
                        groups[u] = [
                            (vs, Q(n, sum(freq.values())))
                            for vs, n in sorted(freq.items())
                        ]
                    assert plan["observed"] == len(paid) + len(actual)
                    assert list(groups) == list(plan["groups"])
                    assert all(
                        groups[u] == [(tuple(v), Q(p)) for v, p in plan["groups"][u]]
                        for u in groups
                    )
                    validate(list(groups.values()), plan)
                    certs += 2
                    targets = sorted(
                        set().union(*(set(vs) for g in groups.values() for vs, _ in g))
                    )
                    signatures = {
                        v: tuple(
                            tuple(i for i, (forced, _) in enumerate(g) if v in forced)
                            for g in groups.values()
                        )
                        for v in targets
                    }

                    def acyclic(scopes):
                        adj = {}
                        for j, patt in enumerate(scopes):
                            if any(
                                len(h) == len(g) for h, g in zip(patt, groups.values())
                            ):
                                continue
                            for i, h in enumerate(patt):
                                if h:
                                    adj.setdefault((1, j), set()).add((0, i))
                                    adj.setdefault((0, i), set()).add((1, j))
                        seen = set()
                        for node in adj:
                            if node in seen:
                                continue
                            todo = [node]
                            component = set()
                            while todo:
                                n = todo.pop()
                                if n not in component:
                                    component.add(n)
                                    todo.extend(adj[n] - component)
                            if sum(len(adj[n]) for n in component) != 2 * (
                                len(component) - 1
                            ):
                                return False
                            seen.update(component)
                        return True

                    assert acyclic(signatures.values()) == plan["forest"]
                    merged = plan["posthoc_coalesced"]
                    assert acyclic(set(signatures.values())) == (merged is not None)
                    if merged:
                        assert (
                            merged["target_count"],
                            merged["distinct_signatures"],
                        ) == (len(targets), len(set(signatures.values())))
                        assert Q(merged["minimum_extra"]) == Q(
                            plan["minimum"]["extra"]
                        ) and Q(merged["maximum_extra"]) == Q(plan["maximum"]["extra"])
                    orientations += clock_sweep(groups, plan)

                def cost(p, k):
                    return len(p["cover"]) + Q(
                        p["maximum"]["extra"] if k == "maximum" else p[k]
                    )

                for key, idx in r["chosen"].items():
                    if key == "original":
                        assert plans[idx]["cover"] == o["cover_first_stage"]
                        continue
                    assert plans[idx] == min(
                        plans, key=lambda p: (cost(p, key), len(p["cover"]), p["cover"])
                    )
                sel = r["chosen"]["local_upper"]
                upper = cost(plans[sel], "local_upper")
                for k, flags in (
                    ("independence_proves_optimal", ()),
                    ("forest_proves_optimal", ("forest",)),
                    ("clock_proves_optimal", ("clock",)),
                    ("forest_or_clock_proves_optimal", ("clock", "forest")),
                ):

                    def lb(p):
                        exact = (
                            "clock" in flags
                            and p["upper_clock"]["status"] == "witness"
                            or "forest" in flags
                            and p["forest"]
                        )
                        return cost(p, "local_upper" if exact else "independent")

                    ok = all(upper <= lb(p) for i, p in enumerate(plans) if i != sel)
                    assert ok == r[k]
                    if ok:
                        assert cost(plans[sel], "maximum") == min(
                            cost(p, "maximum") for p in plans
                        )
                assert r["planner"]["cover"] == plans[sel]["cover"]
                assert (
                    r["planner"]["certified_optimal"]
                    == r["forest_or_clock_proves_optimal"]
                )
        finally:
            nltk.data.path.remove(temp)
    assert not old
    results = json.loads((folder / "coupling-witness-results.json").read_bytes())
    for src, summary in results.items():
        subset = [r for r in rows if r["source"] == src]
        assert len(subset) == summary["sentences"]
        for key in ("original", "maximum", "independent", "local_upper"):
            sel = [r["plans"][r["chosen"][key]] for r in subset]
            ref = [
                min(len(p["cover"]) + Q(p["maximum"]["extra"]) for p in r["plans"])
                for r in subset
            ]
            vals = [len(p["cover"]) + Q(p["maximum"]["extra"]) for p in sel]
            stats = summary["choice"][key]
            assert (
                sum(vals) == Q(stats["sum_worst_expectation"])
                and sum(p["observed"] for p in sel) == stats["actual_reveals"]
            )
            assert sum(x == y for x, y in zip(vals, ref)) == stats["attains_optimum"]
        for label, ps in (
            ("fixed", [r["plans"][r["chosen"]["original"]] for r in subset]),
            ("all_plans", [p for r in subset for p in r["plans"]]),
        ):
            s = summary[label]
            assert s["plans"] == len(ps) and s["forest"] == sum(p["forest"] for p in ps)
            assert s["posthoc_coalesced_exact"] == sum(
                p["posthoc_coalesced"] is not None for p in ps
            )
            assert s["posthoc_coalesced_or_clock_upper"] == sum(
                p["posthoc_coalesced"] is not None
                or p["upper_clock"]["status"] == "witness"
                for p in ps
            )
            for ep in ("upper", "lower"):
                assert s[ep + "_status"] == dict(
                    Counter(p[ep + "_clock"]["status"] for p in ps)
                )
            assert s["upper_added_to_forest"] == sum(
                not p["forest"] and p["upper_clock"]["status"] == "witness" for p in ps
            )
            assert s["both_added_to_forest"] == sum(
                not p["forest"]
                and p["upper_clock"]["status"]
                == p["lower_clock"]["status"]
                == "witness"
                for p in ps
            )
            assert s["upper_genuinely_loose"] == sum(
                Q(p["local_upper"]) > Q(p["maximum"]["extra"]) for p in ps
            )
            assert s["lower_genuinely_loose"] == sum(
                Q(p["lower_clock"]["local"]) < Q(p["minimum"]["extra"]) for p in ps
            )
        for key, status in (
            ("independence_only", "independence_proves_optimal"),
            ("forest", "forest_proves_optimal"),
            ("clock", "clock_proves_optimal"),
            ("forest_or_clock", "forest_or_clock_proves_optimal"),
        ):
            assert summary["optimality_certified_" + key] == sum(
                r[status] for r in subset
            )
    return {
        "sentence_instances": len(rows),
        "all_minimal_plans": verified_plans,
        "exact_lp_certificates": certs,
        "independently_enumerated_clock_orientations": orientations,
    }


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("wordnet", type=Path)
    p.add_argument("directory", type=Path)
    a = p.parse_args()
    print(json.dumps(check(a.wordnet, a.directory), indent=2))
