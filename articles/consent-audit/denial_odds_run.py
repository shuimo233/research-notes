"""Generate exact certificates from the preregistered public policy bundle."""

import argparse
from fractions import Fraction
import gzip
from hashlib import sha1
import json
from pathlib import Path

from denial_odds import distribution, verify
from selection_odds import antichains, members
from selection_odds_run import rational, solve as conditional

PIN = "04d401ec5b65d519d224f26d12a907ea679f10ff"
RATES = tuple(map(Fraction, ("1/4", "1/2", "3/4")))


def read(path):
    raw = path.read_bytes()
    if sha1(f"blob {len(raw)}\0".encode() + raw).hexdigest() != PIN:
        raise ValueError("not the preregistered selection odds bundle")
    return json.loads(gzip.decompress(raw))


def solve(n, masks, service):
    from scipy import __version__
    from scipy.optimize import linprog

    if __version__ != "1.16.3":
        raise RuntimeError("this replay pins scipy 1.16.3")
    floor = Fraction(1, 2 * n)
    minimal, maximal = antichains(masks)
    rows, rhs = [[1, *([0] * n)]], [1 - service]
    for bounds, coefficient, sign in ((minimal, service, -1), (maximal, 1, 1)):
        for mask in bounds:
            row = [float(coefficient), *([0] * n)]
            for j in members(mask):
                row[j + 1] = sign
            rows.append(row)
            mass = floor * mask.bit_count()
            rhs.append(mass if sign < 0 else 1 - mass)
    result = linprog(
        [-1, *([0] * n)],
        A_ub=rows,
        b_ub=list(map(float, rhs)),
        bounds=[(None, None), *([(0, None)] * n)],
        method="highs",
    )
    if not result.success:
        raise ArithmeticError(result.message)
    reciprocal = rational(result.x[0])
    weights = [floor + rational(w) for w in result.x[1:]]
    cap, *prices = [-rational(x) for x in result.ineqlin.marginals]
    lower = {m: p for m, p in zip(minimal, prices[: len(minimal)], strict=True) if p}
    upper = {m: p for m, p in zip(maximal, prices[len(minimal) :], strict=True) if p}
    ratio = verify(weights, reciprocal, floor, service, masks, cap, lower, upper)
    rates = [1 - distribution(weights, m, service)[-1] for m in masks]
    return dict(
        weights=list(map(str, weights)),
        reciprocal=str(reciprocal),
        floor=str(floor),
        service=str(service),
        cap_dual=str(cap),
        lower_dual=[[m, str(p)] for m, p in lower.items()],
        upper_dual=[[m, str(p)] for m, p in upper.items()],
        ratio=str(ratio),
        minimum_service=str(min(rates)),
        maximum_service=str(max(rates)),
    )


def compare(n, masks, service, joint):
    floor = Fraction(joint["floor"])
    reciprocal = Fraction(joint["reciprocal"])
    cap_rate = 1 - reciprocal
    at_cap = conditional(n, masks, floor / cap_rate)
    constant = dict(
        rate=str(cap_rate),
        conditional=at_cap,
        can_match=Fraction(at_cap["lambda"]) >= reciprocal,
    )
    fixed = dict(status="infeasible")
    if floor * max(m.bit_count() for m in masks) <= service:
        at_minimum = conditional(n, masks, floor / service)
        ratio = max(1 / (1 - service), Fraction(at_minimum["weighted_ratio"]))
        fixed = dict(status="feasible", conditional=at_minimum, ratio=str(ratio))
    return dict(fixed_at_minimum=fixed, constant_match=constant)


def summarize(packets):
    summary = {}
    for service in map(str, RATES):
        modes = [p["rates"][service] for p in packets]
        ratios = [Fraction(m["ratio"]) for m in modes]
        fixed = [m["fixed_at_minimum"] for m in modes]
        fixed_ratios = [
            Fraction(m["ratio"]) for m in fixed if m["status"] == "feasible"
        ]
        summary[service] = dict(
            strict_vs_all_constant=sum(
                not m["constant_match"]["can_match"] for m in modes
            ),
            strict_vs_fixed_at_minimum=sum(
                a["status"] == "feasible" and b < Fraction(a["ratio"])
                for a, b in zip(fixed, ratios, strict=True)
            ),
            fixed_at_minimum_infeasible=len(fixed) - len(fixed_ratios),
            maximum_joint_ratio=str(max(ratios)),
            maximum_feasible_fixed_at_minimum_ratio=str(max(fixed_ratios))
            if fixed_ratios
            else None,
        )
    return dict(
        catalogues=len(packets),
        certificates=len(packets) * len(RATES),
        rates=summary,
        primary_gate=len(packets) == 25
        and summary["1/2"]["strict_vs_all_constant"] >= 5,
    )


def run(source, output):
    packets = []
    for row in read(source):
        masks = row["odds"]["patterns"]
        n = len(row["catalogue"]["entries"])
        if not row["odds"]["no_release_possible"]:
            raise ValueError("no feasible empty pattern")
        rates = {}
        for service in RATES:
            record = solve(n, masks, service)
            rates[str(service)] = record | compare(n, masks, service, record)
        packets.append(dict(catalogue=row["catalogue"], patterns=masks, rates=rates))
    summary = summarize(packets)
    output.mkdir(parents=True, exist_ok=True)
    (output / "denial-odds-policies.json.gz").write_bytes(
        gzip.compress(
            json.dumps(packets, separators=(",", ":"), ensure_ascii=True).encode(),
            mtime=0,
        )
    )
    (output / "denial-odds-results.json").write_text(
        json.dumps(summary, indent=2) + "\n", encoding="utf-8", newline="\n"
    )
    print(json.dumps(summary))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    run(args.source, args.output)
