"""Verify route limits against full outcome tables from published scores."""

import argparse
import csv
from fractions import Fraction as F
from functools import cache
import gzip
from hashlib import sha1, sha256
from itertools import combinations, product
import json
from math import prod
from pathlib import Path
from struct import unpack

WIDTHS = (0, 16, 24, 32, 48, 64, 96, 128)
LEVELS = ("0", "1/4", "1/2", "1", "2", "4")
LIMIT = F(21, 20)
HALF = F(1, 2)
ATOMS = list(product((0, 1), repeat=4))
PRESETS_IF_INDEPENDENT = F(sum(len(set(m)) for m in product(WIDTHS, repeat=4)), 8**4)


def tsv(data):
    return list(csv.DictReader(data.decode().splitlines(), delimiter="\t"))


def binary_policy(row, tag, threshold):
    e, n, c = [
        F(unpack("<f", int(row[tag + "_" + q], 16).to_bytes(4, "little"))[0])
        for q in "ENC"
    ]
    rival = max(n, c)
    if row["gold"] == "entailment":
        return e > rival and e >= rival + threshold
    assert row["gold"] == "neutral"
    return rival > e and rival >= e + threshold


@cache
def atom_laws(accept):
    refusals = [
        [F(1, 20) if releases else F(19, 20) for releases in row] for row in accept
    ]
    means = [sum(row) / 8 for row in refusals]
    independent, shared = {}, {}
    for response in ATOMS:
        independent[response] = prod(
            p if b else 1 - p for b, p in zip(response, means, strict=True)
        )
        shared[response] = (
            sum(
                prod(p if b else 1 - p for b, p in zip(response, ps, strict=True))
                for ps in zip(*refusals, strict=True)
            )
            / 8
        )
    assert sum(independent.values()) == sum(shared.values()) == 1
    return independent, shared


def audit_policy(certificate, paired_rows, threshold):
    accept = [
        tuple(
            tuple(binary_policy(pair[world][1], f"w{w}", threshold) for w in WIDTHS)
            for pair in paired_rows
        )
        for world in range(2)
    ]
    assert certificate["pairs"] == [[a[0]["id"], b[0]["id"]] for a, b in paired_rows]
    assert certificate["variation"] == sum(
        len(set(row)) > 1 for world in accept for row in world
    )
    active = [i for i in range(4) if any(len(set(world[i])) > 1 for world in accept)]
    assert certificate["active"] == active
    assert certificate["moments_evaluated"] == sum(
        len(list(combinations(active, size))) for size in (2, 3, 4)
    )
    full_laws = [atom_laws(world) for world in accept]
    windows = {}

    def events(which):
        return [
            tuple(
                sum(prob for a, prob in law.items() if all(a[i] for i in which))
                for law in both
            )
            for both in full_laws
        ]

    for i in range(4):
        for world, (independent, shared) in enumerate(events([i])):
            assert independent == shared == F(certificate["rates"][world][i])
    for size in (2, 3, 4):
        for subset in combinations(range(4), size):
            windows[subset] = events(subset)

    def normalized(window, sharing):
        return [((1 - sharing) * i + sharing * s) / i for i, s in windows[window]]

    by_size = {}
    for size in (2, 3, 4):
        value, witness = certificate["limits"][str(size)]
        share = F(value)
        assert 0 <= share <= HALF
        by_size[size] = share
        for window in windows:
            if len(window) == size:
                a, b = normalized(window, share)
                assert max(a, b) <= LIMIT * min(a, b)
        if share != HALF:
            which, direction = witness
            assert len(which) == size and type(direction) is int and direction in (0, 1)
            values = normalized(tuple(which), share)
            assert values[direction] == LIMIT * values[1 - direction]
            values = normalized(tuple(which), HALF)
            assert values[direction] > LIMIT * values[1 - direction]
        else:
            assert witness is None
    pair, full = by_size[2], by_size[4]
    safe = min(by_size.values())
    assert F(certificate["safe"]) == safe
    assert certificate["pair_full_mismatch"] is (pair > full)
    n1, n2 = normalized((0, 1, 2, 3), HALF)
    i1, i2 = [entry[0] for entry in windows[(0, 1, 2, 3)]]
    assert list(map(F, certificate["norm_at_max"])) == [n1 / n2, n2 / n1]
    assert list(map(F, certificate["raw_at_max"])) == [
        n1 * i1 / (n2 * i2),
        n2 * i2 / (n1 * i1),
    ]
    a, b = normalized((0, 1, 2, 3), pair)
    assert list(map(F, certificate["norm_at_pair_limit"])) == [a / b, b / a]
    assert (max(a, b) > LIMIT * min(a, b)) is (pair > full)
    extra = (pair - safe) * (PRESETS_IF_INDEPENDENT - 1)
    assert F(certificate["extra_configurations"]) == extra
    return (
        pair,
        full,
        safe,
        max(n1 / n2, n2 / n1),
        max(n1 * i1 / (n2 * i2), n2 * i2 / (n1 * i1)),
        extra,
    )


