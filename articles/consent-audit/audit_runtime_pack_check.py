"""Check that the mixed-width wrapper preserves every source model operation."""

import argparse
from hashlib import sha256
import json
from pathlib import Path

import onnx


def inspect(source, derived):
    original, packed = (onnx.load(p) for p in (source, derived))
    onnx.checker.check_model(packed)
    graph = packed.graph
    assert len(graph.node) == 1 and graph.node[0].op_type == "Scan"
    scan = graph.node[0]
    attrs = {a.name: a for a in scan.attribute}
    assert set(attrs) == {"body", "num_scan_inputs"} and attrs["num_scan_inputs"].i == 3
    assert list(scan.input) == ["input_ids", "attention_mask", "min_widths"]
    assert [x.name for x in graph.input] == list(scan.input)
    shape = graph.input[-1].type.tensor_type
    assert shape.elem_type == onnx.TensorProto.INT64
    assert [d.dim_param or d.dim_value for d in shape.shape.dim] == ["batch", 1]
    body = attrs["body"].g
    assert [x.name for x in body.input] == ["row_ids", "row_mask", "target_floor"]
    assert [n.op_type for n in body.node[:11]] == [
        "ReduceSum",
        "Less",
        "Where",
        "Sub",
        "Concat",
        "Slice",
        "Pad",
        "Unsqueeze",
        "Slice",
        "Pad",
        "Unsqueeze",
    ]
    assert list(body.node[1].input) == ["point_end", "target_floor"]
    assert list(body.node[2].input) == ["under_floor", "target_floor", "point_end"]
    assert body.node[-1].op_type == "Squeeze"
    names = {
        "point_ids": "input_ids",
        "point_mask": "attention_mask",
        "point_logits": "logits",
    }
    for prior, new in zip(original.graph.node, body.node[11:-1], strict=True):
        for sequence in (new.input, new.output):
            for i, key in enumerate(sequence):
                sequence[i] = names.get(key, key)
        assert prior.SerializeToString() == new.SerializeToString()
    parameters = list(body.initializer)
    assert [p.name for p in parameters[-2:]] == ["point_zero", "token_pad"]
    for prior, new in zip(original.graph.initializer, parameters[:-2], strict=True):
        assert prior.SerializeToString() == new.SerializeToString()
    assert [x.name for x in body.output] == ["row_result"]
    return {
        "source_operators": len(original.graph.node),
        "source_parameters": len(original.graph.initializer),
        "scan_inputs": len(scan.input),
        "graph_sha256": sha256(derived.read_bytes()).hexdigest(),
    }


if __name__ == "__main__":
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("source", type=Path)
    cli.add_argument("derived", type=Path)
    a = cli.parse_args()
    print(json.dumps(inspect(a.source, a.derived)))
