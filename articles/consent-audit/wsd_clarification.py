"""External WSD test of stopping certificates for four different relation questions."""

import argparse
from collections import Counter
from fractions import Fraction
from functools import lru_cache
from itertools import combinations, product
import json
from pathlib import Path
import sys
from xml.etree import ElementTree
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
from go_model_fetch import fetch_verified, verify
from semcor_clarification import POLICIES, W_DIGEST, read_cohort
from sense_inquiry import SenseInquiry
from wordnet_paths import NounPaths
from wordnet_sense_query import QUESTIONS, STRICT, project

REV = "697cb66cf7ba874c276c863f2e9e2ea32b6c52d9"
FILES = {
    "ALL.data.xml": "7d5cb8f9f6a1055091976a6816288a621475b41f",
    "ALL.gold.key.txt": "d5bd595ebb0d83a149f8a2dc09851f23fc1521f1",
}
SOURCES = ("senseval2", "senseval3", "semeval2007", "semeval2013", "semeval2015")


def exact(n):
    f = Fraction(n)
    return f.numerator if f.denominator == 1 else str(f)


def collect(archive, data):
    graph = NounPaths(archive)
    senses = lru_cache(None)(graph.senses)
    cohort = read_cohort()
    with ZipFile(archive) as z:
        index = {
            key: int(offset)
            for key, offset, *_ in (
                s.split() for s in z.read("wordnet/index.sense").decode().splitlines()
            )
            if "%1:" in key
        }
    gold = {}
    for line in (data / "ALL.gold.key.txt").read_text(encoding="utf8").splitlines():
        ident, *keys = line.split()
        if ident in gold or not keys:
            raise ValueError(f"missing or duplicate gold entry at {ident}")
        gold[ident] = keys

    @lru_cache(None)
    def above(word):
        return set().union(*(graph.ancestors(s) for s in senses(word)))

    @lru_cache(512)
    def tables(a, b):
        matrix = {
            (x, y): graph.relation(x, y) for x, y in product(senses(a), senses(b))
        }
        return {
            q: SenseInquiry(senses(a), senses(b), lambda x, y: project(matrix[x, y], q))
            for q in QUESTIONS
        }

    census = {src: Counter(unmappable_noun_targets=0) for src in SOURCES}
    cases = []
    for doc in ElementTree.parse(data / "ALL.data.xml").iter("text"):
        src = doc.attrib["id"].split(".")[0]
        counts = census[src]
        counts["documents"] += 1
        for sent in doc.iter("sentence"):
            counts["sentences"] += 1
            mentions = []
            for token in sent.findall("instance"):
                if token.attrib["pos"] != "NOUN":
                    continue
                counts["noun_targets"] += 1
                ident, word = token.attrib["id"], token.attrib["lemma"]
                offsets = {index.get(k) for k in gold[ident]}
                if not offsets or not offsets <= senses(word):
                    counts["unmappable_noun_targets"] += 1
                    continue
                mentions.append((word, ident, sorted(offsets)))
            for t, u in combinations(mentions, 2):
                (a, aid, xs), (b, bid, ys) = sorted((t, u))
                if a == b:
                    continue
                registered = (a, b) in cohort
                broad = min(len(senses(a)), len(senses(b))) >= 2 and bool(
                    above(a) & senses(b) or above(b) & senses(a)
                )
                if not (registered or broad):
                    continue
                tests = tables(a, b)
                worlds = []
                for x, y in product(xs, ys):
                    r = graph.relation(x, y)
                    traces = {}
                    for q, inquiry in tests.items():
                        transcripts = []
                        for policy in POLICIES:
                            label, path = inquiry.replay((x, y), policy)
                            if label != project(r, q):
                                raise ValueError(
                                    f"wrong answer {aid} {bid} {q} {policy}"
                                )
                            transcripts.append("".join("LR"[i] for i in path) or "-")
                        traces[q] = transcripts
                    worlds.append([x, y, r, traces])
                cases.append(
                    {
                        "source": src,
                        "sentence": sent.attrib["id"],
                        "ids": [aid, bid],
                        "words": [a, b],
                        "registered": registered,
                        "broad": broad,
                        "both": sum(len(senses(w)) > 1 for w in (a, b)),
                        "worlds": worlds,
                    }
                )
    return census, cases


def costs(trace, both):
    r = {p: len(s) if s != "-" else 0 for p, s in zip(POLICIES, trace, strict=True)}
    r.update(
        oracle=min(r["left"], r["right"]),
        coin=Fraction(r["left"] + r["right"], 2),
        both=both,
    )
    return r


