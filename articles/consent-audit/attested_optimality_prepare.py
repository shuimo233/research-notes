"""Freeze the previously verified public information gaps for the attestation study."""

import argparse
import gzip
from hashlib import sha1
import json
from pathlib import Path


PINS = {
    "transit-optimality-exact.json": "6d9c28bd4ad366b18a1569e99fe2e34894a8ad29",
    "transit-optimality-fixtures.json.gz": "daa31001487434099defdf38da0cc947bf99145f",
    "transit-optimality-packets.json.gz": "86a0e219b9f4d262b3980d1ae75ab44c903ce92b",
    "transit-optimality-packing-ledger.jsonl.gz": "63f678af43828268acae7cb2d52fd63f36d4818f",
    "public-optimality-exact.json": "f8e793a0b8042be0006174c1bb75babaf4e6ce88",
    "slack-certificate-fixtures.json.gz": "f8dba903335931b2003f351e24c3bc5baa819803",
    "public-optimality-packets.json.gz": "38632c54456c76ff237bb8bf4cf66257ed6041e7",
    "public-optimality-ledger.jsonl.gz": "373d647f4d9a946f13831a62121cd6296ff9ba31",
}


def contents(root, file):
    raw = (root / file).read_bytes()
    if sha1(f"blob {len(raw)}\0".encode() + raw).hexdigest() != PINS[file]:
        raise ValueError(f"frozen source changed: {file}")
    return gzip.decompress(raw) if file.endswith(".gz") else raw


def key(row):
    return row["job"], row.get("run")


def corpus(directory, source, prefix, release_prefix, ledger_name, exact_rows):
    truths = json.loads(contents(directory, prefix + "-fixtures.json.gz"))
    public = json.loads(contents(directory, release_prefix + "-packets.json.gz"))
    ledger = list(map(json.loads, contents(directory, ledger_name).splitlines()))
    exact = json.loads(contents(directory, release_prefix + "-exact.json"))
    wanted = {
        row["job"]: row for row in exact[exact_rows] if row["status"] == "shorter"
    }
    records = []
    for raw, packet, transcript in zip(truths, public, ledger, strict=True):
        assert key(raw) == key(packet) == key(transcript)
        job = raw["job"]
        if job not in wanted:
            continue
        initial_bad = wanted.pop(job)
        if source == "BART":
            actual = [0, *(e["second"] for e in raw["events"])]
        else:
            actual = [0, *(value for _, a, b in raw["steps"] for value in (a, b))]
        records.append(
            dict(
                source=source,
                packet=packet,
                actual=actual,
                groups=transcript["proofs"]["groups"],
                prior_counterexample=dict(
                    record=initial_bad["record"], readings=initial_bad["disclosed"]
                ),
            )
        )
    assert not wanted
    return records


def prepare(directory, output):
    bart = corpus(
        directory,
        "BART",
        "transit-optimality",
        "transit-optimality",
        "transit-optimality-packing-ledger.jsonl.gz",
        "followup",
    )
    ci = corpus(
        directory,
        "CI",
        "slack-certificate",
        "public-optimality",
        "public-optimality-ledger.jsonl.gz",
        "cases",
    )
    assert len(bart) == 34 and len(ci) == 1
    data = (json.dumps(bart + ci, separators=(",", ":")) + "\n").encode()
    output.write_bytes(gzip.compress(data, mtime=0))
    return len(bart + ci)


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("directory", type=Path)
    p.add_argument("output", type=Path)
    a = p.parse_args()
    print(json.dumps(dict(gaps=prepare(a.directory, a.output))))
