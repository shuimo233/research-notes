"""Fetch the pinned GoEmotions ONNX release and verify each file before use."""
import argparse
from hashlib import sha1, sha256
from pathlib import Path
import subprocess
from tempfile import NamedTemporaryFile

MODEL = "SamLowe/roberta-base-go_emotions-onnx"
REV = "90ee0c1c4796d370e68968687b8ba51fc11224f4"
FILES = {
    "config.json": "a9d71647a2250ff0d6e4e0d790054415231b4ebe",
    "tokenizer.json": "d535bff2abebc2741089c8d653ff4254a6bccc83",
    "onnx/model.onnx": "3bf605adfa0e59ae36723f1136d37865acb0ec4ded7831f7f7f5231eb032d60a",
    "onnx/model_quantized.onnx": "0c1981c5b479674747911c8e2228f0c4ec90bf47bf66e830f7d4fc62be082958",
}


def verify(path, expected):
    digest = sha256() if len(expected) == 64 else sha1(b"blob " + str(path.stat().st_size).encode() + b"\0")
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    if digest.hexdigest() != expected:
        raise ValueError(f"file digest mismatch for {path.name}")


def fetch(folder, name, host):
    target = folder / name
    if target.exists():
        verify(target, FILES[name])
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile(dir=target.parent, delete=False) as stream:
        tmp = Path(stream.name)
    try:
        url = f"{host.rstrip('/')}/{MODEL}/resolve/{REV}/{name}"
        subprocess.run(["curl", "-fsSL", "--retry", "2", "--connect-timeout", "12",
                        "--max-time", "600", "-o", str(tmp), url], check=True)
        verify(tmp, FILES[name])
        tmp.replace(target)
    finally:
        tmp.unlink(missing_ok=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("folder", type=Path)
    parser.add_argument("--host", default="https://huggingface.co")
    parser.add_argument("--file", choices=FILES)
    args = parser.parse_args()
    for name in ([args.file] if args.file else FILES):
        fetch(args.folder, name, args.host)
        print(f"verified {name}", flush=True)
