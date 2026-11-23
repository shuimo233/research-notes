"""Independently verify saved ONNX graph structure, input checks, RTE results, and all decision paths."""
import argparse
import csv
from hashlib import sha256
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory

import numpy as np
import onnx
from onnx import TensorProto as T, helper as h

sys.path.insert(0, str(Path(__file__).resolve().parent))
from go_scan_export import export
from point_runtime import batch_logits, make_session, validate_feeds


def graph_match(source, point):
    a, b = (onnx.load(p) for p in (source, point))
    assert len(b.graph.node) == 1 and b.graph.node[0].op_type == "Scan"
    scan = b.graph.node[0]
    attrs = {v.name: v for v in scan.attribute}
    assert set(attrs) == {"body", "num_scan_inputs"} and attrs["num_scan_inputs"].i == 2
    body = attrs["body"].g
    assert len(body.node) == len(a.graph.node) + 6
    assert [n.op_type for n in body.node[:5]] == ["ReduceSum", "Slice", "Unsqueeze", "Slice", "Unsqueeze"]
    assert body.node[-1].op_type == "Squeeze"
    restored = {"point_ids":"input_ids", "point_mask":"attention_mask", "point_logits":"logits"}
    for original, candidate in zip(a.graph.node, body.node[5:-1]):
        for seq in (candidate.input, candidate.output):
            for j, name in enumerate(seq):
                seq[j] = restored.get(name, name)
        assert candidate.SerializeToString() == original.SerializeToString()
    assert len(body.initializer) == len(a.graph.initializer) + 1
    assert all(lhs.SerializeToString() == rhs.SerializeToString() for lhs, rhs in zip(a.graph.initializer, body.initializer))
    return {"original_nodes_recovered": len(a.graph.node), "identical_initializers": len(a.graph.initializer),
            "dynamic_quantizers": sum(n.op_type == "DynamicQuantizeLinear" for n in a.graph.node),
            "export_sha256": sha256(point.read_bytes()).hexdigest()}


def fixtures(tmp):
    count = 0
    for op in (11, 12, 13, 18):
        info = h.make_tensor_value_info
        source, point = (tmp / f"{prefix}-{op}.onnx" for prefix in ("original", "wrapped"))
        init = [h.make_tensor("reduce_axis", T.INT64, [1], [1])] if op >= 13 else []
        reduction = h.make_node("ReduceSum", ["input_ids", "reduce_axis"] if init else ["input_ids"],
                                ["int_score"], keepdims=1, **({} if init else {"axes": [1]}))
        graph = h.make_graph([reduction, h.make_node("Cast", ["int_score"], ["logits"], to=T.FLOAT)], "dummy",
                             [info(v, T.INT64, ["b","s"]) for v in ("input_ids","attention_mask")],
                             [info("logits", T.FLOAT, ["b",1])], init)
        m = h.make_model(graph, opset_imports=[h.make_opsetid("", op)])
        m.ir_version = 8
        onnx.save(m, source)
        export(source, point, sha256(source.read_bytes()).hexdigest())
        runtime = make_session(point, 1)
        ids = np.array([[2,3,50],[7,8,9]], dtype=np.int64)
        mask = np.array([[1,1,0],[1,1,1]], dtype=np.int64)
        np.testing.assert_array_equal(batch_logits(runtime, ids, mask), [[5.],[24.]])
        for bad in ([[0,1,1],[1,1,1]], [[1,0,1],[1,1,1]], [[0,0,0],[1,1,1]], [[1,1,2],[1,1,1]]):
            try:
                validate_feeds(ids, np.array(bad, dtype=np.int64))
            except ValueError:
                count += 1
            else:
                raise AssertionError("invalid input mask accepted")
    return {"opset_fixtures": 4, "rejected_invalid_masks": count}


def decisions(path, scores, rte_path, go_data):
    with path.open(encoding="utf8", newline="") as f:
        rows = list(csv.DictReader(f, delimiter="\t"))
    assert len(rows) == scores["go"]["items"]
    vocabulary = (go_data / "emotions.txt").read_text(encoding="utf8").splitlines()
    groups = json.loads((go_data / "ekman_mapping.json").read_bytes())
    groups["neutral"] = ["neutral"]
    group_masks = [sum(1 << vocabulary.index(w) for w in words) for words in groups.values()]
    for category in ("fine", "coarse", "top1"):
        def decision(row, mode):
            if category == "top1":
                return int(row[mode + "_top"])
            num = int(row[mode + "_mask"])
            if category == "coarse":
                return tuple(bool(num & m) for m in group_masks)
            return num
        cols = [[decision(r, name) for r in rows] for name in ("single", "padded", "repeat", "mixed", "scan-original", "scan-shuffled")]
        outcome = scores["go"]["counts"][category]["changed_items"]
        for i,j,tag in [(0,1,"S_to_P"),(1,2,"P_to_R"),(2,3,"R_to_M"),(0,3,"S_to_M"),(0,4,"scan_original"),(0,5,"scan_shuffled")]:
            assert sum(x != y for x, y in zip(cols[i], cols[j])) == outcome[tag]
        assert sum(len(set(t)) > 1 and t[0] == t[-1] for t in zip(*cols[:4])) == outcome["changed_then_restored"]
    with rte_path.open(encoding="utf8", newline="") as f:
        rte = list(csv.DictReader(f, delimiter="\t"))
    assert len(rte) == scores["rte"]["items"]
    pred, integer = {}, {}
    for mode, target in scores["rte"]["outcomes"].items():
        bits = np.asarray([[int(row[f"{mode}_{label}"], 16) for label in "ENC"] for row in rte], dtype=np.uint32)
        integer[mode] = bits
        pred[mode] = np.argmax(bits.view(np.float32), axis=1)
        actual = np.asarray([r["reference"] == "entailment" for r in rte], dtype=bool)
        assert int(np.sum((pred[mode] == 0) == actual)) == target["binary_correct"]
    for mode, target in scores["rte"]["outcomes"].items():
        assert int(np.count_nonzero(integer[mode] != integer["single"])) == target["unequal_float32"]
        assert int(np.count_nonzero(pred[mode] != pred["single"])) == target["three_class_changes"]
        assert int(np.count_nonzero((pred[mode] == 0) != (pred["single"] == 0))) == target["binary_changes"]
    return {"go_decision_rows": len(rows), "rte_raw_score_rows": len(rte)}


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    for name in ("articles", "go_data", "go_model", "go_wrapped", "rte_model", "rte_wrapped"):
        p.add_argument(name, type=Path)
    a = p.parse_args()
    with TemporaryDirectory() as temp:
        result = fixtures(Path(temp))
    result["go"] = graph_match(a.go_model, a.go_wrapped)
    result["rte"] = graph_match(a.rte_model, a.rte_wrapped)
    result.update(decisions(a.articles/"go-point-decisions.tsv", json.loads((a.articles/"point-results.json").read_bytes()),
                            a.articles/"rte-point-logits.tsv", a.go_data))
    print(json.dumps(result, indent=2))
