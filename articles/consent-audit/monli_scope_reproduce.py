"""One-command replay of the source-backed scope study, package frontier and deployed endpoints."""

import argparse
from hashlib import sha256
import json
from pathlib import Path
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from go_model_fetch import fetch_verified, verify
from monli_package import for_budget
from monli_package_replay import replay
from monli_preserver import compute
from monli_preserver_check import check
from monli_scope_baselines import WORDNET_BLOB, compare
from monli_scope_check import audit
from monli_scope_run import infer
from monli_scope_score import assess
from monli_withdrawal import WithdrawalAudit, inputs as withdrawal_inputs, report as withdrawal_report
from monli_withdrawal_check import check as check_withdrawals
from rte_context_fetch import FILES, MODEL, REV


def run(data, model, output, wordnet, host):
    output.mkdir(parents=True, exist_ok=False)
    root = Path(__file__).resolve().parent
    for n in ("config.json", "tokenizer.json", "onnx/model_quantized.onnx"):
        fetch_verified(model / n, f"{host}/{MODEL}/resolve/{REV}/{n}", FILES[n])
    if wordnet is None:
        wordnet = data / "wordnet-3.0-nltk.zip"
        url = "https://raw.githubusercontent.com/nltk/nltk_data/96f9b3252457a2b97e52aec64c3dfceeb5c312d5/packages/corpora/wordnet.zip"
        try:
            fetch_verified(wordnet, url, WORDNET_BLOB)
        except subprocess.CalledProcessError:
            mirror_revision = "42e237f9666c9b593e28b325eb22a52a42c2a48c"
            mirror = f"{host}/datasets/Deepanshu7284/nltk_data_bundle/resolve/{mirror_revision}/corpora/wordnet.zip"
            fetch_verified(wordnet, mirror, WORDNET_BLOB)
    verify(wordnet, WORDNET_BLOB)
    ledger = output / "monli-scope-ledger.tsv"
    frontier = output / "monli-preserver-frontier.tsv"
    pos = data / "pmonli.jsonl"
    infer(data, model, ledger)
    results = {
        "monli-scope-scores.json": assess(ledger),
        "monli-scope-checks.json": audit(
            data, model, output / "scope-scan.onnx", ledger, root / "monli-direction-logits.tsv"
        ),
        "monli-scope-baselines.json": compare(ledger, wordnet),
        "monli-preserver-results.json": compute(pos, ledger, frontier),
        "monli-preserver-checks.json": check(pos, ledger, frontier),
        "monli-package-23.json": for_budget(pos, frontier, 23),
    }
    example = output / "monli-package-23.json"
    example.write_bytes(json.dumps(results[example.name]).encode())
    results["monli-package-replay.json"] = replay(data, model, ledger, frontier, example)
    positive, queries = withdrawal_inputs(pos, ledger)
    results["monli-package-29.json"] = WithdrawalAudit(positive, queries).pack(None)
    results["monli-withdrawal-results.json"] = withdrawal_report(pos, ledger)
    results["monli-withdrawal-checks.json"] = check_withdrawals(pos, ledger)
    match = {}
    for name, obj in results.items():
        (output / name).write_bytes((json.dumps(obj, indent=2) + "\n").encode())
        match[name] = json.loads((output / name).read_bytes()) == json.loads(
            (root / name).read_bytes()
        )
    for path in (ledger, frontier):
        match[path.name] = path.read_bytes().replace(b"\r\n", b"\n") == (
            root / path.name
        ).read_bytes().replace(b"\r\n", b"\n")
    if not all(match.values()):
        raise ValueError(f"replay differs from release: {match}")
    return {
        "published_artifacts_matched": match,
        "derived_onnx_sha256": sha256((output / "scope-scan.onnx").read_bytes()).hexdigest(),
    }


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    for n in ("data", "model", "new_output"):
        p.add_argument(n, type=Path)
    p.add_argument("--wordnet-zip", type=Path)
    p.add_argument("--host", default="https://huggingface.co")
    a = p.parse_args()
    print(json.dumps(run(a.data, a.model, a.new_output, a.wordnet_zip, a.host.rstrip("/")), indent=2))
