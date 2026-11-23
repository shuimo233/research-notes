"""Score the registered MoNLI interventions with a frozen, checksum-verified NLI checkpoint."""

import argparse
import csv
from hashlib import sha256
import json
from pathlib import Path
import sys

import numpy as np
from tokenizers import Tokenizer

sys.path.insert(0, str(Path(__file__).resolve().parent))
from go_model_fetch import verify
from monli_direction import SOURCES, fetch_data
from monli_direction_score import choose_direction
from monli_scope import LexicalEvidence, affirmative, changed_terms, decide_downward_pair, opposite
from point_reinfer import feed
from point_runtime import make_session
from rte_context_fetch import FILES


ALL_SOURCES = {**SOURCES, "nmonli_train": "5f369cd74dda2f514583571bd320a4de39b69451"}
NEGATIVE = ("nmonli_train", "nmonli_test")
LOGIT_FIELDS = [
    f"{condition}_{orientation}_{label}"
    for condition in ("original", "affirmative")
    for orientation in ("ab", "ba")
    for label in "ENC"
]
METHODS = ("original", "invert_original", "affirmative", "invert_affirmative", "evidence_first")


def read_source(folder, name):
    path = folder / (name + ".jsonl")
    verify(path, ALL_SOURCES[name])
    return [json.loads(s) for s in path.read_bytes().splitlines()]


def reciprocal(rows):
    indexed = {}
    for i, r in enumerate(rows, 1):
        a, b = r["sentence1"], r["sentence2"]
        g = r["gold_label"]
        if g not in ("entailment", "neutral") or indexed.setdefault((a, b), (g, i))[0] != g:
            raise ValueError("invalid source annotation")
    pairs = []
    for (a, b), (label, line) in indexed.items():
        if a == b:
            raise ValueError("self comparison")
        if a > b or (b, a) not in indexed:
            continue
        reverse, other = indexed[b, a]
        if label == reverse:
            raise ValueError("expected exactly one gold direction")
        pairs.append((a, b, line, other, "forward" if label == "entailment" else "reverse"))
    return pairs, {
        "original_rows": len(rows),
        "duplicate_rows": len(rows) - len(indexed),
        "unpaired_directions": len(indexed) - 2 * len(pairs),
        "pairs": len(pairs),
    }


def infer(data, model, output):
    fetch_data(data, ALL_SOURCES)
    for p in ("config.json", "tokenizer.json", "onnx/model_quantized.onnx"):
        verify(model / p, FILES[p])
    config = json.loads((model / "config.json").read_bytes())["id2label"]
    if [config[str(i)].upper() for i in range(3)] != ["ENTAILMENT", "NEUTRAL", "CONTRADICTION"]:
        raise ValueError("unexpected label mapping")
    tok = Tokenizer.from_file(str(model / "tokenizer.json"))
    tok.no_padding()
    tok.enable_truncation(512)
    session = make_session(model / "onnx/model_quantized.onnx")
    evidence = LexicalEvidence(read_source(data, "pmonli"))

    def predict(a, b):
        (ans,) = session.run(None, feed([tok.encode(a, b)]))
        if ans.shape != (1, 3) or ans.dtype != np.float32 or not np.isfinite(ans).all():
            raise ValueError("invalid classifier output")
        return ans[0]

    output_rows = []
    for split in NEGATIVE:
        pairs, _ = reciprocal(read_source(data, split))
        for a, b, line, other, gold in pairs:
            pos_a, pos_b = affirmative(a), affirmative(b)
            n1, n2 = predict(a, b), predict(b, a)
            p1, p2 = predict(pos_a, pos_b), predict(pos_b, pos_a)
            orig, pos = choose_direction(n1, n2), choose_direction(p1, p2)

            def compare(left, right):
                assert (left, right) == (pos_a, pos_b)
                return pos

            result = decide_downward_pair(a, b, evidence, compare)
            ab, ba = changed_terms(a, b) or ("", "")
            output_rows.append(
                [
                    split,
                    line,
                    other,
                    sha256(a.encode()).hexdigest(),
                    sha256(b.encode()).hexdigest(),
                    ab,
                    ba,
                    gold,
                    *[f"{x:08x}" for vec in (n1, n2, p1, p2) for x in vec.view(np.uint32)],
                    orig,
                    opposite(orig),
                    pos,
                    opposite(pos),
                    result.direction,
                    " ".join(map(str, result.source_lines)),
                    result.basis,
                ]
            )
        print(f"{split} {len(pairs)} pairs", file=sys.stderr)
    with output.open("x", encoding="utf8", newline="") as stream:
        writer = csv.writer(stream, delimiter="\t", lineterminator="\n")
        writer.writerow(
            [
                "subset",
                "ab_line",
                "ba_line",
                "a_sha256",
                "b_sha256",
                "a_term",
                "b_term",
                "gold",
                *LOGIT_FIELDS,
                *METHODS,
                "positive_source_lines",
                "basis",
            ]
        )
        writer.writerows(output_rows)


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    for name in ("data", "model", "output"):
        p.add_argument(name, type=Path)
    a = p.parse_args()
    infer(a.data, a.model, a.output)
