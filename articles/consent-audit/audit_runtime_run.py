"""Replay the registered operational comparison from archived model logits."""

import argparse
from collections import Counter, defaultdict
from fractions import Fraction as F
import gzip
from hashlib import sha256
import json
from pathlib import Path

from audit_runtime import CAP, MAX_SHARE, cases

POLICIES = "audit-runtime-policies.json.gz"
RESULTS = "audit-runtime-results.json"


def aggregate(rows):
    counts = Counter()
    max_norm, max_raw, max_loss, max_extra = F(1), F(1), F(0), F(0)
    example = None
    for index, p in rows:
        pair = F(p["limits"]["2"][0])
        full = F(p["limits"]["4"][0])
        safe = F(p["safe"])
        counts["profiles"] += 1
        counts["with_mode_variation"] += p["variation"] > 0
        counts["half_pair_fails"] += pair < MAX_SHARE
        counts["half_full_fails"] += full < MAX_SHARE
        counts["half_pair_pass_full_fail"] += pair == MAX_SHARE and full < MAX_SHARE
        counts["pair_full_mismatch"] += p["pair_full_mismatch"]
        counts["pair_all_mismatch"] += pair > safe
        counts["raw_outside_cap_at_half"] += max(map(F, p["raw_at_max"])) > CAP
        counts["moments_evaluated"] += p["moments_evaluated"]
        counts["complete_window_count"] += 11
        max_norm = max(max_norm, *map(F, p["norm_at_max"]))
        max_raw = max(max_raw, *map(F, p["raw_at_max"]))
        max_extra = max(max_extra, F(p["extra_configurations"]))
        if pair - full > max_loss:
            max_loss = pair - full
            example = index
    return {
        **counts,
        "max_norm_half": str(max_norm),
        "max_raw_half": str(max_raw),
        "max_pair_full_share_loss": str(max_loss),
        "max_extra_configurations": str(max_extra),
        "largest_mismatch_case": example,
    }


def run(prior, ledger, out):
    rows = list(cases(prior, ledger))
    sections = defaultdict(list)
    for i, (split, threshold, kind, policy) in enumerate(rows):
        sections[kind].append((i, policy))
        sections[f"{kind}/{split}/{threshold}"].append((i, policy))
    report = {
        "ledger_sha256": sha256(
            ledger.read_bytes().replace(b"\r\n", b"\n")
        ).hexdigest(),
        "sections": {k: aggregate(row) for k, row in sorted(sections.items())},
    }
    out.mkdir(parents=True, exist_ok=True)
    (out / POLICIES).write_bytes(
        gzip.compress(
            json.dumps(rows, ensure_ascii=True, separators=(",", ":")).encode(), mtime=0
        )
    )
    (out / RESULTS).write_text(
        json.dumps(report, indent=2) + "\n", encoding="utf-8", newline="\n"
    )
    print(json.dumps({k: report["sections"][k] for k in ("main", "diagnostic")}))


if __name__ == "__main__":
    cli = argparse.ArgumentParser(description=__doc__)
    for name in ("prior", "ledger", "out"):
        cli.add_argument(name, type=Path)
    arg = cli.parse_args()
    run(arg.prior, arg.ledger, arg.out)
