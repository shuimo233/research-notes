"""End-to-end replication on verified local source caches. Never overwrite a previous run."""
import argparse
from hashlib import sha256
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parent
RTE_HASH = "5b7e374d8d1e44149fafa498efe80166f740914b3e53bcfa6115fb3ecaca0945"


def main(go_data, go_model, rte_data, output):
    output.mkdir(parents=True, exist_ok=False)
    def run(file, *args, capture=False):
        cmd = [sys.executable, "-I", "-B", str(ROOT / file), *map(str, args)]
        print(file, *(str(a) for a in args), flush=True)
        if capture:
            return json.loads(subprocess.check_output(cmd))
        subprocess.run(cmd, check=True)
    def report(name, content):
        (output / name).write_text(json.dumps(content, ensure_ascii=False, indent=2) + "\n", encoding="utf8")

    go_point, rte_point = output/"go-point.onnx", output/"rte-point.onnx"
    run("go_scan_export.py", go_model/"onnx/model_quantized.onnx", go_point)
    run("go_scan_export.py", rte_data/"onnx/model_quantized.onnx", rte_point, "--sha256", RTE_HASH)
    for mode in ("single", "padded", "repeat", "mixed"):
        run("go_context_run.py", go_data, go_model, mode, output/f"context-{mode}.npz")
    for name in ("original", "shuffled"):
        args = ("--shuffled",) if name == "shuffled" else ()
        run("go_context_run.py", go_data, go_model, "scan", output/f"context-scan-{name}.npz", "--wrapped", go_point, *args)
    archive = output/"go-point-decisions.tsv"
    report("go-point-logit-checks.json", run("go_context_archive.py", go_data, go_model, output,
           ROOT/"go-model-batch.tsv", ROOT/"go-layout-changes.tsv", archive, capture=True))
    nli = output/"rte-point-logits.tsv"
    report("rte-source-check.json", run("rte_context_run.py", rte_data, rte_point, nli, capture=True))
    report("point-results.json", run("point_results.py", archive, ROOT/"go-model-batch.tsv", go_data, nli, capture=True))
    report("point-checks.json", run("point_check.py", output, go_data, go_model/"onnx/model_quantized.onnx",
           go_point, rte_data/"onnx/model_quantized.onnx", rte_point, capture=True))
    report("point-reinference.json", run("point_reinfer.py", output, go_data, go_model, rte_data, rte_point, capture=True))
    report("go-point-timing.json", run("go_context_time.py", go_data, go_model, go_point, capture=True))
    agreement = {}
    for name in ("go-point-decisions.tsv", "rte-point-logits.tsv", "go-point-logit-checks.json",
                 "point-results.json", "point-checks.json", "point-reinference.json"):
        left, right = (base/name for base in (output, ROOT))
        if name.endswith(".json"):
            agreement[name] = json.loads(left.read_bytes()) == json.loads(right.read_bytes())
        else:
            agreement[name] = left.read_bytes().replace(b"\r\n", b"\n") == right.read_bytes().replace(b"\r\n", b"\n")
    agreement["fresh_graph_hashes"] = {name: sha256(path.read_bytes()).hexdigest() for name, path in
                                       (("go", go_point), ("rte", rte_point))}
    report("verification.json", agreement)
    print(json.dumps(agreement, indent=2))
    return all(v is True for k, v in agreement.items() if k != "fresh_graph_hashes")


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    for name in ("go_data", "go_model", "rte_data", "output"):
        p.add_argument(name, type=Path)
    a = p.parse_args()
    sys.exit(0 if main(*(path.resolve() for path in (a.go_data, a.go_model, a.rte_data, a.output))) else 1)
