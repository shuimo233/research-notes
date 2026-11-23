"""Independent NLTK and decision-diagram verification of the entire registered conflict population."""

import argparse
from collections import Counter
import csv
from functools import lru_cache
from hashlib import sha256
from itertools import combinations
import json
from math import inf
from pathlib import Path
import shutil
import sqlite3
import sys
from tempfile import TemporaryDirectory
from zipfile import ZipFile

sys.path.insert(0, str(Path(__file__).resolve().parent))
from conflict_bdd import Diagram
from conflict_evidence import analyze
from conflict_package import DecisionService
from go_model_fetch import verify


def ranked(archive):
    with ZipFile(archive) as f:
        lines = f.read("wordnet/cntlist.rev").decode().splitlines()
    with sqlite3.connect(":memory:") as db:
        db.execute("CREATE TABLE freq(w TEXT, kind TEXT, n INT)")
        records = []
        for line in lines:
            key, _, n = line.split()
            w, ending = key.rsplit("%", 1)
            records.append((w, ending[0], int(n)))
        db.executemany("INSERT INTO freq VALUES(?,?,?)", records)
        return [
            r[0]
            for r in db.execute("""SELECT w FROM freq WHERE kind='1' AND w!=''
          AND w NOT GLOB '*[^a-z]*' GROUP BY w ORDER BY SUM(n) DESC,w ASC LIMIT 2000""")
        ]


def fixtures():
    # Exhaustively derive all antichains and every polarity/distance from truth-table neighbors.
    n = 4
    worlds = range(1 << n)
    antichains = []
    for mask in range(1 << (1 << n)):
        family = [w for w in worlds if mask >> w & 1]
        if all(not (x & y in (x, y)) for x, y in combinations(family, 2)):
            antichains.append(family)
    for p in antichains:
        for q in antichains:
            val = [any(w & k == k for k in p) and not any(w & k == k for k in q) for w in worlds]
            expected = analyze(p, q)
            for i in range(n):
                bit = 1 << i
                neigh = [(val[w], val[w | bit]) for w in worlds if not w & bit]
                assert ((False, True) in neigh) == (bit in expected["rising"])
                assert ((True, False) in neigh) == (bit in expected["falling"])
            cost = min((n - w.bit_count() for w in worlds if val[w]), default=inf)
            cut = expected["minimum_deletions"]
            assert (inf if cut is None else cut.bit_count()) == cost
    return len(antichains) ** 2


def verify_policy(diag, positive, negative, index, record, policy, want_worlds=True):
    root = diag.join("and", positive, diag.join("xor", negative, 1))
    report = record["depart_" + policy]
    visible = record["edges"]
    needed = set()
    unknown = set(index) - set(visible)
    for e, i in index.items():
        up, down = diag.polarity(root, i)
        if up or down:
            needed.add(e)
        if e in unknown:
            assert not up and not down
            continue
        saved = str(visible.index(e))
        assert (saved in report["rising"], saved in report["falling"]) == (up, down)
        if want_worlds:
            for name, is_up, active in (("rising", True, up), ("falling", False, down)):
                if active:
                    mask = expand(int(report[name][saved], 16), visible, index)
                    assert not mask & (1 << i)
                    assert (
                        diag.at(root, mask) == (not is_up) and diag.at(root, mask | (1 << i)) == is_up
                    )
    need = sum(1 << i for i, e in enumerate(visible) if e in needed)
    assert int(report["needed"], 16) == need
    cut = report["minimum_delete"]
    if cut is None:
        assert diag.distance(root) == inf
    else:
        raw = expand(int(cut, 16), visible, index)
        assert diag.distance(root) == raw.bit_count()
        assert diag.at(root, ((1 << len(index)) - 1) ^ raw)
    only = set()
    for p in record[policy]:
        only.update(e for i, e in enumerate(visible) if int(p, 16) & (1 << i))
    witness = report["proposal_only_mismatch"]
    assert (witness is not None) == bool(needed - only)
    if witness is not None:
        w = expand(int(witness, 16), visible, index)
        retained = sum(1 << index[e] for e in only)
        assert diag.at(root, w) != diag.at(root, w & retained)
    return needed, diag.distance(root)


def expand(mask, visible, index):
    return sum(1 << index[e] for i, e in enumerate(visible) if mask & (1 << i))


