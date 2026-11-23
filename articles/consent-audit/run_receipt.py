"""Trusted, fixed-layout receipts for a three-source ordered replica export.

Cut coordinates run from 1 through n. A SAME check on rows low and high+1
is stored as one bit: 1 for DIFFERENT, i.e. a cut in [low, high].
"""

from bisect import bisect_right
from collections import defaultdict
from dataclasses import dataclass, field
import argparse
import json
from pathlib import Path


def ceil_log2(value):
    return (value - 1).bit_length()


@dataclass
class Signature:
    starts: list = field(default_factory=list)
    offsets: list = field(default_factory=list)
    size: int = 0
    last: int = 0
    has_left: bool = False
    has_right: bool = False

    def append(self, start, stop):
        self.starts.append(start)
        self.offsets.append(self.size)
        self.size += stop - start
        self.last = stop - 1

    def rank(self, cut):
        run = bisect_right(self.starts, cut) - 1
        return int(self.has_left) + self.offsets[run] + cut - self.starts[run]

    @property
    def alphabet(self):
        return max(1, ceil_log2(self.size + self.has_left + self.has_right))


class RunReceipt:
    def __init__(self, n, intervals=()):
        if type(n) is not int or n < 2:
            raise ValueError("need at least two candidate cut positions")
        self.n = n
        self.intervals = []
        changes = defaultdict(int, {1: 0, n+1: 0})
        for k, (low, high) in enumerate(intervals):
            if type(low) is not int or type(high) is not int or not 1 <= low <= high <= n:
                raise ValueError("check intervals must be nonempty and within 1..n")
            self.intervals.append((low, high))
            changes[low] ^= 1 << k
            changes[high+1] ^= 1 << k
        self.starts = sorted(changes)[:-1]
        self.masks = []
        self.groups = {}
        mask = 0
        for start, stop in zip(self.starts, self.starts[1:] + [n+1]):
            mask ^= changes[start]
            self.masks.append(mask)
            self.groups.setdefault(mask, Signature()).append(start, stop)
        for mask, group in self.groups.items():
            for other, candidate in self.groups.items():
                if other != mask and (other & mask) == other:
                    group.has_left |= candidate.starts[0] < group.starts[0]
                    group.has_right |= candidate.last > group.last
        self.symbols = max(group.alphabet for group in self.groups.values())
        self.bits = ceil_log2(self.symbols)

    def signature(self, cut):
        if type(cut) is not int or not 1 <= cut <= self.n:
            raise ValueError("cut outside 1..n")
        return self.masks[bisect_right(self.starts, cut) - 1]

    def describe(self):
        return {"cut_positions": self.n, "existing_bits": len(self.intervals),
                "extra_symbols": self.symbols, "extra_bits": self.bits,
                "signature_counts": [
                    {"mask": mask, "points": g.size, "left": g.has_left, "right": g.has_right,
                     "extra_symbols": g.alphabet} for mask, g in self.groups.items()]}

    def issue(self, first_cut, second_cut):
        first = self.signature(first_cut)
        second = self.signature(second_cut)
        if first_cut >= second_cut:
            raise ValueError("the two cuts must be in increasing order")
        existing = first | second
        tag = 0
        if first == existing or second == existing:
            group = self.groups[existing]
            low = group.rank(first_cut) if first == existing else 0
            high = group.rank(second_cut) if second == existing else int(group.has_left) + group.size
            tag = (low ^ high).bit_length() - 1
        return {"existing": existing, "tag": tag}

    def decide(self, receipt, word):
        """Under the documented source/trust assumptions, return the three-root majority."""
        if not isinstance(receipt, dict) or set(receipt) != {"existing", "tag"}:
            raise ValueError("need existing and tag fields")
        existing, tag = receipt["existing"], receipt["tag"]
        if (type(existing) is not int or not 0 <= existing < (1 << len(self.intervals))
                or type(tag) is not int or not 0 <= tag < self.symbols):
            raise ValueError("receipt field outside its declared width or alphabet")
        if (not isinstance(word, (bytes, bytearray, list, tuple)) or len(word) != self.n+1
                or any(type(bit) is not int or bit not in (0, 1) for bit in word)):
            raise ValueError("expected n+1 binary rows")
        jumps = []
        for cut in range(1, len(word)):
            if word[cut] != word[cut-1]:
                jumps.append(cut)
                if len(jumps) > 2:
                    raise ValueError("more changes than a three-run export can contain")
        if not jumps:
            return int(word[0])
        if len(jumps) == 2:
            if self.issue(*jumps) != receipt:
                raise ValueError("visible cuts contradict the receipt")
            return int(word[0])
        cut = jumps[0]
        visible = self.signature(cut)
        if visible & ~existing:
            raise ValueError("visible cut contradicts the existing checks")
        if visible == existing:
            group = self.groups[visible]
            if tag >= group.alphabet:
                raise ValueError("tag outside this signature's alphabet")
            second_cut = (group.rank(cut) >> tag) & 1
        else:
            missing = existing & ~visible
            # All missing intervals must contain the other cut, on one side of this one.
            low, high = 1, self.n
            while missing:
                selected = missing & -missing
                a, b = self.intervals[selected.bit_length()-1]
                low, high = max(low, a), min(high, b)
                missing ^= selected
            if low > high:
                raise ValueError("no other cut can explain all the existing checks")
            second_cut = high < cut
        return int(word[0] if second_cut else word[-1])


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path, help="JSON with n, intervals, and optional cuts or receipt and word")
    args = parser.parse_args()
    try:
        request = json.loads(args.input.read_text(encoding="utf-8-sig"))
        codec = RunReceipt(request["n"], request["intervals"])
        if "word" in request:
            result = {"root_majority": codec.decide(request["receipt"], request["word"])}
        elif "cuts" in request:
            result = codec.issue(*request["cuts"])
        else:
            result = codec.describe()
        print(json.dumps(result, indent=2))
    except (ValueError, KeyError, TypeError, OSError) as error:
        parser.exit(2, f"{error}\n")
