"""Fetch and verify the original GoEmotions annotation shards, split files, and label map."""

import argparse
from base64 import b64encode
from concurrent.futures import ThreadPoolExecutor
from hashlib import md5, sha1
from pathlib import Path
from shutil import copyfileobj, which
import subprocess
from tempfile import NamedTemporaryFile
from urllib.request import urlopen

REVISION = "7951440944924ac61b6e2f9a2a3c715834005c40"
GIT = {
    "train.tsv": "aa00d732d3b9e969d9fcbaafc2c5b094555746c0",
    "dev.tsv": "38c793645ca3a2e946d625c9722ca5386b0a6c7f",
    "test.tsv": "7635db4a49befb91e5bc0dbedde095bb2d8593ae",
    "emotions.txt": "0d79bc030e766bc9dac1f4482bfbd864556c284a",
    "ekman_mapping.json": "dd13b0702f20993f0f4aed84fc87a124c7a783ba",
}
GCS = {
    "goemotions_1.csv": ("1593104334878780", "iANWj5ErJXYwqmI6/WM80A=="),
    "goemotions_2.csv": ("1593104334401872", "shblr+wi3xOYCfc38NGLZA=="),
    "goemotions_3.csv": ("1593104334999779", "t9lQh/eKVKeGCjXgJyBJ5Q=="),
}


def verify(path, name):
    data = path.read_bytes()
    if name in GIT:
        actual = sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()
        expected = GIT[name]
    else:
        actual = b64encode(md5(data).digest()).decode()
        expected = GCS[name][1]
    if actual != expected:
        raise ValueError(f"public version or digest mismatch for {name}")


def fetch(folder, name):
    dest = folder / name
    if dest.exists():
        verify(dest, name)
        return
    if name in GIT:
        url = f"https://raw.githubusercontent.com/google-research/google-research/{REVISION}/goemotions/data/{name}"
    else:
        url = f"https://storage.googleapis.com/gresearch/goemotions/data/full_dataset/{name}?generation={GCS[name][0]}"
    with NamedTemporaryFile(dir=folder, delete=False) as handle:
        tmp = Path(handle.name)
    try:
        try:
            with urlopen(url, timeout=30) as source, tmp.open("wb") as output:
                copyfileobj(source, output)
        except OSError:
            if name in GIT and which("gh"):
                with tmp.open("wb") as output:
                    subprocess.run(["gh", "api", "-H", "Accept: application/vnd.github.raw+json",
                                    "repos/google-research/google-research/git/blobs/" + GIT[name]],
                                   check=True, stdout=output)
            else:
                subprocess.run(["curl", "-fsSL", "--retry", "2", "--max-time", "100",
                                "--output", str(tmp), url], check=True)
        verify(tmp, name)
        tmp.replace(dest)
    finally:
        tmp.unlink(missing_ok=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("folder", type=Path)
    args = parser.parse_args()
    args.folder.mkdir(exist_ok=True, parents=True)
    with ThreadPoolExecutor(max_workers=4) as pool:
        for _ in pool.map(lambda name: fetch(args.folder, name), [*GIT, *GCS]):
            pass
    print("Verified three annotation shards, three original splits, vocabulary and mapping.")
