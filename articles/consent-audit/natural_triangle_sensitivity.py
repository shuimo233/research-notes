"""Compare chosen natural positive types under uniform, historical and add-one marginal frequencies."""

import argparse
from fractions import Fraction as Q
import json
from pathlib import Path
import sys
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
from go_model_fetch import verify
from mixed_sense_game import solve
from wordnet_paths import NounPaths
from chain_omission import plan


def run(wordnet, types):
    verify(wordnet, "3c68cd207844f071a5206f7fbed23e5c607ec02f")
    with ZipFile(wordnet) as z:
        counts = {
            (k.split("%")[0], int(o)): int(n)
            for k, o, _, n in (
                l.split() for l in z.read("wordnet/index.sense").decode().splitlines()
            )
            if "%1:" in k
        }
    graph = NounPaths(wordnet)
    result = []
    for line in types.read_bytes().splitlines():
        r = json.loads(line)
        if Q(r["value"]) == Q(r["pure"]):
            continue
        names = r["words"]
        categories = {
            u: {
                x: tuple(
                    v
                    for v in names
                    if v != u
                    and len({graph.relation(x, y) for y in graph.senses(v)}) > 1
                )
                for x in sorted(graph.senses(u))
            }
            for u in names
        }
        is_chain_game = all(
            not f or set(f) == set(names) - {u}
            for u, opts in categories.items()
            for f in opts.values()
        )
        record = {
            "words": names,
            "all_or_none_triggers": is_chain_game,
            "sense_counts": {
                u: {str(x): counts.get((u, x), 0) for x in opts}
                for u, opts in categories.items()
            },
        }
        for prior in ("uniform", "tag_count", "add_one"):
            groups = {}
            active = {}
            for u, opts in categories.items():
                weights = {
                    x: 1
                    if prior == "uniform"
                    else counts.get((u, x), 0) + int(prior == "add_one")
                    for x in opts
                }
                total = sum(weights.values())
                if not total:
                    raise ValueError(f"no historical tags for {u}")
                groups[u] = [(f, Q(weights[x], total)) for x, f in opts.items()]
                active[u] = sum(p for f, p in groups[u] if f)
            pure = min(
                2 + min(1, sum(p for g in groups.values() for f, p in g if v in f))
                for v in names
            )
            mixed = Q(solve(groups)["value"])
            if is_chain_game:
                formula = plan(active)
                assert (Q(formula["pure_cost"]), Q(formula["cost"])) == (pure, mixed)
            if prior == "uniform":
                assert (str(pure), str(mixed)) == (r["pure"], r["value"])
            record[prior] = {
                "active_any": {u: str(p) for u, p in active.items()},
                "pure": str(pure),
                "mixed": str(mixed),
            }
        result.append(record)
    return result


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("wordnet", type=Path)
    p.add_argument("types", type=Path)
    p.add_argument("--output", type=Path)
    a = p.parse_args()
    text = json.dumps(run(a.wordnet, a.types), indent=2)
    if a.output:
        a.output.write_bytes((text + "\n").encode())
    print(text)
