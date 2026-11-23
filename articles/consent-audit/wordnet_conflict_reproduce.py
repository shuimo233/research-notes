"""Regenerate the preregistered WordNet results and compare all published artifacts."""

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
from go_model_fetch import fetch_verified
from wordnet_conflict import run
from wordnet_conflict_check import check

SOURCE = (
    "https://raw.githubusercontent.com/nltk/nltk_data/"
    "96f9b3252457a2b97e52aec64c3dfceeb5c312d5/packages/corpora/wordnet.zip"
)
DIGEST = "3c68cd207844f071a5206f7fbed23e5c607ec02f"
ARTIFACTS = (
    "wordnet-conflict-results.json",
    "wordnet-conflict-ledger.jsonl",
    "wordnet-conflict-context.tsv",
    "wordnet-conflict-context-proofs.jsonl",
    "wordnet-conflict-package.json",
    "wordnet-conflict-checks.json",
)


def reproduce(archive, output, url):
    if not __debug__:
        raise RuntimeError("run without -O so the independent checks execute")
    fetch_verified(archive, url, DIGEST)
    ledger = ROOT / "monli-scope-ledger.tsv"
    run(archive, ledger, output)
    checks = check(archive, ledger, output)
    (output / ARTIFACTS[-1]).write_bytes((json.dumps(checks, indent=2) + "\n").encode())
    for name in ARTIFACTS:
        release = (ROOT / name).read_bytes().replace(b"\r\n", b"\n")
        if (output / name).read_bytes() != release:
            raise ValueError(f"generated artifact differs from release: {name}")
    return checks


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path, help="verified local archive or new download path")
    parser.add_argument("new_output", type=Path, help="directory that does not yet exist")
    parser.add_argument("--url", default=SOURCE, help="alternate download URL for identical bytes")
    args = parser.parse_args()
    print(json.dumps(reproduce(args.archive, args.new_output, args.url), indent=2))
