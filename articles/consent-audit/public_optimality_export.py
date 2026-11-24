"""Export the registered public packets before running any optimality proof."""

import argparse
import gzip
from hashlib import sha1
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from slack_certificate_run import archive_for


EXPECTED_BLOBS = (
    "f8dba903335931b2003f351e24c3bc5baa819803",
    "79be9d2469b572e8fd1ec0942b461a19e898c84c",
)


def verified(path, index):
    raw = path.read_bytes()
    digest = sha1(f"blob {len(raw)}\0".encode() + raw).hexdigest()
    if digest != EXPECTED_BLOBS[index]:
        raise ValueError(f"unexpected frozen input: {path}")
    return gzip.decompress(raw)


def export(fixtures, ledger, output):
    source = json.loads(verified(fixtures, 0))
    scored = map(json.loads, verified(ledger, 1).splitlines())
    public = []
    for f, r in zip(source, scored, strict=True):
        ids = {key: f[key] for key in ("repo", "run", "job")}
        assert all(r[key] == value for key, value in ids.items()) and r["solved"]
        truth, bands, bounds, targets = archive_for(f)
        public.append(
            dict(
                **ids,
                archive=dict(bands=bands, bounds=bounds, targets=targets),
                certificate=dict(
                    labels=r["labels"],
                    disclosed=[[i, truth[i]] for i in r["paths"]["optimum"]],
                ),
            )
        )
    raw = (json.dumps(public, separators=(",", ":")) + "\n").encode()
    output.write_bytes(gzip.compress(raw, mtime=0))
    return len(public)


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("fixtures", type=Path)
    p.add_argument("ledger", type=Path)
    p.add_argument("output", type=Path)
    a = p.parse_args()
    print(json.dumps(dict(packets=export(a.fixtures, a.ledger, a.output))))