def audit(prior, ledger, out):
    p = prior.read_bytes().replace(b"\r\n", b"\n")
    assert (
        sha1(f"blob {len(p)}\0".encode() + p).hexdigest()
        == "1e88b3aea682d3e005cd27a6b1b5349fa8c0c8d1"
    )
    raw = ledger.read_bytes().replace(b"\r\n", b"\n")
    old = tsv(p)
    revised = tsv(raw)
    assert len(old) == len(revised) == 1672
    groups = {}
    for a, b in zip(old, revised, strict=True):
        assert all(
            a[k] == b[k] for k in ("subset", "id", "premise", "hypothesis", "gold")
        )
        assert all(a["single_" + x] == b["w0_" + x] for x in "ENC")
        length = int(b["length"])
        assert 0 < length <= 512
        for i, w in enumerate(WIDTHS):
            for z in WIDTHS[:i]:
                if max(w, length) == max(z, length):
                    assert all(b[f"w{w}_{c}"] == b[f"w{z}_{c}"] for c in "ENC")
        batch = groups.setdefault(a["subset"], {})
        key = a["premise"], a["hypothesis"]
        assert key not in batch
        batch[key] = a, b
    assert {g: len(v) for g, v in groups.items()} == {
        "nmonli_test": 200,
        "pmonli": 1472,
    }
    rows = iter(
        json.loads(
            gzip.decompress((out / "audit-runtime-policies.json.gz").read_bytes())
        )
    )
    summary = {}
    idx = 0
    for split, items in groups.items():
        pairs = []
        for a, b in sorted(k for k in items if k[0] < k[1]):
            token = sha256(("runtime/v1/" + a + b).encode()).digest()
            r = (items[a, b], items[b, a])
            assert {x[0]["gold"] for x in r} == {"entailment", "neutral"}
            pairs.append((token, r if token[-1] % 2 == 0 else r[::-1]))
        assert 2 * len(pairs) == len(items)
        for level in LEVELS:
            threshold = F(level)
            natural = sorted(pairs)

            def old_rank(x):
                token, r = x
                votes = []
                for prev, _ in r:
                    votes.extend(
                        binary_policy(prev, mode, threshold)
                        for mode in ("single", "mixed")
                    )
                disagreements = (votes[0] != votes[1]) + (votes[2] != votes[3])
                return -disagreements, votes, token

            for collection, ordered in (
                ("main", natural),
                ("diagnostic", sorted(pairs, key=old_rank)),
            ):
                for i in range(0, len(ordered), 4):
                    s, t, k, record = next(rows)
                    assert (s, t, k) == (split, level, collection)
                    models = [p for _, p in ordered[i : i + 4]]
                    pair, full, safe, norm, raw_odds, extra = audit_policy(
                        record, models, threshold
                    )
                    for scope in (collection, f"{collection}/{split}/{level}"):
                        state = summary.setdefault(
                            scope,
                            {
                                "profiles": 0,
                                "with_mode_variation": 0,
                                "half_pair_fails": 0,
                                "half_full_fails": 0,
                                "half_pair_pass_full_fail": 0,
                                "pair_full_mismatch": 0,
                                "pair_all_mismatch": 0,
                                "raw_outside_cap_at_half": 0,
                                "moments_evaluated": 0,
                                "complete_window_count": 0,
                                "max_norm_half": F(1),
                                "max_raw_half": F(1),
                                "max_pair_full_share_loss": F(0),
                                "max_extra_configurations": F(0),
                                "largest_mismatch_case": None,
                            },
                        )
                        for key, added in (
                            ("profiles", 1),
                            ("with_mode_variation", record["variation"] > 0),
                            ("half_pair_fails", pair < HALF),
                            ("half_full_fails", full < HALF),
                            ("half_pair_pass_full_fail", pair == HALF and full < HALF),
                            ("pair_full_mismatch", pair > full),
                            ("pair_all_mismatch", pair > safe),
                            ("raw_outside_cap_at_half", raw_odds > LIMIT),
                            ("moments_evaluated", record["moments_evaluated"]),
                            ("complete_window_count", len(ATOMS) - 5),
                        ):
                            state[key] += added
                        if pair - full > state["max_pair_full_share_loss"]:
                            state["largest_mismatch_case"] = idx
                            state["max_pair_full_share_loss"] = pair - full
                        for flag, num in (
                            ("max_norm_half", norm),
                            ("max_raw_half", raw_odds),
                            ("max_extra_configurations", extra),
                        ):
                            state[flag] = max(state[flag], num)
                    idx += 1
    assert next(rows, None) is None and idx == 2508
    result = {
        "ledger_sha256": sha256(raw).hexdigest(),
        "sections": {
            k: {x: str(y) if isinstance(y, F) else y for x, y in s.items()}
            for k, s in summary.items()
        },
    }
    assert result == json.loads((out / "audit-runtime-results.json").read_bytes())
    return {
        "verified": True,
        "profiles": idx,
        "scores": 1672 * 8 * 3,
        "ledger": result["ledger_sha256"],
    }


if __name__ == "__main__":
    cli = argparse.ArgumentParser(description=__doc__)
    for name in ("prior", "ledger", "output"):
        cli.add_argument(name, type=Path)
    args = cli.parse_args()
    print(json.dumps(audit(args.prior, args.ledger, args.output)))
