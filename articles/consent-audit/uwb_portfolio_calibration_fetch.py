"""Get unused UWB locations, after committing the selected rosters."""

import argparse
import gzip
from hashlib import sha256
import json
from pathlib import Path
from zipfile import ZipFile

from uwb_heldout_calibration_fetch import (
    ARCHIVE_BYTES,
    PILOT,
    URL,
    RemoteArchive,
    choose,
    merged_ranges,
    read_observations,
)
from uwb_portfolio_calibration import design_digest, read_frozen


def fetch(old, design, cache, output, workers):
    raw = read_frozen(old)
    design_bytes = design.read_bytes()
    selection = json.loads(design_bytes)
    assert selection["design_input_sha256"] == sha256(old.read_bytes()).hexdigest()
    result = {"source": URL, "design_sha256": design_digest(design), "environments": {}}
    remote = RemoteArchive(cache)
    remote.prefetch([(ARCHIVE_BYTES - 65536, ARCHIVE_BYTES)], 1)
    with ZipFile(remote) as z:
        for env, previous in raw["environments"].items():
            anchors, _, path = choose(z, env)
            assert path == previous["reference_path"]
            excluded = {row["folder"] for row in previous["sites"]}
            if env == "environment2":
                excluded.add(PILOT)
            inventory = {
                member.filename: member
                for member in z.infolist()
                if member.file_size > 100
            }
            entries = []
            root = f"data_set/raw_data/{env}/data"
            for rank, folder in enumerate(path):
                if folder in excluded:
                    continue
                members = {
                    name: inventory[entry]
                    for name in anchors
                    if (entry := f"{root}/{folder}/ch1_{name}.csv") in inventory
                }
                entries.append((rank, folder, members))
            spans = merged_ranges(
                z, (item for _, _, sources in entries for item in sources.values())
            )
            print(
                json.dumps(
                    {
                        "environment": env,
                        "unused_positions": len(entries),
                        "bytes": sum(b - a for a, b in spans),
                    }
                ),
                flush=True,
            )
            remote.prefetch(spans, workers)
            result["environments"][env] = {
                "anchors_m": {a: list(map(str, x)) for a, x in anchors.items()},
                "reference_path": path,
                "sites": [
                    {
                        "rank": i,
                        "folder": folder,
                        "position_m": folder.split("_"),
                        "split": "calibration" if i // 5 % 2 == 0 else "heldout",
                        "anchors": read_observations(z, members, anchors),
                    }
                    for i, folder, members in entries
                ],
            }
    output.write_bytes(
        gzip.compress(json.dumps(result, separators=(",", ":")).encode(), mtime=0)
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for arg in ("old", "design", "cache", "output"):
        parser.add_argument(arg, type=Path)
    parser.add_argument("--workers", default=8, type=int)
    args = parser.parse_args()
    fetch(args.old, args.design, args.cache, args.output, args.workers)
