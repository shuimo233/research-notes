"""Rebuild the chain census via NLTK pair joins, and evaluate observed-marginal games by direct LP."""

import argparse
from collections import defaultdict, Counter
from fractions import Fraction as Q
from itertools import product
from pathlib import Path
from tempfile import TemporaryDirectory
import json
import shutil
from zipfile import ZipFile
import sys

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
from go_model_fetch import verify


def check(archive, report):
    if not __debug__:
        raise RuntimeError("enable assertions")
    import nltk
    from nltk.corpus import wordnet as wn
    from scipy.optimize import linprog

    verify(archive, "3c68cd207844f071a5206f7fbed23e5c607ec02f")
    saved = json.loads(report.read_bytes())
    counts = {}
    frequency = Counter()
    with ZipFile(archive) as z:
        for line in z.read("wordnet/index.sense").decode().splitlines():
            lemma, offset, _, n = line.split()
            if "%1:" in lemma:
                counts[lemma.split("%")[0], int(offset)] = int(n)
        for line in z.read("wordnet/cntlist.rev").decode().splitlines():
            key, _, n = line.split()
            if "%1:" in key:
                frequency[key.split("%")[0]] += int(n)
    with TemporaryDirectory() as temp:
        p = Path(temp) / "corpora"
        p.mkdir()
        shutil.copyfile(archive, p / "wordnet.zip")
        nltk.data.path.insert(0, temp)
        try:
            senses = {
                u: set(wn.synsets(u, pos="n"))
                for u in sorted(wn.all_lemma_names(pos="n"))
                if u.isascii() and u.isalpha() and frequency[u] > 0
            }
            senses = {u: ss for u, ss in senses.items() if len(ss) == 2}
            assert len(senses) == saved["eligible_two_sense_lemmas"]
            owners = defaultdict(set)
            for u, ss in senses.items():
                for s in ss:
                    owners[s].add(u)
            ancestors = {
                s: {a for path in s.hypernym_paths() for a in path[:-1]} for s in owners
            }
            edges = defaultdict(dict)
            for u, ss in senses.items():
                for v in set().union(
                    *(owners.get(a, set()) for x in ss for a in ancestors[x])
                ):
                    if u == v:
                        continue
                    hits = [
                        (x, y)
                        for x in ss
                        for y in senses[v]
                        if x == y or x in ancestors[y] or y in ancestors[x]
                    ]
                    if len(hits) == 1 and hits[0][1] in ancestors[hits[0][0]]:
                        edges[u][v] = hits[0]
            triples = {}
            for a, ends in list(edges.items()):
                for b, (x, y) in ends.items():
                    for c in ends.keys() & edges.get(b, {}).keys():
                        w, z = edges[b][c]
                        if y == w and ends[c] == (x, z):
                            triples[a, b, c] = (x, y, z)
            assert len(triples) == saved["matching_specific_to_general_triples"]

            def rank(names):
                return (
                    -min(frequency[u] for u in names),
                    -sum(frequency[u] for u in names),
                    *names,
                )

            best = min(triples, key=rank)
            assert (
                list(best) == saved["example"]["words"]
                and [s.offset() for s in triples[best]]
                == saved["example"]["active_offsets"]
            )
            observed = {}
            for names, syns in triples.items():
                pairs = [
                    (
                        counts.get((u, s.offset()), 0),
                        counts.get((u, next(iter(senses[u] - {s})).offset()), 0),
                    )
                    for u, s in zip(names, syns)
                ]
                if min(min(pair) for pair in pairs) > 0:
                    observed[names] = pairs
        finally:
            nltk.data.path.remove(temp)
    assert (
        saved["both_senses_observed"] == len(observed) == len(saved["empirical_cases"])
    )
    worlds = list(product((0, 1), repeat=3))
    payoff = [
        [3 - int(all(not b for j, b in enumerate(w) if j != i)) for w in worlds]
        for i in range(3)
    ]
    eq = [[1] * 8] + [[w[i] for w in worlds] for i in range(3)]

    def evaluate(ps):
        b = list(map(float, (1, *ps)))
        pure = []
        for row in payoff:
            lp = linprog([-x for x in row], A_eq=eq, b_eq=b, method="highs")
            assert lp.success
            pure.append(-lp.fun)
        lp = linprog(
            [0] * 8 + [-1],
            A_eq=[r + [0] for r in eq],
            b_eq=b,
            A_ub=[[-x for x in r] + [1] for r in payoff],
            b_ub=[0] * 3,
            method="highs",
        )
        assert lp.success
        return min(pure), -lp.fun

    pure, mixed = evaluate([Q(1, 2)] * 3)
    assert abs(pure - 3) < 1e-10 and abs(mixed - 17 / 6) < 1e-10
    strict = shift = retained = ample = ample_strict = 0
    gain = Q(0)
    for r in saved["empirical_cases"]:
        names = tuple(r["words"])
        pairs = observed.pop(names)
        assert list(map(list, pairs)) == r["active_inactive_counts"]
        assert [s.offset() for s in triples[names]] == r["active_offsets"]
        ps = [Q(x, x + y) for x, y in pairs]
        assert ps == [Q(r["active_marginals"][u]) for u in names]
        delta = Q(r["pure_cost"]) - Q(r["mixed_cost"])
        gain += delta
        shifted = Q(r["upper_shifted_pure"]) > Q(r["upper_shifted_mixed"])
        for prob, a, b in (
            (ps, "pure_cost", "mixed_cost"),
            (
                [min(1, p + Q(1, 20)) for p in ps],
                "upper_shifted_pure",
                "upper_shifted_mixed",
            ),
        ):
            v, w = evaluate(prob)
            assert abs(v - float(Q(r[a]))) < 1e-10 and abs(w - float(Q(r[b]))) < 1e-10
        strict += delta > 0
        shift += shifted
        retained += delta > 0 and shifted
        enough = min(min(pair) for pair in pairs) >= 5
        ample += enough
        ample_strict += enough and delta > 0
    assert not observed and gain == Q(saved["empirical_marginal_total_gap"])
    assert [strict, shift, retained, ample, ample_strict] == [
        saved[k]
        for k in (
            "empirical_marginal_strict",
            "plus_five_points_strict",
            "retained_after_shift",
            "at_least_five_per_sense",
            "at_least_five_per_sense_strict",
        )
    ]
    print(
        f"{len(triples)} WordNet triangles; {len(saved['empirical_cases'])} positive-count marginals checked at both settings; {strict} nominal strict gains"
    )


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("wordnet", type=Path)
    p.add_argument("report", type=Path)
    args = p.parse_args()
    check(args.wordnet, args.report)
