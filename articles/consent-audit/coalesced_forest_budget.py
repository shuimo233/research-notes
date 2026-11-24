"""Check a forest after merging targets that are always triggered in exactly the same worlds."""

import argparse
from collections import defaultdict
from fractions import Fraction as Q
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from coupling_clock import canonical
from forest_cover_budget import forest_bounds


def bounds(groups):
    sources = canonical(groups)
    signatures = defaultdict(list)
    for u, choices in sources.items():
        for k, (vs, _) in enumerate(choices):
            for v in vs:
                signatures[v].append((u, k))
    merged = {}
    counts = {}
    for v, sig in signatures.items():
        key = tuple(sig)
        rep = merged.setdefault(key, v)
        counts[rep] = counts.get(rep, 0) + 1
    projected = {
        u: [({merged[tuple(signatures[v])] for v in vs}, p) for vs, p in choices]
        for u, choices in sources.items()
    }
    if forest_bounds(projected) is None:
        return None
    lo, hi = Q(0), Q(0)
    for sig, representative in merged.items():
        probs = defaultdict(Q)
        for u, i in sig:
            probs[u] += sources[u][i][1]
        lo += counts[representative] * max(probs.values())
        hi += counts[representative] * min(1, sum(probs.values()))
    return {
        "minimum_extra": str(lo),
        "maximum_extra": str(hi),
        "target_count": len(signatures),
        "distinct_signatures": len(merged),
    }


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("groups", type=Path)
    a = p.parse_args()
    print(json.dumps(bounds(json.loads(a.groups.read_bytes())), indent=2))
