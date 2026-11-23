"""Build the registered WordNet conflict corpus and evaluate the two possible fallback policies."""

import argparse
from collections import Counter
import csv
from hashlib import sha256
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from conflict_evidence import analyze, minimal, union
from conflict_package import make_package
from go_model_fetch import verify
from wordnet_paths import NounPaths


def families(graph, a, b):
    ab, ba = graph.paths(a, b), graph.paths(b, a)
    edges = sorted(set().union(*ab, *ba))
    index = {e: 1 << i for i, e in enumerate(edges)}
    def encode(family):
        return minimal(sum(index[e] for e in path) for path in family)

    return edges, encode(ab), encode(ba)


def record(graph, a, b):
    edges, ab, ba = families(graph, a, b)
    # Keep only variables present in an inclusion-minimal certificate in at least one direction.
    used = union([*ab, *ba])
    lookup = {i: j for j, i in enumerate(i for i in range(len(edges)) if used & (1 << i))}

    def remap(fam):
        return minimal(sum(1 << j for i, j in lookup.items() if k & (1 << i)) for k in fam)

    ab, ba = remap(ab), remap(ba)
    labels = [f"{edges[i][0]:08d}>{edges[i][1]:08d}" for i in lookup]

    def packed(res):
        def worlds(w):
            return {str(e.bit_length() - 1): hex(v) for e, v in sorted(w.items())}

        cut = res["minimum_deletions"]
        bad = res["proposal_only_counterexample"]
        return {
            "rising": worlds(res["rising"]),
            "falling": worlds(res["falling"]),
            "needed": hex(res["needed"]),
            "minimum_delete": None if cut is None else hex(cut),
            "proposal_only_mismatch": None if bad is None else hex(bad),
        }

    return {
        "words": [a, b],
        "edges": labels,
        "ab": [hex(v) for v in ab],
        "ba": [hex(v) for v in ba],
        "depart_ab": packed(analyze(ab, ba)),
        "depart_ba": packed(analyze(ba, ab)),
    }


def compare(records):
    total = Counter()
    hist = Counter()
    for r in records:
        n = len(r["edges"])
        for direction in ("ab", "ba"):
            result = r["depart_" + direction]
            needed = int(result["needed"], 16)
            total["policies"] += 1
            total["separate_proof_union_edge_occurrences"] += n
            total["exact_edge_occurrences"] += needed.bit_count()
            total["policies_saving_edges"] += needed.bit_count() < n
            total["proposal_only_wrong"] += result["proposal_only_mismatch"] is not None
            # All registered pairs have proof in both directions on the intact graph.
            kept = union(int(path, 16) for path in r[direction])
            opposite = r["ba" if direction == "ab" else "ab"]
            total["proposal_only_wrong_on_full"] += not any(
                int(path, 16) & kept == int(path, 16) for path in opposite
            )
            total["policies_with_bidirectional_pivot"] += bool(
                result["rising"].keys() & result["falling"].keys()
            )
            cut = result["minimum_delete"]
            hist["unreachable" if cut is None else str(int(cut, 16).bit_count())] += 1
    return {**total, "minimum_deletions_histogram": dict(sorted(hist.items()))}


