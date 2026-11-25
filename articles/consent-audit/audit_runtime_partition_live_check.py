"""Recheck the published route trace against the seeded protocol and model log."""

import argparse
from bisect import bisect_right
import csv
from fractions import Fraction as F
import gzip
from hashlib import sha256
from itertools import accumulate
import json
from math import lcm
from pathlib import Path
from random import Random
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from audit_runtime_drift_check import LOGITS, PREVIOUS, WIDTHS, pinned
from audit_runtime_partition_check import PIN
from audit_runtime_check import binary_policy


def verify(ledger, archive, drift, dest):
    prior = json.loads(gzip.decompress(pinned(archive.read_bytes(), PREVIOUS)))
    shift = json.loads(gzip.decompress(pinned(drift.read_bytes(), PIN)))
    plans = json.loads(
        gzip.decompress(
            (dest / "audit-runtime-partition-policies.json.gz").read_bytes()
        )
    )
    actual = iter(
        json.loads(
            gzip.decompress(
                (dest / "audit-runtime-partition-live.json.gz").read_bytes()
            )
        )
    )
    raw = pinned(ledger.read_bytes().replace(b"\r\n", b"\n"), LOGITS)
    table = {
        (x["subset"], x["id"]): x
        for x in csv.DictReader(raw.decode().splitlines(), delimiter="\t")
    }
    rng = Random(10441168)
    batches = 0
    full_bits = 0
    for j in (1044, 1168):
        section, cut, kind, old = prior[j]
        assert section == "pmonli" and kind == "main"
        pairs = old["pairs"]
        cutoff = F(cut)
        existing = shift[j]
        u = list(map(F, existing["witness"]["contamination"]))
        solo = [[i] for i in range(4)]
        for dist, weights in (
            ("center", [F(1, 8)] * 8),
            ("witness", [(F(3, 8) + v) / 4 for v in u]),
        ):
            denominator = lcm(*(p.denominator for p in weights))
            cumulative = list(accumulate(int(denominator * v) for v in weights))
            for baseline, groups, independence in (
                ("independent", solo, F(1)),
                ("scalar", [[0, 1, 2, 3]], 1 - F(existing["safe"])),
                ("partition", plans[j]["partition"]["blocks"], F(1, 2)),
            ):
                cond = next(actual)
                assert (cond["case"], cond["distribution"], cond["policy"]) == (
                    j,
                    dist,
                    baseline,
                )
                assert list(map(F, cond["weights"])) == weights
                assert len(cond["batches"]) == 24
                digest = sha256()
                distinct = 0
                for trial in cond["batches"]:
                    chosen = rng.randrange(independence.denominator)
                    chosen_blocks = solo if chosen < independence.numerator else groups
                    chosen_routes = {}
                    for group in chosen_blocks:
                        mode = bisect_right(cumulative, rng.randrange(denominator))
                        chosen_routes.update(dict.fromkeys(group, mode))
                    modes = [chosen_routes[i] for i in range(4)]
                    assert modes == trial["modes"]
                    expected = []
                    for world in range(2):
                        coins = [rng.randrange(20) for _ in modes]
                        assert coins == trial["coins"][world]
                        votes = []
                        for i, m in enumerate(modes):
                            ident = pairs[i][world]
                            item = table[section, ident]
                            tag = f"w{WIDTHS[m]}"
                            bits = [item[f"{tag}_{x}"] for x in "ENC"]
                            digest.update(
                                (
                                    "/".join((section, ident, str(m), *bits)) + "\n"
                                ).encode()
                            )
                            outcome = binary_policy(item, tag, cutoff)
                            votes.append(
                                int(not (coins[i] == 1 or (coins[i] >= 2 and outcome)))
                            )
                            full_bits += 3
                        expected.append(votes)
                    assert expected == trial["denied"]
                    distinct += len(set(modes))
                    batches += 1
                assert F(cond["mean_configurations"]) == F(distinct, 24)
                assert digest.hexdigest() == cond["score_sha256"]
    assert next(actual, None) is None and batches == 288 and full_bits == 6912
    print(
        json.dumps(
            {"verified": True, "batches": batches, "score_bit_patterns": full_bits}
        )
    )


if __name__ == "__main__":
    cli = argparse.ArgumentParser(description=__doc__)
    for n in ("ledger", "archive", "drift", "destination"):
        cli.add_argument(n, type=Path)
    args = cli.parse_args()
    verify(args.ledger, args.archive, args.drift, args.destination)
