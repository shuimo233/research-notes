"""Run heterogeneous minimum widths in one Scan without mixing row semantics."""

import argparse
from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory


def export(original, output):
    import onnx
    from onnx import TensorProto, helper

    from go_scan_export import export as singleton_scan
    from rte_context_fetch import FILES

    with TemporaryDirectory(prefix="row-width-base-") as tmp:
        path = Path(tmp) / "singleton-scan.onnx"
        singleton_scan(
            original, path, FILES["onnx/model_quantized.onnx"], min_width=1, pad_token=0
        )
        model = onnx.load(path)
    graph = model.graph
    if len(graph.node) != 1 or graph.node[0].op_type != "Scan":
        raise ValueError("expected one checked singleton Scan")
    scan = graph.node[0]
    body = next(a.g for a in scan.attribute if a.name == "body")
    floor = next(x for x in body.initializer if x.name == "target_floor")
    if floor.data_type != TensorProto.INT64 or list(floor.dims) != [1]:
        raise ValueError("unexpected singleton floor tensor")
    # Make the already-verified padding floor a third Scan stream.
    body.initializer.remove(floor)
    body.input.append(
        helper.make_tensor_value_info("target_floor", TensorProto.INT64, [1])
    )
    graph.input.append(
        helper.make_tensor_value_info("min_widths", TensorProto.INT64, ["batch", 1])
    )
    scan.input.append("min_widths")
    next(a for a in scan.attribute if a.name == "num_scan_inputs").i = 3
    onnx.checker.check_model(model)
    contents = model.SerializeToString()
    with output.open("xb") as f:
        f.write(contents)
    return sha256(contents).hexdigest()


def _one_call(session, rows, floors, pad):
    import numpy as np

    from point_runtime import validate_feeds

    n = max(map(len, rows))
    ids = np.full((len(rows), n), pad, dtype=np.int64)
    mask = np.zeros_like(ids)
    for i, row in enumerate(rows):
        ids[i, : len(row)] = row
        mask[i, : len(row)] = 1
    floors = np.asarray(floors, dtype=np.int64).reshape(-1, 1)
    validate_feeds(ids, mask)
    (logits,) = session.run(
        ["logits"],
        {
            "input_ids": ids,
            "attention_mask": mask,
            "min_widths": floors,
        },
    )
    return logits


def routed_batch(session, rows, floors, *, bucketed=False, pad=0):
    """Run pretokenized rows under the declared per-row width policy."""
    import numpy as np

    if (
        not rows
        or len(rows) != len(floors)
        or any(not 0 < len(row) <= 512 for row in rows)
    ):
        raise ValueError(
            "expected one or more nonempty token sequences of at most 512 tokens"
        )
    if any(type(n) is not int or not 0 <= n <= 512 for n in floors) or pad != 0:
        raise ValueError(
            "expected integer floors in [0,512] and the declared pad token zero"
        )
    if not bucketed:
        return _one_call(session, rows, floors, pad)
    groups = {}
    for i, (row, w) in enumerate(zip(rows, floors, strict=True)):
        groups.setdefault(max(len(row), w), []).append(i)
    result = np.empty((len(rows), 3), dtype=np.float32)
    for group in groups.values():
        result[group] = _one_call(
            session, [rows[i] for i in group], [floors[i] for i in group], pad
        )
    return result


if __name__ == "__main__":
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("source", type=Path)
    cli.add_argument("output", type=Path)
    a = cli.parse_args()
    print(export(a.source, a.output))
