"""Sharp full-window odds after directional audits of all smaller windows."""

from fractions import Fraction as F
from math import comb


def avoidance(counts, size):
    """Probability that a given size-subset of requests all refuses."""
    w = len(counts) - 1
    return sum(q * comb(w - j, size) for j, q in enumerate(counts)) / F(comb(w, size))


def constructed(width, rate, p0, q0):
    """Residual count distributions with extremal avoidance at fixed zero mass."""
    mean = width * rate / (1 - p0)
    j = mean.numerator // mean.denominator
    q = [F(0)] * (width + 1)
    p = q.copy()
    p[0], q[0] = p0, q0
    p[j] = (1 - p0) * (1 + j - mean)
    if j < width:
        p[j + 1] = (1 - p0) * (mean - j)
    q[1] = width * (1 - rate - q0) / (width - 1)
    q[-1] = 1 - q[0] - q[1]
    return p, q


def worst_full_ratio(width, audited, rate, floor):
    """Return an exact ratio and joint success-count witnesses for P and Q.

    Both worlds use the same single-request success rate. Their only shared
    reply on each coordinate is refusal. All windows up to audited must have
    refusal odds at most one in the P-to-Q direction.
    """
    rate, floor = F(rate), F(floor)
    if (
        type(width) is not int
        or type(audited) is not int
        or not 1 <= audited <= width
        or width < 2
    ):
        raise ValueError(
            "audit between one and all requests, with at least two requests"
        )
    if not 0 < rate < 1 or not 0 < floor < 1:
        raise ValueError("rate and floor must both lie strictly between zero and one")
    mean = width * rate
    lo, hi = max(F(0), 1 - mean), 1 - rate
    gain = 1 - floor
    base = floor * (1 - rate) ** width

    def ratio(p, q):
        return (base + gain * p) / (base + gain * q)

    if audited == 1:
        optimum, p0, q0 = ratio(hi, lo), hi, lo
    else:
        slope = F(audited - 1, width - 1)
        offset = (1 - slope) * (1 - rate)
        denominator = comb(width, audited)
        chance = [F(comb(width - j, audited), denominator) for j in range(width + 1)]

        def minimum_observed(zero):
            m = mean / (1 - zero)
            j = m.numerator // m.denominator
            lower = (1 + j - m) * chance[j]
            upper = (m - j) * chance[j + 1] if j < width else 0
            return zero + (1 - zero) * (lower + upper)

        breaks = [
            lo,
            *(1 - mean / j for j in range(1, width + 1) if lo < 1 - mean / j < hi),
            hi,
        ]
        curve = [(x, minimum_observed(x)) for x in breaks]
        turning = offset + slope * lo
        eligible = list(curve)
        for (x, a), (y, b) in zip(curve, curve[1:]):
            if a < turning < b:
                eligible.append((x + (y - x) * (turning - a) / (b - a), turning))
        options = [
            (r, x, y)
            for x, z in eligible
            if (y := max(lo, (z - offset) / slope)) <= hi
            if (r := ratio(x, y)) >= 1
        ]
        optimum, p0, q0 = max(options, key=lambda v: (v[0], -v[2], -v[1]))

    first, second = constructed(width, rate, p0, q0)
    product = [
        F(comb(width, j)) * rate**j * (1 - rate) ** (width - j)
        for j in range(width + 1)
    ]
    return optimum, [
        [floor * a + gain * b for a, b in zip(product, row, strict=True)]
        for row in (first, second)
    ]


def main():
    import argparse
    import json

    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("requests", type=int)
    p.add_argument("audited", type=int)
    p.add_argument("answer_rate", type=F)
    p.add_argument("independent_fraction", type=F)
    p.add_argument(
        "--target",
        type=F,
        help="also find the least audit depth guaranteeing this ratio",
    )
    args = p.parse_args()
    try:
        ratio, (first, second) = worst_full_ratio(
            args.requests,
            args.audited,
            args.answer_rate,
            args.independent_fraction,
        )
    except ValueError as error:
        p.exit(2, f"{error}\n")
    result = dict(
        ratio=str(ratio),
        full_refusal=[str(first[0]), str(second[0])],
        gap_at_ratio_optimum=str(first[0] - second[0]),
        success_count_laws=[list(map(str, c)) for c in (first, second)],
    )
    if args.target is not None:
        if args.target < 1:
            p.error("target must be at least one")
        lo, hi = 1, args.requests
        while lo < hi:
            k = (lo + hi) // 2
            bound, _ = worst_full_ratio(
                args.requests, k, args.answer_rate, args.independent_fraction
            )
            if bound <= args.target:
                hi = k
            else:
                lo = k + 1
        result["minimum_depth_at_target"] = lo
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
