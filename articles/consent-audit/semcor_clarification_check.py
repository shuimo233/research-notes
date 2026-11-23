"""Independently enumerate SemCor pairs and check every clarification against NLTK WordNet."""

import argparse
from collections import Counter, defaultdict
import csv
from fractions import Fraction
from functools import lru_cache
from itertools import product
import json
from pathlib import Path
import shutil
import sys
from tempfile import TemporaryDirectory
from xml.parsers import expat
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
from go_model_fetch import verify


def sentences(blob):
    result = []
    level = 0
    sentence_level = None
    parser = expat.ParserCreate()

    def start(tag, attrs):
        nonlocal level, sentence_level
        level += 1
        if tag == "s":
            result.append([])
            sentence_level = level
        elif sentence_level is not None and level == sentence_level + 1:
            result[-1].append((attrs.get("lemma", ""), attrs.get("lexsn", "")))

    def end(tag):
        nonlocal level, sentence_level
        if tag == "s":
            sentence_level = None
        level -= 1

    parser.StartElementHandler = start
    parser.EndElementHandler = end
    parser.Parse(blob, True)
    return result


def check(wordnet, semcor, output):
    if not __debug__:
        raise RuntimeError("run without -O for independent checks")
    import nltk
    from nltk.corpus import wordnet as wn
    from nltk.corpus.reader.wordnet import WordNetError

    verify(wordnet, "3c68cd207844f071a5206f7fbed23e5c607ec02f")
    verify(semcor, "19cdf8d8b1377016e9a0c3ec2a3147df1a778727")
    pairs = [
        tuple(json.loads(s)["words"])
        for s in (ROOT / "wordnet-conflict-ledger.jsonl").read_bytes().splitlines()
    ]
    vocab = set().union(*pairs)
    with (output / "semcor-clarification-ledger.tsv").open(
        encoding="utf8", newline=""
    ) as f:
        rows = list(csv.DictReader(f, delimiter="\t"))
    expected = json.loads((output / "semcor-clarification-results.json").read_bytes())
    by_id = {
        (
            r["document"],
            int(r["sentence"]),
            int(r["left_position"]),
            int(r["right_position"]),
        ): r
        for r in rows
    }
    assert len(by_id) == len(rows)
    group_costs = defaultdict(Counter)
    group_sizes = Counter()
    total = Counter()
    outcomes = Counter()
    checked_cells = sentence_count = 0
    with TemporaryDirectory() as t:
        corp = Path(t) / "corpora"
        corp.mkdir()
        shutil.copyfile(wordnet, corp / "wordnet.zip")
        nltk.data.path.insert(0, t)
        try:
            senses = {w: set(wn.synsets(w, pos="n")) for w in vocab}

            @lru_cache(None)
            def read_key(w, sn):
                if not sn.startswith("1:") or ";" in sn:
                    return None
                try:
                    item = wn.lemma_from_key(w + "%" + sn).synset()
                except (WordNetError, KeyError, ValueError):
                    return None
                return item if item in senses[w] else None

            @lru_cache(None)
            def ancestors(s):
                return {v for path in s.hypernym_paths() for v in path[:-1]}

            @lru_cache(None)
            def relate(x, y):
                if x == y:
                    return "same"
                if y in ancestors(x):
                    return "left_narrower"
                if x in ancestors(y):
                    return "right_narrower"
                return "neither"

            @lru_cache(None)
            def alternatives(a, b):
                matrix = {
                    (x, y): relate(x, y) for x, y in product(senses[a], senses[b])
                }
                return matrix, len(set(matrix.values())) == 1

            with ZipFile(semcor) as z:
                docs = [
                    p for p in z.namelist() if "/tagfiles/" in p and not p.endswith("/")
                ]
                for doc in docs:
                    for i, sent in enumerate(sentences(z.read(doc)), 1):
                        sentence_count += 1
                        items = defaultdict(list)
                        for j, (w, sn) in enumerate(sent, 1):
                            if w in vocab and (val := read_key(w, sn)) is not None:
                                items[w].append((j, w + "%" + sn, val))
                        for a, b in pairs:
                            if a not in items or b not in items:
                                continue
                            matrix, initial = alternatives(a, b)
                            domains = senses[a], senses[b]
                            for (j, k, x), (h, l, y) in product(items[a], items[b]):
                                row = by_id.pop((doc, i, j, h))
                                assert (a, b, k, l, x.offset(), y.offset()) == (
                                    row["left_word"],
                                    row["right_word"],
                                    row["left_key"],
                                    row["right_key"],
                                    int(row["left_offset"]),
                                    int(row["right_offset"]),
                                )
                                state = matrix[x, y]
                                assert state == row["relation"]
                                outcomes[state] += 1

                                def unique(side, value):
                                    return (
                                        len(
                                            {
                                                v
                                                for key, v in matrix.items()
                                                if key[side] == value
                                            }
                                        )
                                        == 1
                                    )

                                rates = [
                                    Fraction(
                                        sum(unique(s, v) for v in domain), len(domain)
                                    )
                                    for s, domain in enumerate(domains)
                                ]
                                sizes = tuple(map(len, domains))
                                preference = dict(
                                    left=0,
                                    right=1,
                                    table=int(rates[1] > rates[0]),
                                    fewer=int(sizes[1] < sizes[0]),
                                    more=int(sizes[1] > sizes[0]),
                                )
                                costs = {"both": sum(n > 1 for n in sizes)}
                                for policy, first in preference.items():
                                    if sizes[first] == 1:
                                        first = 1 - first
                                    trial = (x, y)
                                    steps = [] if initial else [first]
                                    if steps and not unique(first, trial[first]):
                                        steps.append(1 - first)
                                    costs[policy] = len(steps)
                                    if policy == "table":
                                        assert row["asked"] == (
                                            "".join("LR"[s] for s in steps) or "-"
                                        )
                                        survivors = [
                                            v
                                            for key, v in matrix.items()
                                            if all(key[s] == trial[s] for s in steps)
                                        ]
                                        assert set(survivors) == {state}
                                        checked_cells += len(survivors)
                                assert all(int(row[p]) == n for p, n in costs.items())
                                costs["coin"] = Fraction(
                                    costs["left"] + costs["right"], 2
                                )
                                group_sizes[a, b] += 1
                                group_costs[a, b].update(costs)
                                total.update(costs)
            # Follow-up after scoring: can a single revealed sense ever prove a positive
            # direction where both words genuinely need disambiguation?
            ambiguous_pairs = 0
            certain = Counter()
            pairs_by_label = Counter()
            for a, b in pairs:
                if min(len(senses[a]), len(senses[b])) < 2:
                    continue
                ambiguous_pairs += 1
                matrix, _ = alternatives(a, b)
                pair_labels = set()
                for side, word in enumerate((a, b)):
                    for value in senses[word]:
                        allowed = {v for key, v in matrix.items() if key[side] == value}
                        if len(allowed) == 1:
                            label = allowed.pop()
                            certain[label] += 1
                            pair_labels.add(label)
                pairs_by_label.update(pair_labels)
        finally:
            nltk.data.path.remove(t)
    assert not by_id and len(docs) == expected["documents_scanned"]
    assert sentence_count == expected["sentences_scanned"]
    assert sum(group_sizes.values()) == len(rows) == expected["eligible_occurrences"]
    assert len(group_sizes) == expected["eligible_word_pairs"]
    assert {p: Fraction(v) for p, v in expected["total_reveals"].items()} == dict(total)
    for p, v in expected["mean_reveals_equal_word_pairs"].items():
        assert Fraction(v) == sum(
            Fraction(g[p], group_sizes[k]) for k, g in group_costs.items()
        ) / len(group_sizes)
    assert outcomes == Counter(
        {k: v["items"] for k, v in expected["relations"].items()}
    )
    return {
        "independently_enumerated_occurrences": len(rows),
        "documents": len(docs),
        "independently_checked_policy_replays": 5 * len(rows),
        "remaining_sense_cells_replayed_at_stopping": checked_cells,
        "cooccurring_word_pairs": len(group_sizes),
        "posthoc_two_ambiguous_word_inventory": {
            "pairs": ambiguous_pairs,
            "one_sense_certificates_by_relation": dict(sorted(certain.items())),
            "pairs_with_each_certifiable_relation": dict(sorted(pairs_by_label.items())),
        },
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("wordnet", "semcor", "output"):
        parser.add_argument(name, type=Path)
    a = parser.parse_args()
    print(json.dumps(check(a.wordnet, a.semcor, a.output), indent=2))
