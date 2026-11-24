"""Independently enumerate possible answers and all shared-token certificates."""

import argparse
import csv
from collections import defaultdict
from fractions import Fraction
from functools import lru_cache
from itertools import product
import json
from pathlib import Path
import shutil
import sys
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
from go_model_fetch import verify

SERIAL = ("forward_table", "forward_more", "reverse_table", "reverse_more")


def check(archive, directory):
    if not __debug__:
        raise ValueError("assertions must be enabled")
    import nltk
    from nltk.corpus import wordnet as wn

    verify(archive, "3c68cd207844f071a5206f7fbed23e5c607ec02f")
    rows = [
        json.loads(l)
        for l in (directory / "shared-sense-ledger.jsonl").read_bytes().splitlines()
    ]
    result = json.loads((directory / "shared-sense-results.json").read_bytes())
    intake = defaultdict(dict)
    nsets = ntraces = 0
    with TemporaryDirectory() as tmp:
        p = Path(tmp) / "corpora"
        p.mkdir()
        shutil.copyfile(archive, p / "wordnet.zip")
        nltk.data.path.insert(0, tmp)
        try:

            @lru_cache(None)
            def senses(w):
                return {s.offset(): s for s in wn.synsets(w, pos="n")}

            @lru_cache(None)
            def ancestors(s):
                return {v for path in s.hypernym_paths() for v in path[:-1]}

            for line in (
                (ROOT / "wsd-clarification-ledger.jsonl").read_bytes().splitlines()
            ):
                r = json.loads(line)
                if r["broad"] and len(r["worlds"]) == 1:
                    x, y, lab, _ = r["worlds"][0]
                    intake["wsd", r["sentence"]][tuple(r["ids"])] = (
                        tuple(r["words"]),
                        (x, y),
                        lab,
                    )
            with (ROOT / "semcor-clarification-ledger.tsv").open(
                encoding="utf8", newline=""
            ) as f:
                for r in csv.DictReader(f, delimiter="\t"):
                    w = tuple(r[k + "_word"] for k in ("left", "right"))
                    if all(len(senses(v)) > 1 for v in w):
                        edge = tuple(
                            r[k + "_position"].zfill(4) for k in ("left", "right")
                        )
                        intake["semcor", r["document"] + "/" + r["sentence"]][edge] = (
                            w,
                            tuple(int(r[k + "_offset"]) for k in ("left", "right")),
                            r["relation"],
                        )
            for r in rows:
                orig = intake.pop((r["source"], r["sentence"]))
                edges = [(u, v) for u, v, _ in r["queries"]]
                assert edges == sorted(orig, key=lambda e: sorted(e))
                labels = {tuple(q[:2]): q[2] for q in r["queries"]}
                words, truth = r["words"], r["truth"]
                vertices = sorted(set().union(*edges))
                assert set(vertices) == words.keys() == truth.keys()
                assert r["shared"] == (len(vertices) < 2 * len(edges))
                bits = {v: 1 << i for i, v in enumerate(vertices)}
                determined = {}
                rates = {}
                for u, v in edges:
                    e = u, v
                    assert (
                        (words[u], words[v]),
                        (truth[u], truth[v]),
                        labels[e],
                    ) == orig[e]
                    l, h = senses(words[u]), senses(words[v])
                    matrix = {
                        (x, y): "same"
                        if a == b
                        else "left_narrower"
                        if b in ancestors(a)
                        else "right_narrower"
                        if a in ancestors(b)
                        else "neither"
                        for (x, a), (y, b) in product(l.items(), h.items())
                    }
                    assert matrix[truth[u], truth[v]] == labels[e]
                    constant = len(set(matrix.values())) == 1
                    left = {x for x in l if len({matrix[x, y] for y in h}) == 1}
                    right = {y for y in h if len({matrix[x, y] for x in l}) == 1}
                    determined[e] = {
                        0: constant,
                        bits[u]: truth[u] in left,
                        bits[v]: truth[v] in right,
                        bits[u] | bits[v]: True,
                    }
                    rates[e] = {
                        u: Fraction(len(left), len(l)),
                        v: Fraction(len(right), len(h)),
                    }

                def pending(mask):
                    return [
                        e
                        for e in edges
                        if not determined[e][mask & (bits[e[0]] | bits[e[1]])]
                    ]

                masks = range(1 << len(vertices))
                nsets += len(masks)
                covers = [
                    m
                    for m in masks
                    if all(m & (bits[u] | bits[v]) for u, v in pending(0))
                ]
                first = min(
                    (tuple(v for v in vertices if m & bits[v]) for m in covers),
                    key=lambda vs: (len(vs), vs),
                )
                assert tuple(r["cover_first_stage"]) == first
                optimum = min(m.bit_count() for m in masks if not pending(m))
                cert = r["certificate"]
                assert len(set(cert)) == len(cert) == optimum and not pending(
                    sum(bits[u] for u in cert)
                )

                def preferred(e, mode):
                    u, v = e
                    pref = (
                        rates[e]
                        if mode == "table"
                        else {s: len(senses(words[s])) for s in e}
                    )
                    return v if pref[v] > pref[u] else u

                assert r["uncached"] == sum(
                    1 + (not determined[e][bits[preferred(e, "table")]])
                    for e in pending(0)
                )
                for policy, trace in r["traces"].items():
                    mask = 0
                    for asked in trace:
                        live = pending(mask)
                        assert live and not mask & bits[asked]
                        if policy in SERIAL:
                            order, mode = policy.split("_")
                            e = live[0 if order == "forward" else -1]
                            cand = [u for u in e if not mask & bits[u]]
                            expect = cand[0] if len(cand) == 1 else preferred(e, mode)
                        else:
                            assert policy in ("cover", "greedy")
                            pool = set().union(*live) - {
                                u for u in vertices if mask & bits[u]
                            }
                            if policy == "cover" and set(first) & pool:
                                pool &= set(first)

                            def key(u):
                                incident = [e for e in live if u in e]
                                gain = sum(
                                    1 if any(mask & bits[v] for v in e) else rates[e][u]
                                    for e in incident
                                )
                                return -gain, -len(incident), u

                            expect = min(pool, key=key)
                        assert asked == expect
                        mask |= bits[asked]
                    assert not pending(mask)
                    ntraces += 1
                assert set(r["traces"]) == set((*SERIAL, "greedy", "cover"))
                assert len(r["traces"]["cover"]) <= 2 * optimum
        finally:
            nltk.data.path.remove(tmp)
    assert not intake
    for source, sections in result.items():
        for label, s in sections.items():
            selected = [
                r
                for r in rows
                if r["source"] == source and (label == "all" or r["shared"])
            ]
            assert s["sentences"] == len(selected) and s["relations"] == sum(
                len(r["queries"]) for r in selected
            )
            for k in (*SERIAL, "greedy", "cover"):
                assert s["totals"][k] == sum(len(r["traces"][k]) for r in selected)
            assert s["uncached"] == sum(r["uncached"] for r in selected)
            assert s["offline_minimum"] == sum(len(r["certificate"]) for r in selected)
            assert s["distinct_positions_summed"] == sum(
                len(r["words"]) for r in selected
            )
            assert s["cover_exact_sentences"] == sum(
                len(r["traces"]["cover"]) == len(r["certificate"]) for r in selected
            )
            ratios = [
                Fraction(len(r["traces"]["cover"]), len(r["certificate"]))
                for r in selected
                if r["certificate"]
            ]
            assert s["maximum_cover_ratio"] == (str(max(ratios)) if ratios else None)
            assert s["cover_beats_best_serial_total"] == (
                bool(selected)
                and s["totals"]["cover"] < min(s["totals"][p] for p in SERIAL)
            )
    return {
        "sentence_batches": len(rows),
        "candidate_token_subsets_enumerated": nsets,
        "independently_replayed_traces": ntraces,
        "corpus_source_relations": sum(len(r["queries"]) for r in rows),
    }


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    for name in ("wordnet", "directory"):
        p.add_argument(name, type=Path)
    a = p.parse_args()
    print(json.dumps(check(a.wordnet, a.directory), indent=2))
