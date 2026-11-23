"""Second inference path: HF tokenizers' batch padding, independent Parquet import and archived decisions."""
import argparse
import csv
from hashlib import sha256
from itertools import batched
import json
from pathlib import Path
import sys

import duckdb
import numpy as np
from tokenizers import Tokenizer

sys.path.insert(0, str(Path(__file__).resolve().parent))
from point_runtime import make_session
from go_model_fetch import verify, FILES as GO
from rte_context_fetch import FILES as RTE


def feed(encodings):
    return {"input_ids": np.stack([e.ids for e in encodings]).astype(np.int64),
            "attention_mask": np.stack([e.attention_mask for e in encodings]).astype(np.int64)}


def rte(root, folder, point):
    verify(folder/"validation.parquet", RTE["validation.parquet"])
    verify(folder/"onnx/model_quantized.onnx", RTE["onnx/model_quantized.onnx"])
    with (root/"rte-point-logits.tsv").open() as f:
        saved = {r["id"]: r for r in csv.DictReader(f, delimiter="\t")}
    with duckdb.connect(":memory:") as db:
        rows = db.execute("SELECT idx,sentence1,sentence2 FROM read_parquet(?) ORDER BY idx",
                          [str(folder/"validation.parquet")]).fetchall()
    tok = Tokenizer.from_file(str(folder/"tokenizer.json"))
    tok.enable_truncation(512)
    tok.enable_padding(pad_id=tok.token_to_id("[PAD]"), pad_token="[PAD]")
    src, converted = make_session(folder/"onnx/model_quantized.onnx"), make_session(point)
    checked = 0
    for mode in ("single","mixed","scan","reordered"):
        items = sorted(rows,key=lambda r: sha256(str(r[0]).encode()).digest()) if mode=="reordered" else rows
        for group in batched(items, 1 if mode=="single" else 8):
            batch = tok.encode_batch([(p,h) for _,p,h in group])
            scores, = (src if mode in ("single","mixed") else converted).run(None, feed(batch))
            for row, v in zip(group, scores):
                bits = [f"{x:08x}" for x in v.view(np.uint32)]
                assert bits == [saved[str(row[0])][mode+"_"+k] for k in "ENC"]
                checked += len(bits)
    return checked


def go(root, data, model):
    verify(model/"onnx/model_quantized.onnx", GO["onnx/model_quantized.onnx"])
    with (data/"test.tsv").open(encoding="utf8",newline="") as f:
        groups = list(batched(csv.reader(f,delimiter="\t",quoting=csv.QUOTE_NONE), 8))
    # 16 deterministic ordinary groups and the short final group.
    selection = sorted(groups[:-1],key=lambda g: sha256(g[-1][2].encode()).digest())[:16] + [groups[-1]]
    with (root/"go-point-decisions.tsv").open(encoding="utf8", newline="") as f:
        saved = {r["id"]:r for r in csv.DictReader(f,delimiter="\t")}
    tok = Tokenizer.from_file(str(model/"tokenizer.json"))
    tok.enable_truncation(128)
    sess = make_session(model/"onnx/model_quantized.onnx")
    count = 0
    for group in selection:
        tok.enable_padding(pad_id=tok.token_to_id("<pad>"),pad_token="<pad>")
        mixed, = sess.run(None,feed(tok.encode_batch([r[0] for r in group])))
        width = len(tok.encode_batch([r[0] for r in group])[0].ids)
        for j,(text,_,key) in enumerate(group):
            tok.no_padding()
            one, = sess.run(None,feed([tok.encode(text)]))
            tok.enable_padding(length=width,pad_id=tok.token_to_id("<pad>"),pad_token="<pad>")
            padded, = sess.run(None,feed(tok.encode_batch([text])))
            clones, = sess.run(None,feed(tok.encode_batch([text]*len(group))))
            for name,v in (("single",one[0]),("padded",padded[0]),("repeat",clones[j]),("mixed",mixed[j])):
                bits=sum(1<<i for i,value in enumerate(v) if value>=0)
                assert bits==int(saved[key][name+"_mask"]) and int(np.argmax(v))==int(saved[key][name+"_top"])
                count+=1
    return count


if __name__ == "__main__":
    p=argparse.ArgumentParser(description=__doc__)
    for field in ("articles","go_data","go_model","rte_data","rte_wrapped"):
        p.add_argument(field,type=Path)
    a=p.parse_args()
    print(json.dumps({"go_mode_sample_checks":go(a.articles,a.go_data,a.go_model),
                      "rte_float32_cells_recomputed":rte(a.articles,a.rte_data,a.rte_wrapped)},indent=2))
