"""Post-registration controls giving competing fallback rules the same labeled lexical evidence."""

import argparse
import csv
from functools import lru_cache
from hashlib import sha1
import json
from pathlib import Path
import shutil
from tempfile import TemporaryDirectory


WORDNET_BLOB = "3c68cd207844f071a5206f7fbed23e5c607ec02f"


def compare(ledger, archive):
    import nltk
    from nltk.corpus import wordnet

    data = archive.read_bytes()
    if sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest() != WORDNET_BLOB:
        raise ValueError("expected pinned WordNet 3.0 zip")
    with ledger.open(encoding="utf8", newline="") as f:
        rows = list(csv.DictReader(f, delimiter="\t"))
    output = {}
    with TemporaryDirectory() as tmp:
        corpora = Path(tmp) / "corpora"
        corpora.mkdir()
        shutil.copyfile(archive, corpora / "wordnet.zip")
        nltk.data.path.insert(0, tmp)
        try:
            if wordnet.get_version() != "3.0":
                raise ValueError("expected WordNet 3.0")

            @lru_cache(None)
            def sense_sets(term):
                senses = set(wordnet.synsets(term, pos=wordnet.NOUN))
                ancestors = set()
                for syn in senses:
                    ancestors.update(syn.closure(lambda s: s.hypernyms() + s.instance_hypernyms()))
                return senses, ancestors

            for subset in ("nmonli_train", "nmonli_test"):
                totals = {
                    name: {"correct": 0, "evidence_pairs": 0, "evidence_correct": 0}
                    for name in (
                        "direct_then_signed",
                        "direct_then_blind",
                        "graph_then_blind",
                        "wordnet_then_signed",
                        "wordnet_then_blind",
                    )
                }
                taxonomy = {"both": 0, "neither": 0, "unique": 0}
                for r in (r for r in rows if r["subset"] == subset):
                    lines = r["positive_source_lines"].split()
                    graph = r["evidence_first"] if lines else None
                    direct = graph if len(lines) == 1 else None
                    a, up_a = sense_sets(r["a_term"])
                    b, up_b = sense_sets(r["b_term"])
                    ab, ba = bool(b & up_a), bool(a & up_b)
                    taxonomy["unique" if ab != ba else ("both" if ab else "neither")] += 1
                    external = ("reverse" if ab else "forward") if ab != ba else None
                    for name, source, fallback in (
                        ("direct_then_signed", direct, "invert_affirmative"),
                        ("direct_then_blind", direct, "invert_original"),
                        ("graph_then_blind", graph, "invert_original"),
                        ("wordnet_then_signed", external, "invert_affirmative"),
                        ("wordnet_then_blind", external, "invert_original"),
                    ):
                        t = totals[name]
                        t["evidence_pairs"] += source is not None
                        t["evidence_correct"] += source == r["gold"]
                        t["correct"] += (source or r[fallback]) == r["gold"]
                output[subset] = {"controls": totals, "wordnet_lookup": taxonomy}
        finally:
            nltk.data.path.remove(tmp)
    return output


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("ledger", type=Path)
    p.add_argument("wordnet_zip", type=Path)
    a = p.parse_args()
    print(json.dumps(compare(a.ledger, a.wordnet_zip), indent=2))
