"""Verify parity obstructions, the positive triple gadget, and separation on the Fano plane."""

import json
from fractions import Fraction as Q
from itertools import combinations, product
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fair_union_certificate import certify
from coupling_clock import certificate


def check():
    if not __debug__:
        raise RuntimeError("assertions must be enabled")
    from scipy.optimize import linprog

    pairs = list(combinations(range(4), 2))
    signed = 0
    for signs in product(range(4), repeat=len(pairs)):
        choices = {i: [[], []] for i in range(4)}
        equations = {}
        for (u, v), kind in zip(pairs, signs):
            for parity in (0, 1):
                if kind & (1 << parity):
                    key = f"{u}.{v}.{parity}"
                    choices[u][1].append(key)
                    choices[v][parity].append(key)
                    equations[key] = u, v, parity
        # Active when u=1 or v=parity. To hit with probability one, the triggers must be opposite.
        best = any(
            all(x[u] ^ x[v] == p for u, v, p in equations.values())
            for x in product(range(2), repeat=4)
        )
        r = certify(choices)
        assert (r["status"] == "attainable") == best
        if best:
            for x in r["equal_mass_worlds"]:
                assert (
                    set().union(*(set(choices[i][x[i]]) for i in choices))
                    == equations.keys()
                )
        else:
            from collections import Counter

            degrees = Counter()
            total = 0
            for key in r["odd_parity_obstruction"]:
                u, v, p = equations[key]
                degrees.update((u, v))
                total ^= p
            assert all(n % 2 == 0 for n in degrees.values()) and total == 1
        signed += 1
    # A private fourth bit and four positive triple targets implement exact balance on each gadget.
    local_cases = 0
    for world in product(range(2), repeat=4):
        misses = sum(not any(world[i] for i in e) for e in combinations(range(4), 3))
        hits = misses == 0
        assert hits == (sum(world) >= 2)
        assert int(len(set(world[:3])) == 1) <= 2 * misses - ((4 - sum(world)) - 2)
        local_cases += 1
    triples = list(combinations(range(5), 3))
    worlds = list(product(range(2), repeat=5))
    gadgets = 0
    for mask in range(1 << len(triples)):
        edges = [e for j, e in enumerate(triples) if mask >> j & 1]

        def mono(w):
            return sum(len({w[i] for i in e}) == 1 for e in edges)

        valid = [w for w in worlds if mono(w) == 0]
        # Tight marginal expectation forces each four-variable gadget to have exactly two ones.
        extendable = [
            w
            for w in worlds
            if all(
                any(sum(w[i] for i in e) + aux == 2 for aux in (0, 1)) for e in edges
            )
        ]
        assert valid == extendable
        # Independently decide if the projected support admits a fair joint distribution.
        if valid:
            lp = linprog(
                [0] * len(valid),
                A_eq=[[1] * len(valid)] + [[w[i] for w in valid] for i in range(5)],
                b_eq=[1] + [0.5] * 5,
                method="highs",
            )
            assert lp.success
        best = min(worlds, key=mono)
        four_targets_loss = 0
        for e in edges:
            bits = [best[i] for i in e]
            aux = 1 if sum(bits) <= 1 else 0
            block = bits + [aux]
            four_targets_loss += sum(
                len({block[i] for i in t}) == 1 for t in combinations(range(4), 3)
            )
        assert four_targets_loss == mono(
            best
        )  # sum over the complementary pair, before dividing by two
        gadgets += 1
    lines = sorted(
        {tuple(sorted((i, j, i ^ j))) for i, j in combinations(range(1, 8), 2)}
    )
    opts = {
        i: [[], [str(j) for j, e in enumerate(lines) if i in e]] for i in range(1, 8)
    }
    choices = {
        str(i): [(tuple(g[0]), Q(1, 2)), (tuple(g[1]), Q(1, 2))]
        for i, g in opts.items()
    }
    # Z is uniform on 3-bit strings. Each nonzero linear form vanishes for four of eight values.
    eight = [{i: int((z & i).bit_count() % 2 == 0) for i in opts} for z in range(8)]
    assert all(sum(w[i] for w in eight) == 4 for i in opts)
    cost = lambda w: sum(any(w[i] for i in e) for e in lines)
    assert all(cost(w) == 7 for w in eight)
    clock_best = max(
        Q(cost(dict(zip(opts, w))) + cost(dict(zip(opts, [1 - v for v in w]))), 2)
        for w in product(range(2), repeat=7)
    )
    assert clock_best == Q(13, 2) and certificate(choices)["status"] == "wide"

    def gadget_lp(n, edges):
        from scipy.sparse import lil_matrix

        words = list(product((0, 1), repeat=n))
        k = len(words)
        m = len(edges)
        # a_w = law of original bits. b_ew = joint mass of w and auxiliary e = 1.
        # Conditional on w, the auxiliaries may be sampled independently without changing this additive objective.
        obj = [0] * (k * (1 + m))
        eq = lil_matrix((1 + n + m, len(obj)))
        ineq = lil_matrix((k * m, len(obj)))
        for j, w in enumerate(words):
            eq[0, j] = 1
            for i, t in enumerate(w):
                eq[1 + i, j] = t
            for i, e in enumerate(edges):
                h = sum(1 - w[t] for t in e)
                from math import comb

                off = (i + 1) * k + j
                obj[j] += comb(h + 1, 3)
                obj[off] = comb(h, 3) - comb(h + 1, 3)
                eq[1 + n + i, off] = 1
                ineq[i * k + j, off] = 1
                ineq[i * k + j, j] = -1
        lp = linprog(
            obj,
            A_eq=eq.tocsr(),
            b_eq=[1] + [0.5] * (n + m),
            A_ub=ineq.tocsr(),
            b_ub=[0] * (k * m),
            method="highs",
        )
        assert lp.success
        target = Q(
            min(sum(len({w[i] for i in e}) == 1 for e in edges) for w in words), 2
        )
        primal = [Q(float(v)).limit_denominator(10**6) for v in lp.x]
        assert sum(x * c for x, c in zip(primal, obj)) == target and all(
            x >= 0 for x in primal
        )
        assert sum(primal[:k]) == 1 and all(
            sum(primal[j] * w[i] for j, w in enumerate(words)) == Q(1, 2)
            for i in range(n)
        )
        for i in range(m):
            block = primal[k * (1 + i) : k * (2 + i)]
            assert sum(block) == Q(1, 2) and all(
                v <= u for v, u in zip(block, primal[:k])
            )
        return str(target)

    deficits = [
        gadget_lp(5, triples),
        gadget_lp(7, [tuple(i - 1 for i in e) for e in lines]),
    ]
    return {
        "signed_four_source_systems": signed,
        "four_bit_gadget_rows": local_cases,
        "five_vertex_triple_hypergraphs": gadgets,
        "fano_true_maximum": 7,
        "fano_best_complementary_pair": str(clock_best),
        "fano_witness_worlds": len(eight),
        "positive_gadget_lp_deficits_complete_five_and_fano": deficits,
    }


if __name__ == "__main__":
    print(json.dumps(check(), indent=2))
