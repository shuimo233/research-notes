"""Export the pinned INT8 classifier as a batch of right-unpadded singleton evaluations.

The graph accepts nonempty batches with nonempty, binary, right-padded prefix
masks. Use point_runtime.batch_logits to validate the runtime input contract.
"""
import argparse
from hashlib import sha256
from pathlib import Path
import sys
import onnx
from onnx import helper as h, TensorProto as T

sys.path.insert(0, str(Path(__file__).resolve().parent))
from go_model_fetch import FILES, verify


def export(original, output, digest=FILES["onnx/model_quantized.onnx"], min_width=0, pad_token=0):
    if type(min_width) is not int or min_width < 0 or type(pad_token) is not int or pad_token < 0:
        raise ValueError("expected a nonnegative integer width and padding token")
    verify(original, digest)
    if output.exists():
        raise FileExistsError(output)
    model = onnx.load(original)
    opset = {o.domain: o.version for o in model.opset_import}.get("")
    if opset is None or not 11 <= opset <= 18:
        raise ValueError("this exporter supports standard opsets 11 through 18")
    graph = model.graph
    if [x.name for x in graph.input] != ["input_ids", "attention_mask"] or [x.name for x in graph.output] != ["logits"]:
        raise ValueError("unexpected graph signature")
    for value in graph.input:
        t = value.type.tensor_type
        if t.elem_type != T.INT64 or len(t.shape.dim) != 2 or t.shape.dim[1].HasField("dim_value"):
            raise ValueError("need rank-two int64 inputs with a variable sequence dimension")
    t = graph.output[0].type.tensor_type
    if t.elem_type != T.FLOAT or len(t.shape.dim) != 2 or t.shape.dim[1].dim_value < 1:
        raise ValueError("need rank-two float logits with fixed class count")
    labels = t.shape.dim[1].dim_value
    names = {s for node in graph.node for s in [*node.input, *node.output]}
    names.update(init.name for init in graph.initializer)
    reserved = {"point_ids", "point_mask", "point_logits", "row_ids", "row_mask", "point_end",
                "point_zero", "row_result", "trim_ids", "trim_mask"}
    if min_width:
        reserved.update(("target_floor", "token_pad", "under_floor", "point_width", "extra_width",
                         "right_pads", "padded_ids", "padded_mask"))
    if names & reserved or len(graph.sparse_initializer) or any(
            attr.type in (onnx.AttributeProto.GRAPH, onnx.AttributeProto.GRAPHS)
            for node in graph.node for attr in node.attribute):
        raise ValueError("unsupported captured name, sparse initializer or nested subgraph")
    renamed = {"input_ids": "point_ids", "attention_mask": "point_mask", "logits": "point_logits"}
    for n in graph.node:
        for seq in (n.input, n.output):
            for i, name in enumerate(seq):
                if name in renamed:
                    seq[i] = renamed[name]
    def axis0(op, src, dst, **attrs):
        if opset >= 13:
            return h.make_node(op, [src, "point_zero"], [dst], **attrs)
        return h.make_node(op, [src], [dst], axes=[0], **attrs)

    prep = [axis0("ReduceSum", "row_mask", "point_end", keepdims=1)]
    constants = [h.make_tensor("point_zero", T.INT64, [1], [0])]
    if min_width:
        constants.extend((h.make_tensor("target_floor", T.INT64, [1], [min_width]),
                          h.make_tensor("token_pad", T.INT64, [], [pad_token])))
        prep.extend((h.make_node("Less", ["point_end", "target_floor"], ["under_floor"]),
                     h.make_node("Where", ["under_floor", "target_floor", "point_end"], ["point_width"]),
                     h.make_node("Sub", ["point_width", "point_end"], ["extra_width"]),
                     h.make_node("Concat", ["point_zero", "extra_width"], ["right_pads"], axis=0)))
    for row, cropped, dst in (("row_ids", "trim_ids", "point_ids"), ("row_mask", "trim_mask", "point_mask")):
        prep.append(h.make_node("Slice", [row, "point_zero", "point_end"], [cropped]))
        if min_width:
            padded = "padded_ids" if row == "row_ids" else "padded_mask"
            args = [cropped, "right_pads"] + (["token_pad"] if row == "row_ids" else [])
            prep.append(h.make_node("Pad", args, [padded], mode="constant"))
            cropped = padded
        prep.append(axis0("Unsqueeze", cropped, dst))
    strip = axis0("Squeeze", "point_logits", "row_result")
    info = h.make_tensor_value_info
    body = h.make_graph([*prep, *graph.node, strip], "single_unpadded_example",
                        [info("row_ids", T.INT64, ["width"]), info("row_mask", T.INT64, ["width"])],
                        [info("row_result", T.FLOAT, [labels])],
                        [*graph.initializer, *constants])
    scan = h.make_node("Scan", ["input_ids", "attention_mask"], ["logits"], body=body, num_scan_inputs=2)
    outer = h.make_graph([scan], "independent_examples",
                         [info("input_ids", T.INT64, ["batch", "width"]),
                          info("attention_mask", T.INT64, ["batch", "width"])],
                         [info("logits", T.FLOAT, ["batch", labels])])
    model.graph.CopyFrom(outer)
    onnx.checker.check_model(model)
    data = model.SerializeToString()
    with output.open("xb") as f:
        f.write(data)
    return sha256(data).hexdigest()


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("original", type=Path)
    p.add_argument("output", type=Path)
    p.add_argument("--sha256", default=FILES["onnx/model_quantized.onnx"], help="expected source SHA-256")
    p.add_argument("--min-width", type=int, default=0, help="pad each cropped row to at least this width")
    p.add_argument("--pad-token", type=int, default=0, help="right-padding token ID for the optional width floor")
    a = p.parse_args()
    print(export(a.original, a.output, a.sha256, a.min_width, a.pad_token))
