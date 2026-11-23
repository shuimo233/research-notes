"""Cross-check two label semantics against one pinned third-party released Parquet column."""

import argparse
from hashlib import sha256
import json
from pathlib import Path
import duckdb

DIGEST = "027e4f400a93f72a3b0f01a2cc6bd42c666d53524528a1040149eedd5d889854"
VOCAB = ("anger", "disgust", "fear", "joy", "sadness", "surprise", "neutral")


def check(parquet, comparison):
    if sha256(parquet.read_bytes()).hexdigest() != DIGEST:
        raise ValueError("unexpected third-party test file")
    with comparison.open(encoding="utf8") as stream:
        release = {r["id"]: r for r in map(json.loads, stream)}
    with duckdb.connect(":memory:") as db:
        rows = db.execute("SELECT id, labels_ekman FROM read_parquet(?)", [str(parquet)]).fetchall()
    if len(rows) != len(release) or {k for k, _ in rows} != release.keys():
        raise ValueError("test keys differ")
    official_diff = person_diff = differing_pairs = 0
    for key, labels in rows:
        if any(type(i) is not int or not 0 <= i < len(VOCAB) for i in labels):
            raise ValueError("unexpected third-party label index")
        actual = {VOCAB[i] for i in labels}
        source = release[key]
        if source["status"] != "ok":
            raise ValueError("unresolved source annotations")
        official_diff += actual != set(source["published_ekman"])
        people = set(source["two_reporters_ekman"])
        person_diff += actual != people
        differing_pairs += len(actual ^ people)
    return {"third_party_revision": "36b96f67e724026cac6210b857d1fe388bd46048",
            "test_sha256": DIGEST, "items": len(rows), "different_from_mapped_release": official_diff,
            "different_from_two_people": person_diff, "item_label_disagreements_with_two_people": differing_pairs}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("parquet", type=Path)
    parser.add_argument("comparison", type=Path)
    args = parser.parse_args()
    print(json.dumps(check(args.parquet, args.comparison), indent=2))
