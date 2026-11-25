"""A sharp three-request policy for the complete Boolean support family."""

from fractions import Fraction
from math import comb
from secrets import SystemRandom, randbelow

from denial_odds import choose
from selection_odds import members

HALF = Fraction(1, 2)


def subsets(mask):
    return [s for s in range(mask + 1) if s & mask == s]


def pair_cap_complete_cube(pair_cap):
    """Return the least full ratio and one policy preserving the given pair cap."""
    bound = Fraction(pair_cap)
    if bound < 3:
        raise ValueError("pair ratios below three are impossible on the complete cube")
    b = min(bound, Fraction(7, 2))
    optimum = max(Fraction(32, 7), 4 + 2 / b, (b + 2) / (b - 2))
    t = 1 / b
    v = HALF / optimum
    w = t / optimum
    u = HALF - 2 * v - w
    z = HALF - v - 2 * w
    triangular = [
        [Fraction(1)],
        [HALF, HALF],
        [t, HALF - t, t],
        [u, v, w, z],
    ]
    policy = {
        state: {
            answer: triangular[state.bit_count()][answer.bit_count()]
            for answer in subsets(state)
        }
        for state in range(8)
    }
    return optimum, policy


def rounded_count(eligible):
    lower, remainder = divmod(2 * eligible, 3)
    if not remainder:
        return {lower: Fraction(1)}
    return {lower: Fraction(3 - remainder, 3), lower + 1: Fraction(remainder, 3)}


def window_bias_law(pair_bound, high_bias):
    """Return a shared-bias law for any number of windows with the same pair cap."""
    cap = min(Fraction(pair_bound), Fraction(4))
    high = Fraction(high_bias)
    if cap < 3 or not 4 / cap - HALF < high < 1:
        raise ValueError(
            "high bias must lie strictly between the growth threshold minus one and one"
        )
    low = high / (1 + high)
    if cap == 4:
        low_mass = (high - HALF) / (high - low)
        return {low: low_mass / 2, HALF: HALF, high: (1 - low_mass) / 2}
    second = 2 / cap - Fraction(1, 4)
    low_mass = (high / 2 - second) / (low * (high - low))
    high_mass = (second - low / 2) / (high * (high - low))
    unused = 1 - low_mass - high_mass
    if unused < 0:
        raise ValueError("choose a high bias closer to the threshold")
    return {Fraction(0): unused / 2, low: low_mass / 2, HALF: HALF, high: high_mass / 2}


def projected_probability(eligible, observed, released):
    """Probability of a specific visible pattern from the three-part mechanism."""
    if not 0 <= released <= observed <= eligible:
        raise ValueError("inconsistent visible counts")
    hidden = eligible - observed
    fixed = sum(
        (
            p * Fraction(comb(hidden, count - released), comb(eligible, count))
            for count, p in rounded_count(eligible).items()
            if 0 <= count - released <= hidden
        ),
        Fraction(0),
    )
    return (
        Fraction(1, 2 ** (observed + 1))
        + Fraction(2 ** (observed - released), 4 * 3**observed)
        + fixed / 4
    )


def sample(eligible):
    """Draw one complete truthful reply mask, then reuse its projections."""
    if type(eligible) is not int or eligible < 0:
        raise ValueError("eligible requests must be a nonnegative mask")
    candidates = list(members(eligible))
    branch = randbelow(4)
    if branch < 2:
        chosen = [j for j in candidates if randbelow(2) == 0]
    elif branch == 2:
        chosen = [j for j in candidates if randbelow(3) == 0]
    else:
        size = choose(rounded_count(len(candidates)))
        chosen = SystemRandom().sample(candidates, size)
    return sum(1 << j for j in chosen)
