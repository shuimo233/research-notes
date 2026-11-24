"""Independent corpus check using unreduced action choices, full outcome masks and NLTK relation tables."""

import argparse
from collections import Counter, defaultdict
from fractions import Fraction as Q
from functools import lru_cache
from itertools import combinations, product
from math import prod
from pathlib import Path
import json
import shutil
import sys
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
from go_model_fetch import verify
from frontier_theory_check import raw_optimum
from frontier_rate_check import all_actions, verify_completions


def check(wordnet, folder, information=None):
    if not __debug__:
        raise RuntimeError("enable assertions")
    import nltk
    from nltk.corpus import wordnet as wn

    verify(wordnet, "3c68cd207844f071a5206f7fbed23e5c607ec02f")

    def lines(path):
        return [json.loads(l) for l in path.read_bytes().splitlines()]

    fits = lines(ROOT / "heldout-triangle-plans.jsonl")
    bank = defaultdict(list)
    for r, t in zip(
        lines(ROOT / "natural-triangle-cases.jsonl"),
        lines(ROOT / "heldout-triangle-cases.jsonl"),
        strict=True,
    ):
        assert r["ids"] == t["ids"] and r["sentence"] == t["sentence"]
        bank[r["source"], r["group"], r["sentence"]].append((r, fits[t["context"]]))
    cached = {
        (r["source"], r["group"], r["sentence"]): len(r["forward"]["fitted"])
        for r in lines(ROOT / "cached-triangle-ledger.jsonl")
    }
    outputs = lines(folder / "frontier-ledger.jsonl")
    exact = literal = edges_checked = steps = 0
    supplements = (
        {}
        if information is None
        else {
            (r["source"], r["group"], r["sentence"]): r
            for r in lines(information / "frontier-information-ledger.jsonl")
        }
    )
    original_supplements = list(supplements.values())
    with TemporaryDirectory() as temp:
        d = Path(temp) / "corpora"
        d.mkdir()
        shutil.copyfile(wordnet, d / "wordnet.zip")
        nltk.data.path.insert(0, temp)
        try:

            @lru_cache(None)
            def senses(w):
                return {x.offset(): x for x in wn.synsets(w, pos="n")}

            @lru_cache(None)
            def ancestors(x):
                return {s for path in x.hypernym_paths() for s in path[:-1]}

            def label(x, y):
                if x == y:
                    return "same"
                if y in ancestors(x):
                    return "left_narrower"
                if x in ancestors(y):
                    return "right_narrower"
                return "neither"

            @lru_cache(None)
            def grid(a, b):
                return {
                    (x, y): label(s, t)
                    for x, s in senses(a).items()
                    for y, t in senses(b).items()
                }

            for row in outputs:
                k = row["source"], row["group"], row["sentence"]
                rows = bank.pop(k)
                words = {}
                train = {}
                truth = {}
                required = set()
                for r, fit in rows:
                    words.update(zip(r["ids"], r["words"]))
                    truth.update(zip(r["ids"], r["truth"]))
                    train.update(fit["training"])
                    required.update(tuple(sorted(t)) for t in combinations(r["ids"], 2))
                labels = {
                    e: grid(words[e[0]], words[e[1]])[truth[e[0]], truth[e[1]]]
                    for e in required
                }
                edges_checked += len(required)
                names = sorted(set(words.values()))
                n = len(names)
                mult = tuple(sum(w == v for w in words.values()) for v in names)
                assert (
                    row["classes"] == n
                    and row["positions"] == len(words)
                    and row["edges"] == len(required)
                    and row["cached"] == cached.pop(k)
                )
                arcs = {
                    tuple(sorted((names.index(words[u]), names.index(words[v]))))
                    for u, v in required
                }
                neighbor = [
                    {v for e in arcs if i in e for v in e if v != i} for i in range(n)
                ]
                for i, j in arcs:
                    assert all(
                        tuple(sorted((u, v))) in required
                        for u in words
                        if words[u] == names[i]
                        for v in words
                        if words[v] == names[j]
                    )
                masks = []
                options = []
                probs = []
                for i, u in enumerate(names):
                    full = {}
                    freq = Counter()
                    ps = {int(x): c + 1 for x, c in train[u].items()}
                    assert set(ps) == senses(u).keys()
                    for x, p in ps.items():
                        targets = {
                            j
                            for j in neighbor[i]
                            if len({grid(u, names[j])[x, y] for y in senses(names[j])})
                            > 1
                        }
                        full[x] = sum(1 << j for j in targets)
                        freq[full[x]] += p
                    masks.append(full)
                    options.append(
                        tuple((f, Q(v, sum(ps.values()))) for f, v in freq.items())
                    )
                    probs.append({x: Q(v, sum(ps.values())) for x, v in ps.items()})
                occ = {u: names.index(w) for u, w in words.items()}

                def answers(path):
                    assert len(path) == len(set(path)) and set(path) <= words.keys()
                    known = set(path)
                    for (u, v), val in labels.items():
                        a = words[u]
                        b = words[v]
                        xs = [truth[u]] if u in known else senses(a)
                        ys = [truth[v]] if v in known else senses(b)
                        assert {grid(a, b)[x, y] for x, y in product(xs, ys)} == {val}

                for mode in ("oracle", "greedy", "optimal", "fixed"):
                    answers(row[mode])
                mandatory = {
                    v for u, v in required if masks[occ[u]][truth[u]] >> occ[v] & 1
                } | {u for u, v in required if masks[occ[v]][truth[v]] >> occ[u] & 1}

                @lru_cache(None)
                def mincover(es):
                    if not es:
                        return 0
                    return 1 + min(
                        mincover(tuple(e for e in es if u not in e)) for u in es[0]
                    )

                assert len(row["oracle"]) == len(mandatory) + mincover(
                    tuple(sorted(e for e in required if not mandatory.intersection(e)))
                )
                mincover.cache_clear()
                safe = [
                    prod(
                        (1 - sum(p for f, p in options[j] if f >> i & 1)) ** mult[j]
                        for j in neighbor[i]
                    )
                    for i in range(n)
                ]

                @lru_cache(None)
                def independent(left):
                    if not left:
                        return Q(0)
                    i, *rest = left
                    return max(
                        independent(tuple(rest)),
                        mult[i] * safe[i]
                        + independent(tuple(j for j in rest if j not in neighbor[i])),
                    )

                assert Q(row["expected_fixed"]) == sum(mult) - independent(
                    tuple(range(n))
                )
                independent.cache_clear()
                if row["expected_optimal"] is None:
                    continue
                exact += 1
                # All actions remain competitors even when another vertex is already mandatory.
                value, after = all_actions(options, neighbor)
                v = value(mult, 0)
                assert v == Q(row["expected_optimal"]), (k, v, row["expected_optimal"])
                remaining = mult
                forced = 0
                for u in row["optimal"]:
                    i = occ[u]
                    assert after(i, remaining, forced) == value(remaining, forced)
                    before = remaining
                    remaining = tuple(c - int(j == i) for j, c in enumerate(before))
                    forced = (forced | masks[i][truth[u]]) & sum(
                        1 << j for j, c in enumerate(remaining) if c
                    )
                    steps += 1
                assert value(remaining, forced) == 0
                value.cache_clear()
                after.cache_clear()
                if information is not None:
                    rec = supplements.pop(k)
                    assert rec["gold"] == len(row["optimal"])
                    splits = changed = 0
                    graph = {
                        a: {b for e in required if a in e for b in e if b != a}
                        for a in words
                    }
                    for i, actual in enumerate(options):
                        u = min(a for a in words if occ[a] == i)
                        unreached = set(graph[u])
                        projections = []
                        while unreached:
                            comp = {min(unreached)}
                            while True:
                                grow = comp | (
                                    set().union(*(graph[a] for a in comp)) - {u}
                                )
                                if grow == comp:
                                    break
                                comp = grow
                            group = comp & unreached
                            unreached -= group
                            mask = sum(1 << j for j in {occ[a] for a in group})
                            local = Counter()
                            for f, p in sorted(actual):
                                local[f & mask] += p
                            projections.append(local)
                        splits += len(projections) > 1
                        cuts = {Q(0), Q(1)}
                        segments = []
                        for local in projections:
                            t = Q(0)
                            intervals = []
                            for f, p in local.items():
                                intervals.append((t, t + p, f))
                                t += p
                                cuts.add(t)
                            segments.append(intervals)
                        replacement = Counter()
                        cuts = sorted(cuts)
                        for a, b in zip(cuts, cuts[1:]):
                            mask = sum(
                                next(f for lo, hi, f in ls if lo <= (a + b) / 2 < hi)
                                for ls in segments
                            )
                            replacement[mask] += b - a
                        changed += dict(actual) != dict(replacement)
                    assert (splits, changed) == (
                        rec["types_with_split_scopes"],
                        rec["types_with_changed_cross_block_law"],
                    ), (k, splits, changed)
                    verify_completions(
                        rec,
                        v,
                        options,
                        neighbor,
                        mult,
                        [
                            sorted(u for u in words if words[u] == name)
                            for name in names
                        ],
                        {u: masks[occ[u]][truth[u]] for u in words},
                    )
                ids = sorted(words)
                if prod(1 + len(senses(words[u])) for u in ids) <= 3000:
                    ds = [list(senses(words[u])) for u in ids]
                    tables = {
                        (a, b): [
                            [grid(words[ids[a]], words[ids[b]])[x, y] for y in ds[b]]
                            for x in ds[a]
                        ]
                        for a, b in combinations(range(len(ids)), 2)
                        if (ids[a], ids[b]) in required
                    }
                    ps = [[probs[occ[u]][x] for x in xs] for u, xs in zip(ids, ds)]
                    assert raw_optimum(ps, tables, [1] * len(ids)) == v
                    literal += 1
        finally:
            nltk.data.path.remove(temp)
    assert not bank and not cached
    report = json.loads((folder / "frontier-results.json").read_bytes())
    for src, groups in report.items():
        for scope, t in groups.items():
            selected = [
                r for r in outputs if r["source"] == src and r["group"] == scope
            ]
            certified = [r for r in selected if r["expected_optimal"] is not None]
            totals = {
                mode: sum(len(r[mode]) for r in selected)
                for mode in ("optimal", "greedy", "fixed", "oracle")
            }
            c = sum(r["cached"] for r in selected)
            assert (
                all(t[m] == v for m, v in totals.items())
                and t["realized_cached"] == c
                and len(selected) == t["sentences"]
                and len(certified) == t["certified_roots"]
            )
            assert t["observed_fallback_sentences"] == sum(
                bool(r["fallback_decisions"]) for r in selected
            )
            assert t["primary_gate"] == (
                bool(selected)
                and totals["optimal"] * 100 <= 99 * c
                and totals["optimal"] < totals["greedy"]
            )
            assert all(
                Q(t["expected_" + f + "_on_certified"])
                == sum(Q(r["expected_" + f]) for r in certified)
                for f in ("optimal", "fixed")
            )
            assert t["strict_model_advantage_over_fixed"] == sum(
                Q(r["expected_optimal"]) < Q(r["expected_fixed"]) for r in certified
            )
            assert t["realized_versus_cached"] == {
                "fewer": sum(len(r["optimal"]) < r["cached"] for r in selected),
                "more": sum(len(r["optimal"]) > r["cached"] for r in selected),
            }
            assert t["maximum_states"] == max(
                (r["states"] for r in selected), default=0
            )
    assert not supplements
    if information is not None:
        info = json.loads(
            (information / "frontier-information-results.json").read_bytes()
        )
        for src, groups in info.items():
            for group, comparisons in groups.items():
                sel = [
                    r
                    for r in original_supplements
                    if r["source"] == src and r["group"] == group
                ]
                for mode, result in comparisons.items():
                    regret = [
                        Q(r[mode]["actual_expected"]) - Q(r["exact"]) for r in sel
                    ]
                    assert all(d >= 0 for d in regret)
                    expected = {
                        "cases": len(sel),
                        "incorrect_forecast": sum(
                            r[mode]["forecast"] != r["exact"] for r in sel
                        ),
                        "strict_expected_regret": sum(d > 0 for d in regret),
                        "summed_regret": str(sum(regret)),
                        "gold_queries": sum(r[mode]["queries"] for r in sel),
                        "exact_gold": sum(r["gold"] for r in sel),
                    }
                    if mode == "block":
                        expected.update(
                            sentences_with_split_scopes=sum(
                                bool(r["types_with_split_scopes"]) for r in sel
                            ),
                            sentences_replacing_cross_block_law=sum(
                                bool(r["types_with_changed_cross_block_law"])
                                for r in sel
                            ),
                        )
                    assert result == expected
    return {
        "sentences": len(outputs),
        "relations": edges_checked,
        "alternative_exact_roots": exact,
        "certified_optimal_trace_steps": steps,
        "raw_history_roots": literal,
        "checked_scalar_completions": 2 * len(original_supplements),
    }


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("wordnet", type=Path)
    p.add_argument("folder", type=Path)
    p.add_argument("--information", type=Path)
    a = p.parse_args()
    print(json.dumps(check(a.wordnet, a.folder, a.information), indent=2))
