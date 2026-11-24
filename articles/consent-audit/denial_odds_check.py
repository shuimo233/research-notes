"""Reconstruct feasible patterns and verify denial-inclusive certificates without a solver."""

import argparse
from fractions import Fraction
import gzip
from hashlib import sha1
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from public_optimality_check import model
from selection_odds_check import independent_patterns, score

PIN = "04d401ec5b65d519d224f26d12a907ea679f10ff"
SERVICES = ("1/4", "1/2", "3/4")


def unpack_prices(rows, masks):
    prices = {m: Fraction(v) for m, v in rows}
    assert len(prices) == len(rows) and prices.keys() <= set(masks)
    assert all(x > 0 for x in prices.values())
    return prices


def masses(weights, masks):
    return {m: sum(w for j, w in enumerate(weights) if m >> j & 1) for m in masks}


def dual(record, k, masks, floor, refusal):
    weights = list(map(Fraction, record["weights"]))
    low = unpack_prices(record["lower_dual"], masks)
    high = unpack_prices(record["upper_dual"], masks)
    assert len(weights) == k and all(w >= floor for w in weights)
    assert Fraction(record["floor"]) == floor
    incidence = [
        sum(value for m, value in high.items() if m >> j & 1)
        - sum(value for m, value in low.items() if m >> j & 1)
        for j in range(k)
    ]
    assert min(incidence) >= 0
    bound = sum(high.values()) - floor * sum(incidence)
    mass = masses(weights, masks)
    if refusal:
        service = Fraction(record["service"])
        cap = Fraction(record["cap_dual"])
        r = Fraction(record["reciprocal"])
        assert 0 < service < 1 and 0 < r <= 1 - service and cap >= 0
        assert cap + service * sum(low.values()) + sum(high.values()) == 1
        assert bound + cap * (1 - service) == r
        assert service * r <= min(mass.values()) <= max(mass.values()) <= 1 - r
        emissions = {-1: [Fraction(1)], **{j: [] for j in range(k)}}
        rates = []
        for m, weight in mass.items():
            rate = max(service, weight)
            assert service <= rate < 1
            row = [w * rate / weight for j, w in enumerate(weights) if m >> j & 1]
            assert sum(row) == rate and min(row) >= floor
            emissions[-1].append(1 - rate)
            rates.append(rate)
            for j, p in zip((j for j in range(k) if m >> j & 1), row, strict=True):
                emissions[j].append(p)
        assert min(rates) == Fraction(record["minimum_service"])
        assert max(rates) == Fraction(record["maximum_service"])
        reconstructed = max(max(values) / min(values) for values in emissions.values())
        assert reconstructed == Fraction(record["ratio"]) == 1 / r
        return r

    r = Fraction(record["lambda"])
    assert 0 < r <= 1 and bound == r and sum(low.values()) == 1
    assert min(mass.values()) == r and max(mass.values()) <= 1
    assert record["patterns"] == masks
    assert score(weights, masks, floor) == Fraction(record["weighted_ratio"]) == 1 / r
    assert score([Fraction(1)] * k, masks, floor) == Fraction(record["uniform_ratio"])
    return r


def check(source, output):
    raw = source.read_bytes()
    assert sha1(f"blob {len(raw)}\0".encode() + raw).hexdigest() == PIN
    frozen = json.loads(gzip.decompress(raw))
    published = json.loads(
        gzip.decompress((output / "denial-odds-policies.json.gz").read_bytes())
    )
    report = json.loads((output / "denial-odds-results.json").read_bytes())
    collected = {s: [] for s in SERVICES}
    patterns = 0
    for original, new in zip(frozen, published, strict=True):
        catalogue = new["catalogue"]
        assert catalogue == original["catalogue"]
        size, _, _, _, edges, _, _ = model(catalogue["packet"])
        k = len(catalogue["entries"])
        floor = Fraction(1, 2 * k)
        zero, *masks = independent_patterns(size, edges, catalogue["entries"])
        assert zero == 0 and original["odds"]["no_release_possible"]
        assert masks == new["patterns"] == original["odds"]["patterns"]
        assert set(new["rates"]) == set(SERVICES)
        patterns += len(masks)
        for tag in SERVICES:
            service = Fraction(tag)
            entry = new["rates"][tag]
            assert Fraction(entry["service"]) == service
            r = dual(entry, k, masks, floor, True)

            match = entry["constant_match"]
            assert Fraction(match["rate"]) == 1 - r
            candidate = dual(match["conditional"], k, masks, floor / (1 - r), False)
            assert match["can_match"] is (candidate >= r)

            fixed = entry["fixed_at_minimum"]
            densest = max(m.bit_count() for m in masks)
            at_minimum = None
            if service < floor * densest:
                assert fixed == {"status": "infeasible"}
            else:
                assert fixed["status"] == "feasible"
                conditional = dual(
                    fixed["conditional"], k, masks, floor / service, False
                )
                at_minimum = max(1 / conditional, 1 / (1 - service))
                assert at_minimum == Fraction(fixed["ratio"]) >= 1 / r
                assert match["can_match"] is (conditional >= 1 - service)
            collected[tag].append((1 / r, at_minimum, candidate < r))

    rates = {}
    for tag, rows in collected.items():
        fixed = [b for _, b, _ in rows if b is not None]
        rates[tag] = dict(
            strict_vs_all_constant=sum(flag for _, _, flag in rows),
            strict_vs_fixed_at_minimum=sum(b is not None and a < b for a, b, _ in rows),
            fixed_at_minimum_infeasible=len(rows) - len(fixed),
            maximum_joint_ratio=str(max(a for a, _, _ in rows)),
            maximum_feasible_fixed_at_minimum_ratio=str(max(fixed)) if fixed else None,
        )
    expected = dict(
        catalogues=len(published),
        certificates=len(published) * len(SERVICES),
        rates=rates,
        primary_gate=len(published) == 25
        and rates["1/2"]["strict_vs_all_constant"] >= 5,
    )
    assert expected == report
    return expected | {"feasible_nonempty_patterns": patterns, "verified": True}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    if not __debug__:
        raise RuntimeError("enable assertions")
    print(json.dumps(check(args.source, args.output)))
