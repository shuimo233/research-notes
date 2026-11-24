"""Ask for a token sense or return all requested relations for a sentence."""

import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from go_model_fetch import verify
from shared_sense import SharedInquiry
from wordnet_paths import NounPaths


def query(archive, batch, observed, policy):
    verify(archive, "3c68cd207844f071a5206f7fbed23e5c607ec02f")
    graph = NounPaths(archive)
    words = batch["words"]
    service = SharedInquiry(
        {i: graph.senses(w) for i, w in words.items()}, batch["pairs"], graph.relation
    )
    action, value = service.next(observed, policy)
    if action == "answers":
        return {"answers": [[u, v, label] for (u, v), label in value.items()]}
    from zipfile import ZipFile

    with ZipFile(archive) as z, z.open("wordnet/data.noun") as f:
        allowed = set(service.domains[value])
        choices = {
            line[:8].decode(): line.partition(b"|")[2].decode().strip()
            for line in f
            if line[:8].isdigit() and int(line[:8]) in allowed
        }
    return {"ask": value, "word": words[value], "choices": choices}


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("wordnet", type=Path)
    p.add_argument(
        "batch",
        type=Path,
        help="JSON with words (ID to lemma) and pairs (ordered ID pairs)",
    )
    p.add_argument("--sense", action="append", default=[], metavar="ID=OFFSET")
    p.add_argument(
        "--policy",
        choices=(
            "cover",
            "greedy",
            "forward_more",
            "reverse_more",
            "forward_table",
            "reverse_table",
        ),
        default="cover",
    )
    a = p.parse_args()
    try:
        observed = {}
        for raw in a.sense:
            key, val = raw.rsplit("=", 1)
            if observed.setdefault(key, int(val)) != int(val):
                raise ValueError(f"conflicting assignments for {key}")
        print(
            json.dumps(
                query(a.wordnet, json.loads(a.batch.read_bytes()), observed, a.policy),
                indent=2,
            )
        )
    except (ValueError, KeyError) as error:
        p.error(str(error))
