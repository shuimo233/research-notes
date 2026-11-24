"""Build and certify optimal weighted lotteries on the frozen public catalogues."""

import argparse
from fractions import Fraction
import gzip
from hashlib import sha1
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from conclusion_replay_inquiry import parse
from public_optimality import PublicAudit
from selection_odds import antichains, likelihood, members, patterns, verify

PIN = "4cfee872ef4246f25728b8aacd8ff0faf3d5eb87"


def read(path):
    raw = path.read_bytes()
    if sha1(f"blob {len(raw)}\0".encode() + raw).hexdigest() != PIN:
        raise ValueError("not the preregistered public catalogue")
    return json.loads(gzip.decompress(raw))


def rational(value):
    return Fraction(float(value)).limit_denominator(10**8)


def solve(n, masks):
    from scipy import __version__
    from scipy.optimize import linprog

    if __version__ != "1.16.3":
        raise RuntimeError("this replay pins scipy 1.16.3")
    floor = Fraction(1, 2 * n)
    minimal, maximal = antichains(masks)
    rows, rhs = [], []
    for sign, wanted in ((-1, minimal), (1, maximal)):
        for mask in wanted:
            row = [int(sign < 0), *([0] * n)]
            for i in members(mask):
                row[i + 1] = sign
            rows.append(row)
            cost = floor * mask.bit_count()
            rhs.append(cost if sign < 0 else 1 - cost)
    result = linprog(
        [-1, *([0] * n)],
        A_ub=rows,
        b_ub=[float(x) for x in rhs],
        bounds=[(None, None), *([(0, None)] * n)],
        method="highs",
    )
    if not result.success:
        raise ArithmeticError(result.message)
    value = rational(result.x[0])
    weights = [rational(v) + floor for v in result.x[1:]]
    dual = [-rational(v) for v in result.ineqlin.marginals]
    lower = {
        mask: price
        for mask, price in zip(minimal, dual[: len(minimal)], strict=True)
        if price
    }
    upper = {
        mask: price
        for mask, price in zip(maximal, dual[len(minimal) :], strict=True)
        if price
    }
    optimized = verify(weights, value, floor, masks, lower, upper)
    uniform = likelihood([Fraction(1)] * n, masks)
    assert optimized <= uniform
    return dict(
        patterns=masks,
        minimal=minimal,
        maximal=maximal,
        floor=str(floor),
        weights=list(map(str, weights)),
        **{"lambda": str(value)},
        lower_dual=[[m, str(c)] for m, c in lower.items()],
        upper_dual=[[m, str(c)] for m, c in upper.items()],
        uniform_ratio=str(uniform),
        weighted_ratio=str(optimized),
    )


def packet(entry):
    record = entry["packet"]
    audit = PublicAudit(*parse(record["archive"]), record["certificate"])
    labels = [r["comparison"] for r in entry["entries"]]
    masks, no_release, checked = patterns(audit.fibre, labels)
    cert = solve(len(labels), masks)
    return dict(
        catalogue=entry,
        odds=dict(cert, no_release_possible=no_release, checked_cells=checked),
    )


def run(source, output):
    results = [packet(f) for f in read(source)]
    raw = [r["odds"] for r in results]
    initial = [Fraction(r["uniform_ratio"]) for r in raw]
    optimized = [Fraction(r["weighted_ratio"]) for r in raw]
    gain = [old > new for old, new in zip(initial, optimized, strict=True)]
    summary = dict(
        catalogues=len(raw),
        labels=sum(len(r["weights"]) for r in raw),
        checked_cells=sum(r["checked_cells"] for r in raw),
        feasible_nonempty_patterns=sum(len(r["patterns"]) for r in raw),
        max_patterns=max(len(r["patterns"]) for r in raw),
        active_extremal_rows=sum(len(r["minimal"]) + len(r["maximal"]) for r in raw),
        dual_rows=sum(len(r["lower_dual"]) + len(r["upper_dual"]) for r in raw),
        strictly_improved=sum(gain),
        neutral_uniform=sum(v == 1 for v in initial),
        neutral_optimum=sum(v == 1 for v in optimized),
        worst_uniform=str(max(initial)),
        worst_optimum=str(max(optimized)),
        mean_uniform=str(sum(initial) / len(initial)),
        mean_optimum=str(sum(optimized) / len(optimized)),
        gate=len(raw) == 25 and sum(gain) >= 5,
    )
    output.mkdir(parents=True, exist_ok=False)
    (output / "selection-odds-results.json").write_bytes(
        (json.dumps(summary, indent=2) + "\n").encode()
    )
    packed = (json.dumps(results, separators=(",", ":")) + "\n").encode()
    (output / "selection-odds-policies.json.gz").write_bytes(
        gzip.compress(packed, mtime=0)
    )
    return summary


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("public_catalogue", type=Path)
    p.add_argument("output", type=Path)
    a = p.parse_args()
    if not __debug__:
        raise RuntimeError("enable assertions")
    print(json.dumps(run(a.public_catalogue, a.output), indent=2))
