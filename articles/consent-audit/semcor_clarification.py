"""Replay exact two-word sense clarification on naturally cooccurring SemCor mentions."""

import argparse
from collections import Counter, defaultdict
import csv
from fractions import Fraction
from functools import lru_cache
from itertools import combinations
import json
from pathlib import Path
import sys
from xml.etree import ElementTree
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
from go_model_fetch import fetch_verified, verify
from sense_inquiry import SenseInquiry
from wordnet_paths import NounPaths

W_DIGEST = "3c68cd207844f071a5206f7fbed23e5c607ec02f"
S_DIGEST = "19cdf8d8b1377016e9a0c3ec2a3147df1a778727"
POLICIES = ("table", "left", "right", "fewer", "more")
FIELDS = (
    "document",
    "sentence",
    "left_position",
    "right_position",
    "left_word",
    "right_word",
    "left_key",
    "right_key",
    "left_offset",
    "right_offset",
    "relation",
    "asked",
    *POLICIES,
    "both",
)


def read_cohort():
    return {
        tuple(json.loads(line)["words"])
        for line in (ROOT / "wordnet-conflict-ledger.jsonl").read_bytes().splitlines()
    }


def collect(wordnet, semcor):
    graph = NounPaths(wordnet)
    with ZipFile(wordnet) as z:
        index = dict(
            line.split()[:2]
            for line in z.read("wordnet/index.sense").decode().splitlines()
        )
    pairs = read_cohort()
    vocab = set().union(*pairs)
    candidates = {w: graph.senses(w) for w in vocab}

    @lru_cache(None)
    def table(a, b):
        return SenseInquiry(candidates[a], candidates[b], graph.relation)

    rows = []
    census = Counter()
    with ZipFile(semcor) as z:
        names = sorted(
            n for n in z.namelist() if "/tagfiles/" in n and not n.endswith("/")
        )
        census["documents_scanned"] = len(names)
        for name in names:
            with z.open(name) as stream:
                tree = ElementTree.parse(stream)
            for sn, sentence in enumerate(tree.iter("s"), 1):
                census["sentences_scanned"] += 1
                mentions = []
                for pos, token in enumerate(sentence, 1):
                    w = token.get("lemma", "")
                    if w not in vocab:
                        continue
                    key = w + "%" + token.get("lexsn", "")
                    if not key.startswith(w + "%1:") or key not in index:
                        continue
                    sense = int(index[key])
                    if sense in candidates[w]:
                        mentions.append((w, pos, key, sense))
                for first, second in combinations(mentions, 2):
                    l, r = sorted((first, second))
                    a, b = l[0], r[0]
                    if (a, b) not in pairs:
                        continue
                    inquiry = table(a, b)
                    truth = l[3], r[3]
                    label = graph.relation(*truth)
                    row = dict(
                        zip(
                            FIELDS[:11],
                            (name, sn, l[1], r[1], a, b, l[2], r[2], *truth, label),
                            strict=True,
                        )
                    )
                    for policy in POLICIES:
                        final, asked = inquiry.replay(truth, policy)
                        if label != final:
                            raise ValueError(f"failed to resolve {name} sentence {sn}")
                        if policy == "table":
                            row["asked"] = "".join("LR"[i] for i in asked) or "-"
                        row[policy] = len(asked)
                    row["both"] = sum(len(side) > 1 for side in inquiry.senses)
                    rows.append(row)
    return rows, dict(census)


def summarize(rows, census):
    groups = defaultdict(list)
    for r in rows:
        groups[r["left_word"], r["right_word"]].append(r)
    policies = (*POLICIES, "both", "coin")

    def expense(r, p):
        return Fraction(r["left"] + r["right"], 2) if p == "coin" else r[p]

    def costs(group):
        return {p: sum(expense(r, p) for r in group) for p in policies}

    # Public totals and means use exact integers or p/q strings, including the randomized baseline.
    def exact(n):
        f = Fraction(n)
        return f.numerator if f.denominator == 1 else str(f)

    counts = costs(rows)
    relations = sorted({r["relation"] for r in rows})
    pair_means = (
        {
            p: exact(
                sum(Fraction(costs(g)[p], len(g)) for g in groups.values())
                / len(groups)
            )
            for p in policies
        }
        if groups
        else {}
    )
    return {
        **census,
        "eligible_occurrences": len(rows),
        "eligible_word_pairs": len(groups),
        "eligible_documents": len({r["document"] for r in rows}),
        "eligible_sentences": len({(r["document"], r["sentence"]) for r in rows}),
        "total_reveals": {p: exact(n) for p, n in counts.items()},
        "mean_reveals_equal_word_pairs": pair_means,
        "occurrences_where_first_side_matters": sum(
            r["left"] != r["right"] for r in rows
        ),
        "relations": {
            v: {
                "items": sum(r["relation"] == v for r in rows),
                "table_reveals": sum(r["table"] for r in rows if r["relation"] == v),
                "both_reveals": sum(r["both"] for r in rows if r["relation"] == v),
                "table_saves_reveals": sum(
                    r["both"] - r["table"] for r in rows if r["relation"] == v
                ),
            }
            for v in relations
        },
        "asked_paths": dict(sorted(Counter(r["asked"] for r in rows).items())),
        "strict_gain_over_best_fixed_control": bool(rows)
        and counts["table"]
        < min(counts[p] for p in ("left", "right", "fewer", "more")),
    }


def run(wordnet, semcor, out):
    verify(wordnet, W_DIGEST)
    verify(semcor, S_DIGEST)
    rows, census = collect(wordnet, semcor)
    result = summarize(rows, census)
    out.mkdir(parents=True, exist_ok=False)
    with (out / "semcor-clarification-ledger.tsv").open(
        "x", encoding="utf8", newline=""
    ) as f:
        writer = csv.DictWriter(
            f, fieldnames=FIELDS, delimiter="\t", lineterminator="\n"
        )
        writer.writeheader()
        writer.writerows(rows)
    (out / "semcor-clarification-results.json").write_bytes(
        (json.dumps(result, indent=2) + "\n").encode()
    )
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("wordnet", "semcor", "new_output"):
        parser.add_argument(name, type=Path)
    parser.add_argument("--check-release", action="store_true",
                        help="run independent NLTK checks and compare all three release files")
    parser.add_argument("--fetch", action="store_true",
                        help="download missing archives, verifying against the registered Git blobs")
    a = parser.parse_args()
    if a.fetch:
        for name, archive, digest in (("wordnet", a.wordnet, W_DIGEST), ("semcor", a.semcor, S_DIGEST)):
            fetch_verified(archive, f"https://www.nltk.org/nltk_data/packages/corpora/{name}.zip", digest)
    result = run(a.wordnet, a.semcor, a.new_output)
    if a.check_release:
        from semcor_clarification_check import check

        checks = check(a.wordnet, a.semcor, a.new_output)
        (a.new_output / "semcor-clarification-checks.json").write_bytes(
            (json.dumps(checks, indent=2) + "\n").encode())
        for ending in ("ledger.tsv", "results.json", "checks.json"):
            name = "semcor-clarification-" + ending
            if (a.new_output / name).read_bytes() != (ROOT / name).read_bytes().replace(b"\r\n", b"\n"):
                raise ValueError(f"release artifact differs: {name}")
        result["checks"] = checks
    print(json.dumps(result, indent=2))
