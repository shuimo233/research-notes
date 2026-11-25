"""Certify all-refusal odds when two worlds have different refusal rates."""

from collections import Counter
from fractions import Fraction as F
from itertools import product
from math import comb, prod

from audit_parity import equality_lp


def groups(first, second):
    return tuple(sorted(Counter(zip(first, second, strict=True)).items()))


def contract(first, second, gamma, caps):
    first, second = (tuple(map(F, row)) for row in (first, second))
    gamma, caps = F(gamma), tuple(map(F, caps))
    if (
        len(first) < 2
        or len(first) != len(second)
        or not all(0 < r < 1 for r in (*first, *second))
        or not 0 < gamma < 1
        or len(caps) >= len(first)
        or any(b < 1 for b in caps)
    ):
        raise ValueError(
            "expected matching interior rates, an interior floor and caps >= 1"
        )
    return first, second, gamma, caps


def fixed(first, second, gamma, caps):
    """Return the maximum *normalized* directional odds and exact LP evidence."""
    first, second, gamma, caps = contract(first, second, gamma, caps)
    gg = groups(first, second)
    cells = list(product(*(range(n + 1) for _, n in gg)))
    n = len(cells)
    zeros = [0] * n
    a = [[1] * n + [-1] * n]
    for i, (pair, size) in enumerate(gg):
        a.extend(
            (
                [c[i] - size * pair[0] for c in cells] + zeros,
                zeros + [c[i] - size * pair[1] for c in cells],
            )
        )
    floor = gamma / (1 - gamma)
    rules = []
    for types in product(*(range(min(size, len(caps) + 1) + 1) for _, size in gg)):
        depth = sum(types)
        if not 2 <= depth <= len(caps) + 1:
            continue
        cap = caps[depth - 2]
        exposure = [
            F(
                prod(comb(j, t) for j, t in zip(c, types, strict=True)),
                prod(comb(size, t) for (_, size), t in zip(gg, types, strict=True)),
            )
            for c in cells
        ]
        p, q = (
            prod(pair[i] ** t for (pair, _), t in zip(gg, types, strict=True))
            for i in (0, 1)
        )
        positive = [v / p for v in exposure]
        negative = [v / q for v in exposure]
        offset = (1 - cap) * floor
        rules.append((positive + [offset - cap * v for v in negative], cap != 1))
        if cap != 1:
            rules.append(
                ([-cap * v for v in positive] + [v + offset for v in negative], True)
            )

    a.append(zeros + [floor] * (n - 1) + [floor + 1 / prod(second)])
    b = [0] * (len(a) - 1) + [1]
    c = [floor] * (n - 1) + [floor + 1 / prod(first)] + zeros
    slacks = sum(slack for _, slack in rules)
    a = [row + [0] * slacks for row in a]
    j = 0
    for row, slack in rules:
        a.append(row + [int(slack and i == j) for i in range(slacks)])
        b.append(0)
        j += slack
    value, solution, dual = equality_lp(a, b, c + [0] * slacks)
    return dict(
        odds=str(value),
        support=[[i, str(v)] for i, v in enumerate(solution) if v],
        dual=list(map(str, dual)),
        cells=n,
    )


def bounds(low, high, second, gamma, caps, tolerance, limit):
    """Cover a directional refusal-rate box with exact endpoint certificates.

    The denominator is fixed at its lowest allowed refusal vector. A node
    stores evidence only at the lower corner of its numerator refusal box.
    """
    low, second, gamma, caps = contract(low, second, gamma, caps)
    high, _, _, _ = contract(high, second, gamma, caps)
    tolerance = F(tolerance)
    if (
        any(a > b for a, b in zip(low, high, strict=True))
        or tolerance <= 1
        or limit < 0
    ):
        raise ValueError(
            "expected an ordered box, relative tolerance > 1 and split limit >= 0"
        )
    proofs = {}

    def node(a, b):
        if a not in proofs:
            proofs[a] = fixed(a, second, gamma, caps)
        scaled = F(proofs[a]["odds"]) / prod(second)
        return scaled * prod(a), scaled * prod(b)

    def key(point):
        return " ".join(map(str, point))

    lower, upper = node(low, high)
    incumbent = low
    witnessed_high = node(high, high)[0]
    if witnessed_high > lower:
        lower, incumbent = witnessed_high, high
    plan = {}
    pending = [(upper, "", low, high)]
    for _ in range(limit):
        upper, path, a, b = max(pending)
        if upper <= tolerance * lower:
            break
        # Split in log-volume order without enumerating any real probabilities.
        i = max(range(len(a)), key=lambda j: b[j] / a[j])
        mid = (a[i] + b[i]) / 2
        plan[path] = i
        pending.remove((upper, path, a, b))
        for label, child_a, child_b in (
            ("0", a, b[:i] + (mid,) + b[i + 1 :]),
            ("1", a[:i] + (mid,) + a[i + 1 :], b),
        ):
            achieved, possible = node(child_a, child_b)
            if achieved > lower:
                lower, incumbent = achieved, child_a
            pending.append((possible, path + label, child_a, child_b))

    needed = {incumbent, low, high} | {a for _, _, a, _ in pending}
    return dict(
        lower=str(lower),
        upper=str(max(row[0] for row in pending)),
        witness=key(incumbent),
        splits=plan,
        points={key(a): proofs[a] for a in sorted(needed)},
    )


def main():
    import argparse
    import json
    from pathlib import Path

    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("contract", type=Path)
    cli.add_argument("--tolerance", type=F, default=F(21, 20))
    cli.add_argument("--splits", type=int, default=128)
    arg = cli.parse_args()
    data = json.loads(arg.contract.read_text(encoding="utf-8"))
    print(
        json.dumps(
            {
                f"{a}/{b}": bounds(
                    *zip(*data[a], strict=True),
                    [row[0] for row in data[b]],
                    data["floor"],
                    data["caps"],
                    arg.tolerance,
                    arg.splits,
                )
                for a, b in (("first", "second"), ("second", "first"))
            }
        )
    )


if __name__ == "__main__":
    main()
