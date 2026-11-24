"""Independently check Raganato intake, all stopping certificates and aggregate bounds."""

import argparse
from collections import Counter
from fractions import Fraction
from functools import lru_cache
from itertools import combinations, product
import json
from pathlib import Path
import shutil
import sys
from tempfile import TemporaryDirectory
from xml.dom.minidom import parse

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
from go_model_fetch import verify

LABELS = ("same", "left_narrower", "right_narrower", "neither")
POLICIES = ("table", "left", "right", "fewer", "more")
QUESTIONS = ("relation", "left_narrower", "right_narrower", "comparable")


def observed_costs(world, question, both):
    traces = world[3][question]
    counts = dict(zip(POLICIES, (len(t.strip("-")) for t in traces), strict=True))
    counts["coin"] = Fraction(counts["left"] + counts["right"], 2)
    counts["oracle"] = min(counts["left"], counts["right"])
    counts["both"] = both
    return counts


def check_summary(published, cases):
    single = [c for c in cases if len(c["worlds"]) == 1]
    many = [c for c in cases if len(c["worlds"]) != 1]
    assert (published["items"], published["single"], published["multiple"]) == (
        len(cases),
        len(single),
        len(many),
    )
    assert published["distinct_pairs"] == len({tuple(c["words"]) for c in cases})
    assert published["multiple_with_unique_relation"] == sum(
        len({w[2] for w in c["worlds"]}) == 1 for c in many
    )
    for q in QUESTIONS:
        stats = published["single_gold"][q]
        for p, value in stats["total"].items():
            assert Fraction(value) == sum(
                observed_costs(c["worlds"][0], q, c["both"])[p] for c in single
            )
        for label in LABELS:
            members = [c for c in single if c["worlds"][0][2] == label]
            strata = stats["by_relation"][label]
            assert strata["items"] == len(members)
            for p in ("table", "oracle", "both"):
                assert strata[p] == sum(
                    observed_costs(c["worlds"][0], q, c["both"])[p] for c in members
                )
        strict = [c for c in single if c["worlds"][0][2] in LABELS[1:3]]
        deltas = [
            (
                observed_costs(c["worlds"][0], "relation", c["both"]),
                observed_costs(c["worlds"][0], q, c["both"]),
            )
            for c in strict
        ]
        assert stats["strict_worlds_with_shorter_certificate_than_four_way"] == sum(
            y["oracle"] < x["oracle"] for x, y in deltas
        )
        assert stats["strict_worlds_with_fewer_table_reveals_than_four_way"] == sum(
            y["table"] < x["table"] for x, y in deltas
        )
        assert stats["strict_worlds_with_more_table_reveals_than_four_way"] == sum(
            y["table"] > x["table"] for x, y in deltas
        )
        positives = [c for c in strict if c["worlds"][0][2] == q]
        assert stats["affirmative_singleton_identity_checks"] == len(positives)
        for c in positives:
            w = c["worlds"][0]
            assert (
                observed_costs(w, "relation", c["both"])["oracle"]
                == observed_costs(w, q, c["both"])["oracle"]
            )
        for key, bounds in published["multi_gold_sum_of_case_bounds"][q].items():
            intervals = []
            for c in many:
                values = [
                    observed_costs(w, q, c["both"])[key.split("_")[0]]
                    for w in c["worlds"]
                ]
                if key.endswith("_savings"):
                    values = [c["both"] - cost for cost in values]
                intervals.append((min(values), max(values)))
            assert bounds == [sum(v[i] for v in intervals) for i in (0, 1)]


