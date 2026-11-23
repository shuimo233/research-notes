"""Fetch locked source files for the RTE transfer, including two independent release formats."""
import argparse
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from go_model_fetch import fetch_verified

MODEL = "Xenova/distilbert-base-uncased-mnli"
REV = "fddd480db7392a87114a6813c6acb5ede13ff4ee"
DATA_REV = "bcdcba79d07bc864c1c254ccfcedcce55bcc9a8c"
FILES = {
    "config.json": "8c9d46fe6cf23ab39dd6fbad2e4d0640397c4faa",
    "tokenizer.json": "688882a79f44442ddc1f60d70334a7ff5df0fb47",
    "onnx/model_quantized.onnx": "5b7e374d8d1e44149fafa498efe80166f740914b3e53bcfa6115fb3ecaca0945",
    "RTE.zip": "6bf86de103ecd335f3441bd43574d23fef87ecc695977a63b82d5efb206556ee",
    "validation.parquet": "fb2aa2e04f551133ba663617a15ae133dc22b0f6a969bc0629b5ea6003ee9cf8",
}


def fetch(folder, host):
    for name, digest in FILES.items():
        if name == "RTE.zip":
            url = "https://dl.fbaipublicfiles.com/glue/data/RTE.zip"
        elif name == "validation.parquet":
            url = f"{host}/datasets/nyu-mll/glue/resolve/{DATA_REV}/rte/validation-00000-of-00001.parquet"
        else:
            url = f"{host}/{MODEL}/resolve/{REV}/{name}"
        fetch_verified(folder / name, url, digest)
        print(f"verified {name}", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("folder", type=Path)
    parser.add_argument("--host", default="https://huggingface.co")
    args = parser.parse_args()
    fetch(args.folder, args.host.rstrip("/"))
