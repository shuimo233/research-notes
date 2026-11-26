"""Fetch pinned crates and extract independent version alternatives from Cargo locks."""

from argparse import ArgumentParser
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from hashlib import sha256
import json
from pathlib import Path
import tarfile
import tomllib

from weighted_bench import fetch

APPLICATIONS = {
    "ripgrep": ("13.0.0", "14.1.0", "14.1.1"),
    "fd-find": ("10.0.0", "10.1.0", "10.2.0"),
    "bat": ("0.23.0", "0.24.0", "0.25.0"),
    "just": ("1.38.0", "1.39.0", "1.40.0"),
}
REGISTRY = "registry+https://github.com/rust-lang/crates.io-index"


def index_path(name):
    if len(name) < 3:
        return f"{len(name)}/{name}"
    if len(name) == 3:
        return f"3/{name[0]}/{name}"
    return f"{name[:2]}/{name[2:4]}/{name}"


def fetch_crate(root, name, version, expected=None):
    if expected is None:
        assert name.isascii() and all(c.isalnum() or c in "-_" for c in name)
        index = f"https://index.crates.io/{index_path(name)}"
        local = root / f"{name}.index"
        if not local.exists():
            fetch(index, local)
        item = next(
            json.loads(line)
            for line in local.read_bytes().splitlines()
            if json.loads(line)["vers"] == version
        )
        assert item["name"] == name
        expected = item["cksum"]
    assert len(expected) == 64 and all(c in "0123456789abcdef" for c in expected)
    assert all(c.isascii() and (c.isalnum() or c in ".+-_") for c in name + version)
    location = f"{name}-{version}.crate"
    path = root / location
    url = f"https://static.crates.io/crates/{name}/{location}"
    if not path.is_file() or sha256(path.read_bytes()).hexdigest() != expected:
        fetch(url, path)
    assert sha256(path.read_bytes()).hexdigest() == expected
    return {
        "name": name,
        "version": version,
        "file": location,
        "url": url,
        "sha256": expected,
        "bytes": path.stat().st_size,
    }


def catalog(path, prefix):
    with tarfile.open(path, mode="r:gz") as source:
        members = [
            item
            for item in source.getmembers()
            if item.isfile() and item.name == prefix + "/Cargo.lock"
        ]
        if len(members) != 1:
            raise ValueError("expected one Cargo.lock in " + path.name)
        with source.extractfile(members[0]) as r:
            lock = tomllib.loads(r.read().decode())
    by_name = defaultdict(list)
    for crate in lock["package"]:
        if crate.get("source") == REGISTRY and crate.get("checksum"):
            by_name[crate["name"]].append(
                {"version": crate["version"], "sha256": crate["checksum"]}
            )
    return by_name


def shortlist(parts):
    names = sorted(set.intersection(*(set(p) for p in parts)))
    variants = {}
    for name in names:
        if any(len(p[name]) != 1 for p in parts):
            continue
        *prev, lead = (p[name][0] for p in parts)
        older = {
            p["version"]: p["sha256"] for p in prev if p["version"] != lead["version"]
        }
        if older:
            variants[name] = [
                *({"version": v, "sha256": sha} for v, sha in sorted(older.items())),
                lead,
            ]
        if len(variants) == 8:
            break
    return variants


def run(root):
    root.mkdir(parents=True, exist_ok=True)
    result = {}
    for name, versions in APPLICATIONS.items():
        anchors = []
        try:
            anchors = [fetch_crate(root, name, v) for v in versions]
            choices = shortlist(
                [
                    catalog(root / a["file"], a["name"] + "-" + a["version"])
                    for a in anchors
                ]
            )
        except (OSError, ValueError, StopIteration) as exc:
            result[name] = {
                "unavailable": str(exc),
                "versions": versions,
                "anchors": anchors,
            }
        else:
            result[name] = {"anchors": anchors, "choices": choices}
        print(name, sorted(result[name].get("choices", {})), flush=True)
    keys = {
        (name, p["version"], p["sha256"])
        for row in result.values()
        for name, v in row.get("choices", {}).items()
        for p in v
    }
    with ThreadPoolExecutor(max_workers=8) as pool:
        downloads = list(pool.map(lambda p: fetch_crate(root, *p), sorted(keys)))
    return {"applications": result, "dependencies": downloads}


if __name__ == "__main__":
    p = ArgumentParser(description=__doc__)
    p.add_argument("cache", type=Path)
    p.add_argument("output", type=Path)
    a = p.parse_args()
    result = run(a.cache)
    a.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
