"""Post-holdout exact receipt when a public flag certifies a recorded rule violation."""

import argparse
from bisect import bisect_left
from functools import lru_cache
from itertools import combinations_with_replacement
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from mqm_receipt import Receipt, ballot_rows, exclusive, partition
from mqm_wmt import load, positive


def violates(ballots, cap):
    return any(len(b) > cap or (len(b) > 1 and any(exclusive(t) for t in b)) for b in ballots)


class ViolatingSpace:
    """Increasing public fallback ranks admitting at least one violating realization."""

    def __init__(self, margins, cap=5):
        self.codec = Receipt(margins, cap, relaxed=True)
        singles = self.codec.single
        fillers = [(k, d, exclusive(t)) for t, (k, d) in self.codec.margins.items() if t not in singles]
        # Designate seat zero as a witness. Track which seats the fillers occupy,
        # how many rows reach the witness, and whether one of them is exclusive.
        states = {(0, 0, False)}
        for k, d, marker in fillers:
            increments = set()
            for x in range(k + 1):
                for y in range(k - x + 1):
                    z = k - x - y
                    mask = int(x > 0) | (int(y > 0) << 1) | (int(z > 0) << 2)
                    if mask.bit_count() == d:
                        increments.add((mask, min(cap + 1, x), marker and x > 0))
            states = {(a | b, min(cap + 1, u + v), e or f)
                      for a, u, e in states for b, v, f in increments}

        @lru_cache(None)
        def possible_witness(occupied, size, marker):
            return any((occupied | fill) == 7 and
                       (size + n > cap or (size + n >= 2 and (marker or sealed)))
                       for fill, n, sealed in states)

        self.ranks = []
        for rank in range(self.codec.states):
            loads = [0, 0, 0]
            markers = [False, False, False]
            owners = self.codec.space.unrank(rank)
            for t, seat in zip(singles, owners):
                loads[seat] += self.codec.margins[t][0]
                markers[seat] |= exclusive(t)
            for w in range(3):
                occupied = sum(1 << j for j in range(3) if loads[(w + j) % 3])
                if possible_witness(occupied, loads[w], markers[w]):
                    self.ranks.append(rank)
                    break

    @property
    def bits(self):
        if not self.ranks:
            raise ValueError("no violating record realizes these margins")
        return (len(self.ranks) - 1).bit_length()

    def encode(self, owners):
        old = self.codec.space.rank(owners)
        index = bisect_left(self.ranks, old)
        if index == len(self.ranks) or self.ranks[index] != old:
            raise ValueError("partition incompatible with a certified violation")
        return index

    def decode(self, index):
        if type(index) is not int or not 0 <= index < len(self.ranks):
            raise ValueError("invalid conditional rank")
        return self.codec.space.unrank(self.ranks[index])


def exhaustive():
    types = (("major", "A"), ("minor", "B"), ("major", "Non-translation!"), ("no-error", "No-error"))
    # With three nonempty forms and at most six total rows, no form can exceed four.
    forms = [b for n in range(1, 5) for b in combinations_with_replacement(types, n)]
    observed = {}
    cases = 0
    for ballots in combinations_with_replacement(forms, 3):
        if sum(map(len, ballots)) > 6:
            continue
        cases += 1
        key = tuple(map(tuple, ballot_rows(ballots)))
        functions = observed.setdefault(key, set())
        if violates(ballots, 2):
            functions.add(tuple(sum(any(t in b for t in q) for b in ballots) >= 2
                                for q in QUERIES))
    for margins, expected in observed.items():
        space = ViolatingSpace(margins, 2)
        actual = set()
        for i in range(len(space.ranks)):
            owners = space.decode(i)
            if space.encode(owners) != i:
                raise AssertionError("failed rank round trip")
            actual.add(tuple(space.codec.with_partition(q, owners) for q in QUERIES))
        if actual != expected or len(actual) != len(space.ranks):
            raise AssertionError("constrained functions differ from enumerated raw votes")
    return {"raw_tables": cases, "margins": len(observed), "policies_per_table": len(QUERIES)}


def audit(folder, lang):
    ratings, _, _ = load(folder, lang)
    summary = dict.fromkeys(("flagged", "fewer_states", "fewer_bits", "permissive_bits",
                             "certified_bits", "permissive_major_bits", "certified_major_bits"), 0)
    for key, group in ratings.items():
        ballots = list(group.values())
        if not violates(ballots, 5):
            continue
        summary["flagged"] += 1
        space = ViolatingSpace(ballot_rows(ballots))
        old = space.codec
        owners = partition(ballots, old.single)
        if space.decode(space.encode(owners)) != owners:
            raise ValueError(f"lost source partition for {key}")
        summary["permissive_bits"] += old.bits
        summary["certified_bits"] += space.bits
        summary["fewer_states"] += len(space.ranks) < old.states
        summary["fewer_bits"] += space.bits < old.bits
        q = {t for t in old.margins if positive(t)}
        summary["permissive_major_bits"] += len(old.possible(q)) == 2
        answers = {old.with_partition(q, space.decode(i)) for i in range(len(space.ranks))}
        truth = sum(any(positive(t) for t in b) for b in ballots) >= 2
        if truth not in answers:
            raise AssertionError("actual majority missing from certified possibilities")
        summary["certified_major_bits"] += len(answers) == 2
    return {"direction": lang, **summary}


QUERIES = [set(t for j, t in enumerate((("major", "A"), ("minor", "B"), ("major", "Non-translation!")))
               if mask & (1 << j)) for mask in range(8)]


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("data", type=Path)
    args = parser.parse_args()
    print(json.dumps({"exhaustive": exhaustive(),
                      "corpora": [audit(args.data, lang) for lang in ("ende", "zhen")]}, indent=2))
