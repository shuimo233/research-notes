"""Check the chain policy with all binary worlds, exact rational saddle arithmetic and an independent LP."""

from collections import Counter
from fractions import Fraction as Q
from itertools import combinations_with_replacement, product
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from chain_omission import plan, compare


def expand(adverse):
    law = Counter(
        {frozenset((u,)): Q(p) for u, p in adverse.get("singletons", {}).items()}
    )
    law[frozenset()] += Q(adverse.get("empty", "0"))
    if "systematic_mass" in adverse:
        mass = Q(adverse["systematic_mass"])
        spans = []
        end = Q(0)
        for u, p in adverse["inclusion"].items():
            start = end
            end += Q(p)
            spans.append((u, start, end))
        breaks = sorted({Q(0), Q(1)} | {b % 1 for _, _, b in spans})
        for lo, hi in zip(breaks, breaks[1:]):
            offset = (lo + hi) / 2
            active = frozenset(
                u
                for u, a, b in spans
                if any(a <= offset + j < b for j in range(int(end) + 1))
            )
            law[active] += (hi - lo) * mass
    assert sum(law.values()) == 1 and all(p >= 0 for p in law.values())
    return law


def check():
    if not __debug__:
        raise RuntimeError("enable assertions")
    from scipy.optimize import linprog

    count = strict = proper = 0
    for n in range(2, 7):
        vertices = tuple(map(str, range(n)))
        worlds = [
            frozenset(u for u, x in zip(vertices, bits) if x)
            for bits in product((0, 1), repeat=n)
        ]
        saves = [[int(w <= {u}) for u in vertices] for w in worlds]
        # Independent LP chooses a joint law to minimize the largest pure omission saving.
        ub = [[s[i] for s in saves] + [-1] for i in range(n)]
        eq = [[1] * len(worlds) + [0]] + [
            [int(u in w) for w in worlds] + [0] for u in vertices
        ]
        for ps in combinations_with_replacement([Q(j, 4) for j in range(5)], n):
            result = plan(dict(zip(vertices, ps)))
            law = expand(result["adverse"])
            assert all(
                sum(weight for w, weight in law.items() if u in w) == p
                for u, p in zip(vertices, ps)
            )
            limit = n - Q(result["cost"])
            pay = {
                u: sum(weight for w, weight in law.items() if w <= {u})
                for u in vertices
            }
            assert max(pay.values()) == limit
            selected = set(result["omit_uniformly_from"])
            assert all(pay[u] == limit for u in selected)
            # Verify the policy's lower bound independently by a second optimization on its world payouts.
            objective = [
                sum(s[i] for i, u in enumerate(vertices) if u in selected)
                / len(selected)
                for s in saves
            ]
            b = list(map(float, (1, *ps)))
            worst = linprog(
                objective, A_eq=[row[:-1] for row in eq], b_eq=b, method="highs"
            )
            optimum = linprog(
                [0] * len(worlds) + [1],
                A_eq=eq,
                b_eq=b,
                A_ub=ub,
                b_ub=[0] * n,
                method="highs",
            )
            assert (
                worst.success
                and optimum.success
                and max(abs(worst.fun - float(limit)), abs(optimum.fun - float(limit)))
                < 1e-9
            )
            if len(set(ps)) == 1:
                p = ps[0]
                homogeneous = max(Q(0), 1 - (n - 1) * p, (2 - n * p) / n)
                assert homogeneous == limit
            count += 1
            strict += Q(result["cost"]) < Q(result["pure_cost"])
            proper += 1 < len(selected) < n
    fair = plan(dict.fromkeys(("A", "B", "C"), "1/2"))
    assert fair["cost"] == "17/6" and fair["pure_cost"] == "3"
    from mixed_sense_game import solve

    for ps in (("1/2",) * 3, ("1/2", "9/20", "2/5", "1/20"), ("0", "0", "0")):
        probabilities = {str(i): Q(p) for i, p in enumerate(ps)}
        groups = {
            u: [((), 1 - p), (sorted(probabilities.keys() - {u}), p)]
            for u, p in probabilities.items()
        }
        result = solve(groups)
        assert result["value"] == plan(probabilities)["cost"] and result[
            "covers"
        ] == len(ps)
    named = plan(dict(zip("ABCD", ("1/2", "9/20", "2/5", "1/20"))))
    assert (
        named["cost"] == "229/60"
        and named["pure_cost"] == "39/10"
        and named["omit_uniformly_from"] == list("ABC")
    )
    runs = 0
    for marginals in (
        dict.fromkeys("ABC", "1/2"),
        dict(zip("ABCD", ("1/2", "9/20", "2/5", "1/20"))),
    ):
        for bits in product((False, True), repeat=len(marginals)):
            truth = dict(zip(marginals, bits))
            for omit in plan(marginals)["omit_uniformly_from"]:
                batches = []

                def ask(batch):
                    batches.append(list(batch))
                    return {u: truth[u] for u in batch}

                actual = compare(marginals, marginals, ask, lambda options: omit)
                assert actual["batches"] == batches and (omit not in batches[0])
                assert len(batches) == 1 + int(any(truth[u] for u in batches[0]))
                assert len(actual["relations"]) == len(bits) * (len(bits) - 1) // 2
                for u, v, label in actual["relations"]:
                    assert label == (
                        "left_narrower" if truth[u] and truth[v] else "neither"
                    )
                runs += 1
    print(
        f"{count} marginal vectors; {count * 2} LP comparisons; {strict} strict improvements; {proper} proper-prefix policies; {runs} complete interaction traces verified"
    )


if __name__ == "__main__":
    check()
