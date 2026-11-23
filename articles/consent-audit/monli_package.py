"""Pack traced positive evidence for a fixed budget, or run one licensed downward pair."""

import argparse
import csv
from dataclasses import asdict
import json
from pathlib import Path
import re
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from go_model_fetch import verify
from monli_direction_score import choose_direction
from monli_scope import WORD, LexicalEvidence, decide_downward_pair

POSITIVE_BLOB = "c8696b058de83a2edb5cc9daf496ab779637ecd5"


def package(source, lines):
    verify(source, POSITIVE_BLOB)
    if len(set(lines)) != len(lines):
        raise ValueError("duplicate source line")
    graph = LexicalEvidence(json.loads(t) for t in source.read_bytes().splitlines())
    ids = {line: (a, b) for a, adj in graph.edges.items() for b, line in adj.items()}
    if not set(lines) <= ids.keys():
        raise ValueError("unknown canonical evidence edge")
    return {"positive_git_blob": POSITIVE_BLOB, "edges": [[i, *ids[i]] for i in sorted(lines)]}


def load_package(obj):
    if obj["positive_git_blob"] != POSITIVE_BLOB:
        raise ValueError("unknown evidence source")
    graph = LexicalEvidence(())
    seen = set()
    for line, a, b in obj["edges"]:
        if (
            type(line) is not int
            or line < 1
            or line in seen
            or a == b
            or not all(re.fullmatch(WORD, w) for w in (a, b))
        ):
            raise ValueError("invalid edge record")
        seen.add(line)
        adj = graph.edges.setdefault(a, {})
        adj[b] = min(adj.get(b, line), line)
    return graph


def for_budget(source, frontier, budget):
    with frontier.open(encoding="utf8", newline="") as f:
        for r in csv.DictReader(f, delimiter="\t"):
            if int(r["source_edges"]) == budget:
                lines = list(map(int, r["pmonli_source_lines"].split()))
                if len(lines) != budget:
                    raise ValueError("wrong edge count")
                return package(source, lines)
    raise ValueError("budget absent from frontier")


class FrozenComparator:
    def __init__(self, model):
        import numpy as np
        from tokenizers import Tokenizer
        from point_runtime import make_session
        from rte_context_fetch import FILES

        for p in ("config.json", "tokenizer.json", "onnx/model_quantized.onnx"):
            verify(model / p, FILES[p])
        labels = json.loads((model / "config.json").read_bytes())["id2label"]
        if [labels[str(i)].upper() for i in range(3)] != ["ENTAILMENT", "NEUTRAL", "CONTRADICTION"]:
            raise ValueError("unexpected labels")
        self.np = np
        self.tok = Tokenizer.from_file(str(model / "tokenizer.json"))
        self.tok.no_padding()
        self.tok.enable_truncation(512)
        self.session = make_session(model / "onnx/model_quantized.onnx")
        self.calls = 0

    def __call__(self, a, b):
        columns = []
        for left, right in ((a, b), (b, a)):
            e = self.tok.encode(left, right)
            feed = {
                name: self.np.array([x], dtype=self.np.int64)
                for name, x in (("input_ids", e.ids), ("attention_mask", e.attention_mask))
            }
            (values,) = self.session.run(None, feed)
            self.calls += 1
            columns.append(values[0])
        return choose_direction(*columns)


def predict_one(left, right, graph, model):
    comparator = None

    def compare(x, y):
        nonlocal comparator
        if comparator is None:
            comparator = FrozenComparator(model)
        return comparator(x, y)

    answer = decide_downward_pair(left, right, graph, compare)
    return {**asdict(answer), "model_forward_calls": comparator.calls if comparator else 0}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    cmds = parser.add_subparsers(dest="command", required=True)
    build = cmds.add_parser("build")
    build.add_argument("positive", type=Path)
    build.add_argument("frontier", type=Path)
    build.add_argument("budget", type=int)
    build.add_argument("output", type=Path)
    run = cmds.add_parser("predict")
    run.add_argument("package", type=Path)
    run.add_argument("model", type=Path)
    run.add_argument("left")
    run.add_argument("right")
    a = parser.parse_args()
    if a.command == "build":
        payload = for_budget(a.positive, a.frontier, a.budget)
        with a.output.open("x", encoding="utf8", newline="\n") as f:
            f.write(json.dumps(payload, indent=2) + "\n")
    else:
        graph = load_package(json.loads(a.package.read_bytes()))
        print(json.dumps(predict_one(a.left, a.right, graph, a.model), indent=2))