def run(archive, ledger, dest):
    verify(archive, "3c68cd207844f071a5206f7fbed23e5c607ec02f")
    g = NounPaths(archive)
    words = g.ranked_words(2000)
    pairs, nforward = g.reciprocal(words)
    primary = [record(g, a, b) for a, b in pairs]
    with ledger.open(encoding="utf8", newline="") as f:
        source = list(csv.DictReader(f, delimiter="\t"))
    cache = {tuple(r["words"]): r for r in primary}
    groups = {}
    fieldnames = [
        "subset",
        "ab_line",
        "a_term",
        "b_term",
        "fallback",
        "support_ab",
        "support_ba",
        "decision",
        "proof_union_edges",
        "minimum_edges",
        "minimum_deletions",
    ]
    table = []
    actual_conflicts = set()
    context_records = set()
    service_rows = []
    for r in source:
        a, b = r["a_term"], r["b_term"]
        key = tuple(sorted((a, b)))
        if key not in cache:
            cache[key] = record(g, *key)
        rec = cache[key]
        context_records.add(key)
        row_ab = "ab" if a == key[0] else "ba"
        row_ba = "ba" if a == key[0] else "ab"
        forward, reverse = bool(rec[row_ab]), bool(rec[row_ba])
        if forward and reverse:
            actual_conflicts.add(key)
        fallback = r["invert_affirmative"]
        if fallback not in ("forward", "reverse"):
            raise ValueError("expected a definite archived fallback")
        # In a downward frame an a->b lexical proof predicts the reverse sentence direction.
        depart_side = row_ab if fallback == "forward" else row_ba
        policy = rec["depart_" + depart_side]
        service_rows.append(
            (
                r["subset"] + "/" + r["ab_line"],
                fallback,
                "reverse" if fallback == "forward" else "forward",
                rec,
                depart_side,
            )
        )
        chosen = ("reverse" if forward else "forward") if forward != reverse else fallback
        n = len(rec["edges"])
        k = int(policy["needed"], 16).bit_count()
        cut = policy["minimum_delete"]
        table.append(
            [
                r["subset"],
                r["ab_line"],
                a,
                b,
                fallback,
                int(forward),
                int(reverse),
                chosen,
                n,
                k,
                "unreachable" if cut is None else int(cut, 16).bit_count(),
            ]
        )
        counts = groups.setdefault(r["subset"], Counter())
        counts["items"] += 1
        counts["both"] += forward and reverse
        counts["neither"] += not (forward or reverse)
        counts["correct"] += chosen == r["gold"]
        counts["policies_saving_edges"] += k < n
        counts["separate_proof_union_edge_occurrences"] += n
        counts["exact_edge_occurrences"] += k
    dest.mkdir(parents=True, exist_ok=False)
    with (dest / "wordnet-conflict-ledger.jsonl").open("x", encoding="utf8", newline="\n") as stream:
        for item in primary:
            stream.write(json.dumps(item, separators=(",", ":")) + "\n")
    with (dest / "wordnet-conflict-context-proofs.jsonl").open(
        "x", encoding="utf8", newline="\n"
    ) as stream:
        for key in sorted(context_records):
            stream.write(json.dumps(cache[key], separators=(",", ":")) + "\n")
    with (dest / "wordnet-conflict-context.tsv").open("x", encoding="utf8", newline="") as stream:
        writer = csv.writer(stream, delimiter="\t", lineterminator="\n")
        writer.writerow(fieldnames)
        writer.writerows(table)
    extra = [cache[k] for k in sorted(actual_conflicts)]
    compiled = make_package(service_rows)
    (dest / "wordnet-conflict-package.json").write_bytes(
        (json.dumps(compiled, indent=2) + "\n").encode()
    )
    primary_all = set().union(*(set(r["edges"]) for r in primary))
    primary_need = {
        e
        for r in primary
        for i, e in enumerate(r["edges"])
        if (int(r["depart_ab"]["needed"], 16) | int(r["depart_ba"]["needed"], 16)) >> i & 1
    }
    result = {
        "ranked_words": len(words),
        "ranked_words_sha256": sha256("\n".join(words).encode()).hexdigest(),
        "unordered_candidates": len(words) * (len(words) - 1) // 2,
        "strict_directed_relations": nforward,
        "reciprocal_pairs": len(primary),
        "registered": compare(primary),
        "primary_unique_proof_edges": len(primary_all),
        "primary_unique_decision_edges": len(primary_need),
        "context_unique_proof_edges": len({e for key in context_records for e in cache[key]["edges"]}),
        "context_unique_decision_edges": len(compiled["facts"]),
        "real_queries": groups,
        "real_bilateral_cases": extra,
    }
    (dest / "wordnet-conflict-results.json").write_bytes(
        (json.dumps(result, indent=2) + "\n").encode()
    )
    return result


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    for name in ("archive", "ledger", "new_output"):
        p.add_argument(name, type=Path)
    a = p.parse_args()
    v = run(a.archive, a.ledger, a.new_output)
    print(json.dumps({k: value for k, value in v.items() if k != "real_bilateral_cases"}, indent=2))