def summarize(cases):
    single, multi = (
        [c for c in cases if len(c["worlds"]) == 1],
        [c for c in cases if len(c["worlds"]) > 1],
    )
    relations = ("same", "left_narrower", "right_narrower", "neither")
    stats = {}
    for q in QUESTIONS:
        totals = Counter({p: 0 for p in (*POLICIES, "oracle", "coin", "both")})
        strata = {v: Counter(items=0, both=0, table=0, oracle=0) for v in relations}
        oracle_shorter = table_shorter = table_longer = singleton_checks = 0
        for c in single:
            _, _, v, traces = c["worlds"][0]
            row = costs(traces[q], c["both"])
            original = costs(traces["relation"], c["both"])
            totals.update(row)
            strata[v].update(
                items=1, both=c["both"], table=row["table"], oracle=row["oracle"]
            )
            if v in STRICT:
                oracle_shorter += row["oracle"] < original["oracle"]
                table_shorter += row["table"] < original["table"]
                table_longer += row["table"] > original["table"]
                if v == q:
                    if row["oracle"] != original["oracle"]:
                        raise ValueError("singleton-fiber certificate changed")
                    singleton_checks += 1
        stats[q] = {
            "total": {p: exact(n) for p, n in totals.items()},
            "by_relation": strata,
            "strict_worlds_with_shorter_certificate_than_four_way": oracle_shorter,
            "strict_worlds_with_fewer_table_reveals_than_four_way": table_shorter,
            "strict_worlds_with_more_table_reveals_than_four_way": table_longer,
            "affirmative_singleton_identity_checks": singleton_checks,
        }
    bounds = {}
    for q in QUESTIONS:
        metrics = ("table", "oracle", "table_savings", "oracle_savings")
        sums = {p: [0, 0] for p in metrics}
        for c in multi:
            worlds = [costs(t[q], c["both"]) for _, _, _, t in c["worlds"]]
            for p in metrics:
                col = (
                    [c["both"] - w[p.removesuffix("_savings")] for w in worlds]
                    if p.endswith("_savings")
                    else [w[p] for w in worlds]
                )
                sums[p][0] += min(col)
                sums[p][1] += max(col)
        bounds[q] = sums
    return {
        "items": len(cases),
        "single": len(single),
        "multiple": len(multi),
        "distinct_pairs": len({tuple(c["words"]) for c in cases}),
        "multiple_with_unique_relation": sum(
            len({w[2] for w in c["worlds"]}) == 1 for c in multi
        ),
        "single_gold": stats,
        "multi_gold_sum_of_case_bounds": bounds,
    }


def run(archive, data, output):
    verify(archive, W_DIGEST)
    for name, digest in FILES.items():
        verify(data / name, digest)
    census, cases = collect(archive, data)
    result = {"input_census": census, "policy_order_in_ledger": list(POLICIES)}
    for group in ("registered", "broad"):
        rows = [c for c in cases if c[group]]
        result[group] = {
            "pooled": summarize(rows),
            "sources": {
                s: summarize([c for c in rows if c["source"] == s]) for s in SOURCES
            },
        }
    s = result["registered"]["pooled"]["single_gold"]["relation"]["by_relation"]
    result["primary_gate_passed"] = (
        sum(s[k]["items"] for k in STRICT) >= 20
        and all(s[k]["both"] == s[k]["table"] for k in STRICT)
        and s["neither"]["both"] > s["neither"]["table"]
    )
    result["overlap_items"] = sum(c["registered"] and c["broad"] for c in cases)
    output.mkdir(parents=True, exist_ok=False)
    with (output / "wsd-clarification-ledger.jsonl").open(
        "x", encoding="utf8", newline="\n"
    ) as f:
        for c in cases:
            f.write(json.dumps(c, separators=(",", ":")) + "\n")
    (output / "wsd-clarification-results.json").write_bytes(
        (json.dumps(result, indent=2) + "\n").encode()
    )
    return result


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    for name in ("wordnet", "data", "new_output"):
        p.add_argument(name, type=Path)
    p.add_argument(
        "--fetch",
        action="store_true",
        help="fetch missing content and verify the pinned digests",
    )
    p.add_argument(
        "--check-release",
        action="store_true",
        help="independently check and compare all three published outputs",
    )
    args = p.parse_args()
    if args.fetch:
        fetch_verified(
            args.wordnet,
            "https://www.nltk.org/nltk_data/packages/corpora/wordnet.zip",
            W_DIGEST,
        )
        for name, digest in FILES.items():
            fetch_verified(
                args.data / name,
                f"https://raw.githubusercontent.com/akranlu/wsd-data/{REV}/data/ALL/{name}",
                digest,
            )
    result = run(args.wordnet, args.data, args.new_output)
    if args.check_release:
        from wsd_clarification_check import check

        checks = check(args.wordnet, args.data, args.new_output)
        (args.new_output / "wsd-clarification-checks.json").write_bytes(
            (json.dumps(checks, indent=2) + "\n").encode()
        )
        for suf in ("ledger.jsonl", "results.json", "checks.json"):
            fname = "wsd-clarification-" + suf
            if (args.new_output / fname).read_bytes() != (
                ROOT / fname
            ).read_bytes().replace(b"\r\n", b"\n"):
                raise ValueError(f"published file differs: {fname}")
    print(
        json.dumps(
            {
                k: {f: result[k]["pooled"][f] for f in ("items", "single", "multiple")}
                for k in ("registered", "broad")
            },
            indent=2,
        )
    )