def check(wordnet, data, output):
    if not __debug__:
        raise RuntimeError("run without -O to check every assertion")
    import nltk
    from nltk.corpus import wordnet as wn
    from nltk.corpus.reader.wordnet import WordNetError

    verify(wordnet, "3c68cd207844f071a5206f7fbed23e5c607ec02f")
    verify(data / "ALL.data.xml", "7d5cb8f9f6a1055091976a6816288a621475b41f")
    verify(data / "ALL.gold.key.txt", "d5bd595ebb0d83a149f8a2dc09851f23fc1521f1")
    records = [
        json.loads(x)
        for x in (output / "wsd-clarification-ledger.jsonl").read_bytes().splitlines()
    ]
    remaining = {tuple(r["ids"]): r for r in records}
    assert len(remaining) == len(records)
    report = json.loads((output / "wsd-clarification-results.json").read_bytes())
    assert report["policy_order_in_ledger"] == list(POLICIES)
    frozen = {
        tuple(json.loads(s)["words"])
        for s in (ROOT / "wordnet-conflict-ledger.jsonl").read_bytes().splitlines()
    }
    gold = {
        fields[0]: fields[1:]
        for line in (data / "ALL.gold.key.txt").read_text(encoding="utf8").splitlines()
        if (fields := line.split())
    }
    census = {}
    checks = worlds_count = 0
    with TemporaryDirectory() as temp:
        corpus = Path(temp) / "corpora"
        corpus.mkdir()
        shutil.copyfile(wordnet, corpus / "wordnet.zip")
        nltk.data.path.insert(0, temp)
        try:

            @lru_cache(None)
            def senses(word):
                return {s.offset(): s for s in wn.synsets(word, pos="n")}

            @lru_cache(None)
            def ancestors(node):
                return {v.offset() for path in node.hypernym_paths() for v in path[:-1]}

            @lru_cache(None)
            def reachable(word):
                return set().union(*(ancestors(v) for v in senses(word).values()))

            @lru_cache(512)
            def model(a, b):
                left, right = senses(a), senses(b)
                matrix = {
                    (x, y): 0
                    if x == y
                    else 1
                    if y in ancestors(left[x])
                    else 2
                    if x in ancestors(right[y])
                    else 3
                    for x, y in product(left, right)
                }
                questions = {}
                for q, mapping in zip(
                    QUESTIONS,
                    ((0, 1, 2, 3), (0, 1, 0, 0), (0, 0, 1, 0), (0, 1, 1, 0)),
                    strict=True,
                ):
                    outcomes = {k: mapping[v] for k, v in matrix.items()}
                    constant = len(set(outcomes.values())) == 1
                    flat = (
                        {x for x in left if len({outcomes[x, y] for y in right}) == 1},
                        {y for y in right if len({outcomes[x, y] for x in left}) == 1},
                    )
                    nl, nr = len(left), len(right)
                    pref = (
                        int(len(flat[1]) * nl > len(flat[0]) * nr),
                        0,
                        1,
                        int(nl > nr),
                        int(nl < nr),
                    )
                    questions[q] = constant, flat, pref
                return matrix, questions

            with parse(str(data / "ALL.data.xml")) as tree:
                for doc in tree.getElementsByTagName("text"):
                    src = doc.getAttribute("id").split(".")[0]
                    counts = census.setdefault(src, Counter(unmappable_noun_targets=0))
                    counts["documents"] += 1
                    for sent in doc.getElementsByTagName("sentence"):
                        counts["sentences"] += 1
                        candidates = {}
                        for token in sent.getElementsByTagName("instance"):
                            if token.getAttribute("pos") != "NOUN":
                                continue
                            counts["noun_targets"] += 1
                            w, ident = (
                                token.getAttribute("lemma"),
                                token.getAttribute("id"),
                            )
                            keys = gold[ident]
                            try:
                                offsets = {
                                    wn.lemma_from_key(k).synset().offset()
                                    for k in keys
                                    if "%1:" in k
                                }
                                valid = (
                                    all("%1:" in k for k in keys)
                                    and offsets
                                    and offsets <= senses(w).keys()
                                )
                            except (ValueError, KeyError, WordNetError):
                                valid = False
                            if valid:
                                candidates.setdefault(w, []).append((ident, offsets))
                            else:
                                counts["unmappable_noun_targets"] += 1
                        for a, b in combinations(sorted(candidates), 2):
                            primary = (a, b) in frozen
                            sizes = len(senses(a)), len(senses(b))
                            broad = min(sizes) >= 2 and bool(
                                senses(a).keys() & reachable(b)
                                or senses(b).keys() & reachable(a)
                            )
                            if not primary and not broad:
                                continue
                            matrix, questions = model(a, b)
                            for (u, xs), (v, ys) in product(
                                candidates[a], candidates[b]
                            ):
                                r = remaining.pop((u, v))
                                assert (
                                    r["source"],
                                    r["sentence"],
                                    r["words"],
                                    r["registered"],
                                    r["broad"],
                                    r["both"],
                                ) == (
                                    src,
                                    sent.getAttribute("id"),
                                    [a, b],
                                    primary,
                                    broad,
                                    sum(n > 1 for n in sizes),
                                )
                                assert [(w[0], w[1]) for w in r["worlds"]] == sorted(
                                    product(xs, ys)
                                )
                                for x, y, label, traces in r["worlds"]:
                                    worlds_count += 1
                                    assert label == LABELS[matrix[x, y]]
                                    assert traces.keys() == set(QUESTIONS)
                                    for q, (constant, flat, pref) in questions.items():
                                        paths = []
                                        for first in pref:
                                            if sizes[first] == 1:
                                                first = 1 - first
                                            path = "-" if constant else "LR"[first]
                                            if (
                                                not constant
                                                and (x, y)[first] not in flat[first]
                                            ):
                                                path += "LR"[1 - first]
                                            paths.append(path)
                                        assert paths == traces[q]
                                        checks += len(paths)
        finally:
            nltk.data.path.remove(temp)
    assert not remaining and census == report["input_census"]
    assert len(census) == 5
    for group in ("registered", "broad"):
        selected = [r for r in records if r[group]]
        check_summary(report[group]["pooled"], selected)
        assert set(report[group]["sources"]) == set(census)
        for source, stats in report[group]["sources"].items():
            check_summary(stats, [r for r in selected if r["source"] == source])
    assert report["overlap_items"] == sum(
        r["registered"] and r["broad"] for r in records
    )
    s = report["registered"]["pooled"]["single_gold"]["relation"]["by_relation"]
    strict = [s[k] for k in LABELS[1:3]]
    assert report["primary_gate_passed"] == (
        sum(r["items"] for r in strict) >= 20
        and sum(r["both"] - r["table"] for r in strict) == 0
        and s["neither"]["both"] > s["neither"]["table"]
    )
    return {
        "independently_reconstructed_occurrences": len(records),
        "admissible_sense_worlds": worlds_count,
        "policy_question_world_transcripts_checked": checks,
        "sources": len(census),
        "cohort_pooled_and_source_summaries_checked": 2 * (1 + len(census)),
    }


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    for name in ("wordnet", "data", "output"):
        p.add_argument(name, type=Path)
    a = p.parse_args()
    print(json.dumps(check(a.wordnet, a.data, a.output), indent=2))
