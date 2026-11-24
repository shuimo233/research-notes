"""Find attested two-sense noun triples realizing the constructive three-position game."""

import argparse
from collections import defaultdict
from itertools import product
from pathlib import Path
from fractions import Fraction as Q
from zipfile import ZipFile
import json
import sys

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
from go_model_fetch import verify
from wordnet_paths import NounPaths
from chain_omission import plan


def scan(archive):
    verify(archive, "3c68cd207844f071a5206f7fbed23e5c607ec02f")
    graph = NounPaths(archive)
    counts = {}
    with ZipFile(archive) as z:
        for line in z.read("wordnet/index.sense").decode("utf8").splitlines():
            key, offset, _, number = line.split()
            w, kind = key.split("%")
            if kind.startswith("1:"):
                counts[w, int(offset)] = int(number)
    words = {
        w: graph.senses(w)
        for w in graph.frequency
        if graph.frequency[w] > 0 and w in graph.index and w.isascii() and w.isalpha()
    }
    words = {w: s for w, s in words.items() if len(s) == 2}
    owners = defaultdict(list)
    for w, senses in words.items():
        for s in senses:
            owners[s].append(w)
    parents = {s: owners.keys() & graph.ancestors(s) for s in owners}

    def only_chain_edge(left, right, x, y):
        return all(
            graph.relation(a, b) == ("left_narrower" if (a, b) == (x, y) else "neither")
            for a, b in product(words[left], words[right])
        )

    count = 0
    best = None
    included = strict = stress_strict = retained = well_sampled = (
        well_sampled_strict
    ) = 0
    gains = Q(0)
    measured_example = None
    cases = []
    for x in sorted(owners):
        for y in sorted(parents[x]):
            for z in sorted(parents[y]):
                for a, b, c in product(owners[x], owners[y], owners[z]):
                    if len({a, b, c}) < 3 or not (
                        only_chain_edge(a, b, x, y)
                        and only_chain_edge(b, c, y, z)
                        and only_chain_edge(a, c, x, z)
                    ):
                        continue
                    count += 1
                    freq = [graph.frequency[w] for w in (a, b, c)]
                    key = (-min(freq), -sum(freq), a, b, c)
                    if best is None or key < best[0]:
                        best = (
                            key,
                            {
                                "words": [a, b, c],
                                "active_offsets": [x, y, z],
                                "candidates": [sorted(words[w]) for w in (a, b, c)],
                                "tagged_noun_counts": freq,
                            },
                        )
                    pairs = [
                        (
                            counts.get((w, active), 0),
                            counts.get((w, next(iter(words[w] - {active}))), 0),
                        )
                        for w, active in zip((a, b, c), (x, y, z))
                    ]
                    if any(min(pair) == 0 for pair in pairs):
                        continue
                    included += 1
                    probs = {w: Q(h, h + j) for w, (h, j) in zip((a, b, c), pairs)}
                    policy = plan(probs)
                    gap = Q(policy["pure_cost"]) - Q(policy["cost"])
                    strict += gap > 0
                    gains += gap
                    stressed = plan(
                        {w: min(Q(1), p + Q(1, 20)) for w, p in probs.items()}
                    )
                    stress_gain = Q(stressed["cost"]) < Q(stressed["pure_cost"])
                    stress_strict += stress_gain
                    retained += gap > 0 and stress_gain
                    ample = min(min(pair) for pair in pairs) >= 5
                    well_sampled += ample
                    well_sampled_strict += ample and gap > 0
                    cases.append(
                        {
                            "words": [a, b, c],
                            "active_offsets": [x, y, z],
                            "active_inactive_counts": pairs,
                            "active_marginals": {w: str(p) for w, p in probs.items()},
                            "pure_cost": policy["pure_cost"],
                            "mixed_cost": policy["cost"],
                            "upper_shifted_pure": stressed["pure_cost"],
                            "upper_shifted_mixed": stressed["cost"],
                        }
                    )
                    if gap > 0:
                        rank = (-min(min(pair) for pair in pairs), key)
                        if measured_example is None or rank < measured_example[0]:
                            measured_example = (rank, cases[-1])
    return {
        "eligible_two_sense_lemmas": len(words),
        "matching_specific_to_general_triples": count,
        "example": None if best is None else best[1],
        "both_senses_observed": included,
        "empirical_marginal_strict": strict,
        "empirical_marginal_total_gap": str(gains),
        "plus_five_points_strict": stress_strict,
        "retained_after_shift": retained,
        "at_least_five_per_sense": well_sampled,
        "at_least_five_per_sense_strict": well_sampled_strict,
        "empirical_example": None if measured_example is None else measured_example[1],
        "empirical_cases": sorted(cases, key=lambda r: r["words"]),
    }


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("wordnet", type=Path)
    p.add_argument("--output", type=Path, help="also save UTF-8 JSON")
    args = p.parse_args()
    result = json.dumps(scan(args.wordnet), indent=2)
    if args.output:
        args.output.write_bytes((result + "\n").encode())
    print(result)
