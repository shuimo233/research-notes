"""Sharp full-window odds from a profile of audited directional tolerances."""

from fractions import Fraction as F
from math import comb

from audit_depth import constructed


def needed_caps(caps):
    """Remove shallower constraints already implied for the extremal pair."""
    best = None
    whose = {}
    for depth, cap in sorted(caps.items(), reverse=True):
        if depth == 1:
            continue
        cap = F(cap)
        relative = (cap - 1) / (depth - 1)
        if best is None or relative < best:
            whose[depth] = cap
            best = relative
    return whose


def hull(lines):
    """Increasing-slope upper envelope of affine lower bounds on q(0)."""
    by_slope = {}
    for a, b in lines:
        by_slope[a] = max(b, by_slope.get(a, b))
    stack = []
    for a, b in sorted(by_slope.items()):
        while stack:
            prev_a, prev_b, prev_at = stack[-1]
            at = (prev_b - b) / (a - prev_a)
            if prev_at is None or at > prev_at:
                break
            stack.pop()
        stack.append((a, b, at if stack else None))
    return stack


def uniform_closed_form(w, k, p, gamma, B):
    """Return the simple bound when feasible at minimum denominator mass."""
    p, gamma, B = F(p), F(gamma), F(B)
    residual_min = max(F(0), 1 - w * p)
    h = F(w - k, w - 1) * (1 - p)
    c = F(k - 1, w - 1)
    floor = gamma / (1 - gamma)
    x = min(1 - p, B * (h + c * residual_min) + (B - 1) * floor * (1 - p) ** k)
    if x < 1 - w * p / (w - k + 1):
        return None
    base = floor * (1 - p) ** w
    return (base + x) / (base + residual_min)


def worst_profile(w, p, gamma, specified):
    """Solve exactly under one common marginal and a map depth -> odds cap."""
    p, gamma = F(p), F(gamma)
    caps = {k: F(v) for k, v in specified.items()}
    if type(w) is not int or w < 2 or not 0 < p < 1 or not 0 < gamma < 1:
        raise ValueError("expected at least two requests and interior probabilities")
    if any(type(k) is not int or not 1 <= k <= w or B < 1 for k, B in caps.items()):
        raise ValueError("depths must be in range and caps at least one")
    gain = 1 - gamma
    audits = needed_caps(caps)
    mean = w * p
    lo, hi = max(F(0), 1 - mean), 1 - p
    full_floor = gamma * (1 - p) ** w

    def ratio(x, y):
        return (full_floor + gain * x) / (full_floor + gain * y)

    max_ratio, p0, q0 = F(1), lo, lo
    if not audits:
        max_ratio, p0, q0 = ratio(hi, lo), hi, lo
    else:
        chance = {
            k: [F(comb(w - j, k), comb(w, k)) for j in range(w + 1)] for k in audits
        }
        right = {
            k: (
                B * F(k - 1, w - 1),
                B * F(w - k, w - 1) * (1 - p) + (B - 1) * (gamma / gain) * (1 - p) ** k,
            )
            for k, B in audits.items()
        }
        for j in range(1, w):
            left, high = max(lo, 1 - mean / j), min(hi, 1 - mean / (j + 1))
            if left > high:
                continue
            lines = [(F(0), lo)]
            for k in audits:
                a, b = chance[k][j : j + 2]
                slope, intercept = right[k]
                lines.append(
                    (
                        (1 - (j + 1) * a + j * b) / slope,
                        ((j + 1 - mean) * a + (mean - j) * b - intercept) / slope,
                    )
                )
            shell = hull(lines)
            for n, (a, b, start) in enumerate(shell):
                end = shell[n + 1][2] if n + 1 < len(shell) else None
                L = max(left, start) if start is not None else left
                U = min(high, end) if end is not None else high
                if L > U:
                    continue
                for x in (L, U):
                    y = a * x + b
                    if lo <= y <= hi and (value := ratio(x, y)) > max_ratio:
                        max_ratio, p0, q0 = value, x, y
    first, second = constructed(w, p, p0, q0)
    base = [gamma * comb(w, j) * p**j * (1 - p) ** (w - j) for j in range(w + 1)]
    return max_ratio, [
        [x + gain * y for x, y in zip(base, row, strict=True)]
        for row in (first, second)
    ]


def determining_caps(w, p, gamma, caps):
    """Find an irredundant subset certifying the same bound."""
    bound, _ = worst_profile(w, p, gamma, caps)
    retained = needed_caps(caps)
    for k in sorted(retained):
        rest = {u: v for u, v in retained.items() if u != k}
        if worst_profile(w, p, gamma, rest)[0] == bound:
            retained = rest
    return retained


def main():
    import argparse
    import json

    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("requests", type=int)
    p.add_argument("answer_rate", type=F)
    p.add_argument("independent_fraction", type=F)
    p.add_argument("caps", nargs="+", metavar="DEPTH=CAP")
    p.add_argument(
        "--explain",
        action="store_true",
        help="also find the one or two depths determining the result",
    )
    args = p.parse_args()
    try:
        entries = [raw.split("=", 1) for raw in args.caps]
        caps = {int(k): F(v) for k, v in entries}
        if len(caps) != len(entries):
            raise ValueError("specify one cap per depth")
        ratio, rows = worst_profile(
            args.requests, args.answer_rate, args.independent_fraction, caps
        )
    except (ValueError, ArithmeticError) as error:
        p.exit(2, f"{error}\n")
    result = dict(
        ratio=str(ratio),
        retained_depths=list(needed_caps(caps)),
        full_refusal=[str(row[0]) for row in rows],
        success_count_laws=[list(map(str, row)) for row in rows],
    )
    if args.explain:
        chosen = determining_caps(
            args.requests, args.answer_rate, args.independent_fraction, caps
        )
        result["determining_caps"] = {k: str(v) for k, v in chosen.items()}
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
