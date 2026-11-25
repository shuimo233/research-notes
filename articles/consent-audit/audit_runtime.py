"""Compile exact sharing limits from finite, individually validated model routes."""

import csv
from fractions import Fraction as F
from hashlib import sha1, sha256
from itertools import batched, combinations
from math import prod
import struct

MODES = (0, 16, 24, 32, 48, 64, 96, 128)
THRESHOLDS = (F(0), F(1, 4), F(1, 2), F(1), F(2), F(4))
CAP = F(21, 20)
MAX_SHARE = F(1, 2)
PRIOR = "1e88b3aea682d3e005cd27a6b1b5349fa8c0c8d1"
EXPECTED = {"nmonli_test": 200, "pmonli": 1472}


def prior_rows(path):
    raw = path.read_bytes().replace(b"\r\n", b"\n")
    if sha1(f"blob {len(raw)}\0".encode() + raw).hexdigest() != PRIOR:
        raise ValueError("expected the frozen singleton/mixed model archive")
    return {
        (row["subset"], row["id"]): row
        for row in csv.DictReader(raw.decode().splitlines(), delimiter="\t")
    }


def signed(row, mode):
    a, b, c = (
        F(struct.unpack(">f", bytes.fromhex(row[f"{mode}_{key}"]))[0]) for key in "ENC"
    )
    return (a - max(b, c)) * (1 if row["gold"] == "entailment" else -1)


def guard(margin, threshold):
    return margin > 0 and margin >= threshold


def load_data(prior, ledger):
    before = prior_rows(prior)
    rows = {}
    with ledger.open(encoding="utf-8", newline="") as stream:
        for row in csv.DictReader(stream, delimiter="\t"):
            key = row["subset"], row["id"]
            orig = before[key]
            if (
                key in rows
                or any(row[k] != orig[k] for k in ("premise", "hypothesis", "gold"))
                or any(row[f"w0_{c}"] != orig[f"single_{c}"] for c in "ENC")
                or not 0 < int(row["length"]) <= 512
            ):
                raise ValueError(f"invalid inference record {key}")
            size = int(row["length"])
            for i, mode in enumerate(MODES):
                alias = next(
                    m for m in MODES[: i + 1] if max(m, size) == max(mode, size)
                )
                if any(row[f"w{mode}_{c}"] != row[f"w{alias}_{c}"] for c in "ENC"):
                    raise ValueError(f"inconsistent effective width {key}")
            rows[key] = (
                row,
                tuple(signed(row, f"w{j}") for j in MODES),
                tuple(signed(orig, j) for j in ("single", "mixed")),
            )
    if set(rows) != set(before):
        raise ValueError("the model record is incomplete")
    all_pairs = {}
    for split, n in EXPECTED.items():
        lookup = {
            (v[0]["premise"], v[0]["hypothesis"]): v
            for (subset, _), v in rows.items()
            if subset == split
        }
        if len(lookup) != n:
            raise ValueError(f"invalid source length {split}")
        matched = []
        for (a, b), first in lookup.items():
            if a >= b:
                continue
            second = lookup[b, a]
            if {first[0]["gold"], second[0]["gold"]} != {"entailment", "neutral"}:
                raise ValueError("expected oppositely labelled directions")
            tag = sha256(f"runtime/v1/{a}{b}".encode()).digest()
            matched.append((tag, (second, first) if tag[-1] & 1 else (first, second)))
        if len(matched) * 2 != n:
            raise ValueError("unpaired observations")
        all_pairs[split] = sorted(matched)
    return all_pairs


def one_case(pairs, threshold):
    rates = tuple(
        tuple(
            tuple(F(1, 20) if guard(x, threshold) else F(19, 20) for x in pair[w][1])
            for pair in pairs
        )
        for w in range(2)
    )
    profile = sharing_plan(rates)
    profile["pairs"] = [[pair[0][0]["id"], pair[1][0]["id"]] for pair in pairs]
    return profile


def sharing_plan(rates, cap=CAP, max_share=MAX_SHARE):
    """Use conditional refusal rates indexed by [world][request][configuration]."""
    cap, max_share = F(cap), F(max_share)
    rates = tuple(tuple(tuple(map(F, items)) for items in world) for world in rates)
    if len(rates) != 2 or len(rates[0]) != len(rates[1]) or len(rates[0]) < 2:
        raise ValueError("expected two worlds with the same requests")
    w = len(rates[0])
    m = len(rates[0][0])
    if (
        cap < 1
        or not 0 <= max_share <= 1
        or not m
        or any(
            len(row) != m or not all(0 < p < 1 for p in row)
            for world in rates
            for row in world
        )
    ):
        raise ValueError("expected equally many modes and nondegenerate rates")
    means = [[sum(a) / m for a in world] for world in rates]
    changes = [[len(set(row)) > 1 for row in world] for world in rates]
    active, constant = [], []
    for i in range(w):
        (active if changes[0][i] or changes[1][i] else constant).append(i)
    bounds = {size: (max_share, None) for size in range(2, w + 1)}
    full_delta = [0, 0]
    for size in range(2, len(active) + 1):
        for subset in combinations(active, size):
            increments = []
            for world, mu in zip(rates, means, strict=True):
                base = prod(mu[i] for i in subset)
                shared = sum(prod(world[i][j] for i in subset) for j in range(m)) / m
                increments.append((shared - base) / base)
            if size == len(active):
                full_delta = increments
            for side in range(2):
                slope = increments[side] - cap * increments[1 - side]
                if slope > 0:
                    limit = (cap - 1) / slope
                    for extra in range(len(constant) + 1):
                        depth = size + extra
                        if limit < bounds[depth][0]:
                            witness = sorted((*subset, *constant[:extra]))
                            bounds[depth] = (limit, [witness, side])
    pair, full = bounds[2][0], bounds[w][0]
    safe = min(x[0] for x in bounds.values())
    base = [prod(mu) for mu in means]

    def ratios(share):
        a, b = (1 + share * d for d in full_delta)
        normal = a / b
        raw = normal * base[0] / base[1]
        return [str(normal), str(1 / normal)], [str(raw), str(1 / raw)]

    upper_norm, upper_raw = ratios(max_share)
    pair_norm, _ = ratios(pair)
    distinct = m * (1 - F(m - 1, m) ** w)
    return {
        "variation": sum(sum(world) for world in changes),
        "active": active,
        "moments_evaluated": 2 ** len(active) - len(active) - 1,
        "rates": [[str(r) for r in mu] for mu in means],
        "limits": {
            str(size): [str(limit), marker] for size, (limit, marker) in bounds.items()
        },
        "safe": str(safe),
        "pair_full_mismatch": pair > full,
        "extra_configurations": str((pair - safe) * (distinct - 1)),
        "norm_at_max": upper_norm,
        "raw_at_max": upper_raw,
        "norm_at_pair_limit": pair_norm,
    }


def cases(prior, ledger):
    all_pairs = load_data(prior, ledger)
    for split, pairs in all_pairs.items():
        for threshold in THRESHOLDS:

            def rank(marked):
                tag, pair = marked
                bits = tuple(guard(x, threshold) for p in pair for x in p[2])
                return -(int(bits[0] != bits[1]) + int(bits[2] != bits[3])), bits, tag

            for kind, sorted_pairs in (
                ("main", pairs),
                ("diagnostic", sorted(pairs, key=rank)),
            ):
                for group in batched((p for _, p in sorted_pairs), 4, strict=True):
                    yield split, str(threshold), kind, one_case(group, threshold)