def check(archive, ledger, output):
    import nltk
    from nltk.corpus import wordnet as wn

    verify(archive, "3c68cd207844f071a5206f7fbed23e5c607ec02f")
    expected = json.loads((output / "wordnet-conflict-results.json").read_bytes())
    words = ranked(archive)
    assert sha256("\n".join(words).encode()).hexdigest() == expected["ranked_words_sha256"]
    with TemporaryDirectory() as t:
        corp = Path(t) / "corpora"
        corp.mkdir()
        shutil.copyfile(archive, corp / "wordnet.zip")
        nltk.data.path.insert(0, t)
        try:

            @lru_cache(None)
            def senses(w):
                return set(wn.synsets(w, pos="n"))

            @lru_cache(None)
            def ancestors(w):
                return {node for s in senses(w) for path in s.hypernym_paths() for node in path[:-1]}

            def lexical_paths(a, b):
                proof = set()
                for start in senses(a):
                    for path in start.hypernym_paths():
                        for i, node in enumerate(path[:-1]):
                            if node in senses(b):
                                proof.add(
                                    frozenset(
                                        f"{y.offset():08d}>{x.offset():08d}"
                                        for x, y in zip(path[i:], path[i + 1 :])
                                    )
                                )
                return proof

            reciprocal = set()
            directed = 0
            for a, b in combinations(words, 2):
                ab = bool(senses(b) & ancestors(a))
                ba = bool(senses(a) & ancestors(b))
                directed += ab + ba
                if ab and ba:
                    reciprocal.add(tuple(sorted((a, b))))
            assert directed == expected["strict_directed_relations"]
            records = [
                json.loads(l)
                for l in (output / "wordnet-conflict-ledger.jsonl").read_bytes().splitlines()
            ]
            got = [tuple(r["words"]) for r in records]
            assert len(got) == len(reciprocal) and set(got) == reciprocal

            @lru_cache(None)
            def model(a, b):
                ab, ba = lexical_paths(a, b), lexical_paths(b, a)
                idx = {e: i for i, e in enumerate(sorted(set().union(*ab, *ba)))}
                d = Diagram()
                return d, idx, ab, ba, d.family(ab, idx), d.family(ba, idx)

            checks = 0
            published_witnesses = 0
            context_records = [
                json.loads(l)
                for l in (output / "wordnet-conflict-context-proofs.jsonl").read_bytes().splitlines()
            ]
            context_keys = {tuple(r["words"]) for r in context_records}
            assert len(context_keys) == len(context_records)
            primary_sets = [set(), set()]
            observed = Counter()
            cuts = Counter()
            for index, r in enumerate(records + context_records):
                d, idx, p, q, ab, ba = model(*r["words"])
                primary = index < len(records)
                if primary:
                    primary_sets[0].update(r["edges"])
                for label, raw in (("ab", p), ("ba", q)):
                    true_paths = {path for path in raw if not any(other < path for other in raw)}
                    saved = {
                        frozenset(e for i, e in enumerate(r["edges"]) if int(mask, 16) >> i & 1)
                        for mask in r[label]
                    }
                    assert saved == true_paths
                for mode, x, y in (("ab", ab, ba), ("ba", ba, ab)):
                    needed, distance = verify_policy(d, x, y, idx, r, mode)
                    saved = r["depart_" + mode]
                    if primary:
                        primary_sets[1].update(needed)
                        observed["policies"] += 1
                        observed["separate_proof_union_edge_occurrences"] += len(r["edges"])
                        observed["exact_edge_occurrences"] += len(needed)
                        observed["policies_saving_edges"] += len(needed) < len(r["edges"])
                        observed["proposal_only_wrong"] += saved["proposal_only_mismatch"] is not None
                        proposed_paths = p if mode == "ab" else q
                        minimal_paths = [v for v in proposed_paths if not any(w < v for w in proposed_paths)]
                        kept = sum(1 << idx[e] for e in set().union(*minimal_paths))
                        root = d.join("and", x, d.join("xor", y, 1))
                        observed["proposal_only_wrong_on_full"] += d.at(root, kept) != d.at(
                            root, (1 << len(idx)) - 1
                        )
                        observed["policies_with_bidirectional_pivot"] += bool(
                            saved["rising"].keys() & saved["falling"].keys()
                        )
                        cuts["unreachable" if distance == inf else str(distance)] += 1
                    published_witnesses += len(saved["rising"]) + len(saved["falling"])
                    checks += len(idx)
            with ledger.open(encoding="utf8", newline="") as f:
                contexts = {(r["subset"], r["ab_line"]): r for r in csv.DictReader(f, delimiter="\t")}
            with (output / "wordnet-conflict-context.tsv").open(encoding="utf8", newline="") as f:
                outputs = list(csv.DictReader(f, delimiter="\t"))
            assert len(contexts) == len(outputs) == 596
            assert context_keys == {
                tuple(sorted([r["a_term"], r["b_term"]])) for r in contexts.values()
            }
            assert expected["registered"] == {**observed, "minimum_deletions_histogram": dict(cuts)}
            assert list(map(len, primary_sets)) == [
                expected["primary_unique_proof_edges"],
                expected["primary_unique_decision_edges"],
            ]
            package = json.loads((output / "wordnet-conflict-package.json").read_bytes())
            service = DecisionService(package)
            assert service.queries.keys() == {s + "/" + i for s, i in contexts}
            graph_union = set()
            required_union = set()
            executed = 0
            counts = {}
            for r in outputs:
                orig = contexts.pop((r["subset"], r["ab_line"]))
                a, b = orig["a_term"], orig["b_term"]
                fb = orig["invert_affirmative"]
                d, idx, p, q, ab, ba = model(a, b)
                assert (a, b, fb) == (r["a_term"], r["b_term"], r["fallback"])
                chosen = ("reverse" if p else "forward") if bool(p) != bool(q) else fb
                assert (int(r["support_ab"]), int(r["support_ba"]), r["decision"]) == (
                    bool(p),
                    bool(q),
                    chosen,
                )
                raw_min = [v for family in (p, q) for v in family if not any(w < v for w in family)]
                minimum_source = set().union(*raw_min)
                graph_union.update(minimum_source)
                assert int(r["proof_union_edges"]) == len(minimum_source)
                x, y = (ab, ba) if fb == "forward" else (ba, ab)
                root = d.join("and", x, d.join("xor", y, 1))
                essentials = {e for e, i in idx.items() if any(d.polarity(root, i))}
                required_union.update(essentials)
                assert int(r["minimum_edges"]) == len(essentials)
                key = r["subset"] + "/" + r["ab_line"]
                base, other, rule = package["queries"][key]
                assert base == fb and other == ("reverse" if base == "forward" else "forward")
                pa, pb = package["rules"][rule]

                def compiled(paths):
                    return d.family([frozenset(service.facts[i] for i in path) for path in paths], idx)

                assert d.join("and", compiled(pa), d.join("xor", compiled(pb), 1)) == root
                full = (1 << len(idx)) - 1
                for e in [None, *service.facts]:
                    gone = 0 if e not in idx else 1 << idx[e]
                    assert service.decide(key, () if e is None else (e,)) == (
                        other if d.at(root, full ^ gone) else base
                    )
                    executed += 1
                distance = d.distance(root)
                assert r["minimum_deletions"] == ("unreachable" if distance == inf else str(distance))
                c = counts.setdefault(r["subset"], Counter())
                c["correct"] += chosen == orig["gold"]
                c["items"] += 1
                c["both"] += bool(p) and bool(q)
                c["neither"] += not (p or q)
                c["policies_saving_edges"] += len(essentials) < len(minimum_source)
                c["separate_proof_union_edge_occurrences"] += len(minimum_source)
                c["exact_edge_occurrences"] += len(essentials)
            for s, c in counts.items():
                assert expected["real_queries"][s] == dict(c)
            assert required_union == set(service.facts)
            assert (len(graph_union), len(required_union)) == (
                expected["context_unique_proof_edges"],
                expected["context_unique_decision_edges"],
            )
        finally:
            nltk.data.path.remove(t)
    return {
        "independently_enumerated_word_pairs": len(words) * (len(words) - 1) // 2,
        "both_directions": len(records),
        "bdd_policy_edge_checks": checks,
        "directional_witness_worlds_replayed": published_witnesses,
        "bdd_nearest_withdrawals_checked": 2 * (len(records) + len(context_records)) + len(outputs),
        "context_distinct_word_pairs": len(context_records),
        "runtime_original_or_single_withdrawal_checks": executed,
        "unrestricted_package_equivalences": len(outputs),
        "real_model_contexts": len(outputs),
        "exhaustive_small_path_family_pairs": fixtures(),
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for n in ("archive", "ledger", "data"):
        parser.add_argument(n, type=Path)
    a = parser.parse_args()
    print(json.dumps(check(a.archive, a.ledger, a.data), indent=2))
