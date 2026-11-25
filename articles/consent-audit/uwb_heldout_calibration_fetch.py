"""Build the compact channel-1 fixture from specified members of Zenodo 8280736."""

import argparse
from bisect import bisect_right
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from csv import DictReader
from decimal import Decimal, InvalidOperation
import gzip
from hashlib import sha256
from io import StringIO
import json
from pathlib import Path
from re import search
import subprocess
from zipfile import ZipFile

URL = "https://zenodo.org/records/8280736/files/data_set.zip?download=1"
ARCHIVE_BYTES = 4441862175
ENVIRONMENTS = ("environment0", "environment2")
PILOT = "12.21_4.95_1.32"
STEM = "uwb-heldout-calibration"


class RemoteArchive:
    def __init__(self, cache):
        self.cache = cache
        self.cache.mkdir(parents=True, exist_ok=True)
        self.position = 0
        self.blocks = {}
        self.starts = []

    def tell(self):
        return self.position

    def seek(self, offset, origin=0):
        self.position = (0, self.position, ARCHIVE_BYTES)[origin] + offset
        return self.position

    def seekable(self):
        return True

    def fetch(self, limits):
        first, stop = limits
        name = self.cache / f"{first}-{stop}.bin"
        header = name.with_suffix(".headers")
        signature = f"bytes {first}-{stop - 1}/{ARCHIVE_BYTES}"

        def valid(file):
            if (
                not file.exists()
                or file.stat().st_size != stop - first
                or not header.exists()
            ):
                return False
            captures = search(
                r"(?im)^content-range:\s*([^\r\n]+)",
                header.read_text(encoding="latin1"),
            )
            return captures and captures[1].strip() == signature

        if not valid(name):
            writing = name.with_suffix(".partial")
            subprocess.run(
                [
                    "curl",
                    "--fail",
                    "--silent",
                    "--show-error",
                    "--location",
                    "--retry",
                    "2",
                    "--retry-delay",
                    "2",
                    "--max-time",
                    "45",
                    "--max-filesize",
                    str(stop - first),
                    "--range",
                    f"{first}-{stop - 1}",
                    "--dump-header",
                    str(header),
                    "--output",
                    str(writing),
                    URL,
                ],
                check=True,
            )
            if not valid(writing):
                raise ValueError(f"incorrect response for range {signature}")
            writing.replace(name)
        return first, stop, name

    def register(self, records):
        self.blocks.update({a: (b, p) for a, b, p in records})
        self.starts = sorted(self.blocks)

    def prefetch(self, ranges, workers):
        with ThreadPoolExecutor(max_workers=workers) as pool:
            self.register(pool.map(self.fetch, ranges))

    def read(self, n=-1):
        first = self.position
        stop = ARCHIVE_BYTES if n < 0 else min(first + n, ARCHIVE_BYTES)
        if first >= stop:
            return b""
        index = bisect_right(self.starts, first) - 1
        if index >= 0:
            start = self.starts[index]
            limit, filename = self.blocks[start]
        if index < 0 or stop > limit:
            start, limit, filename = self.fetch((first, stop))
            self.register([(start, limit, filename)])
        with filename.open("rb") as stream:
            stream.seek(first - start)
            data = stream.read(stop - first)
        self.position = stop
        if len(data) != stop - first:
            raise ValueError("cached range was truncated")
        return data


def coordinates(row, names=("x", "y", "z")):
    return tuple(Decimal(row[key]) for key in names)


def rows(data):
    return list(DictReader(StringIO(data.decode("utf-8-sig"))))


def choose(z, env):
    root = f"data_set/{env}/"
    anchor_name, path_name = root + "anchors.csv", root + "walking_path.csv"
    anchor_rows, path_rows = rows(z.read(anchor_name)), rows(z.read(path_name))
    anchors = {r["Anchor"]: coordinates(r) for r in anchor_rows}
    path = list(map(coordinates, path_rows))
    prefix = f"data_set/raw_data/{env}/data/"
    located = defaultdict(dict)
    for member in z.infolist():
        if not member.filename.startswith(prefix) or member.file_size <= 100:
            continue
        folder, filename = member.filename.removeprefix(prefix).split("/")
        if filename.startswith("ch1_A") and filename.endswith(".csv"):
            site = tuple(map(Decimal, folder.split("_")))
            anchor = filename.removeprefix("ch1_").removesuffix(".csv")
            if anchor in located[site]:
                raise ValueError(f"duplicate raw source at {folder}:{anchor}")
            located[site][anchor] = member
    assert set(located) == set(path) and len(path) == len(located)
    split = defaultdict(list)
    for idx, site in enumerate(path):
        members = located[site]
        folder = folder_name(members)
        if env == "environment2" and folder == PILOT:
            continue
        side = "calibration" if idx // 5 % 2 == 0 else "heldout"
        key = sha256(f"uwb-offset-v1/{env}/{folder}".encode()).digest()
        split[side].append((key, idx, folder, site, members))
    chosen = [
        (idx, folder, site, side, members)
        for side, candidates in split.items()
        for _, idx, folder, site, members in sorted(candidates)[:20]
    ]
    return anchors, sorted(chosen), [folder_name(located[site]) for site in path]


def folder_name(members):
    return next(iter(members.values())).filename.split("/")[-2]


def merged_ranges(archive, members):
    offsets = sorted(
        {item.header_offset for item in archive.infolist()} | {archive.start_dir}
    )
    next_offset = dict(zip(offsets, offsets[1:]))
    ranges = []
    for first in sorted({item.header_offset for item in members}):
        limit = next_offset[first]
        if (
            ranges
            and limit - ranges[-1][0] <= 4_000_000
            and first - ranges[-1][1] <= 800_000
        ):
            ranges[-1] = (ranges[-1][0], limit)
        else:
            ranges.append((first, limit))
    return ranges


def read_observations(z, members, anchors):
    measurements = {}
    for anchor, member in sorted(members.items()):
        raw = z.read(member)
        lines = StringIO(raw.decode("utf-8-sig"))
        version = next(lines).strip()
        if version != "v1.1" or anchor not in anchors:
            raise ValueError(f"unexpected member or schema: {member.filename}")
        values, categories = [], set()
        tags, installed = set(), set()
        for row in DictReader(lines):
            if row["CHANNEL_NUMBER"] != "1":
                raise ValueError("selected member is not channel 1")
            categories.add(row["NLOS"])
            tags.add(coordinates(row, ("X_TAG", "Y_TAG", "Z_TAG")))
            installed.add(coordinates(row, ("X_ANCHOR", "Y_ANCHOR", "Z_ANCHOR")))
            try:
                value = Decimal(row["RANGE"])
            except InvalidOperation:
                continue
            if value.is_finite():
                values.append(str(value))
        measurements[anchor] = {
            "member": member.filename,
            "crc32": f"{member.CRC:08x}",
            "sha256": sha256(raw).hexdigest(),
            "range_m": values,
            "los": sorted(categories),
            "raw_tag_m": [list(map(str, t)) for t in sorted(tags)],
            "raw_anchor_m": [list(map(str, a)) for a in sorted(installed)],
        }
    return measurements


def build(workdir, workers=8):
    remote = RemoteArchive(workdir / "range-cache")
    remote.prefetch([(ARCHIVE_BYTES - 65536, ARCHIVE_BYTES)], 1)
    with ZipFile(remote) as archive:
        selected = {env: choose(archive, env) for env in ENVIRONMENTS}
        fixtures = {"source": URL, "archive_bytes": ARCHIVE_BYTES, "environments": {}}
        for env, (anchors, locations, path) in selected.items():
            ranges = merged_ranges(
                archive,
                (m for _, _, _, _, members in locations for m in members.values()),
            )
            print(
                json.dumps(
                    {
                        "environment": env,
                        "ranges": len(ranges),
                        "bytes": sum(b - a for a, b in ranges),
                    }
                ),
                flush=True,
            )
            remote.prefetch(ranges, workers)
            fixtures["environments"][env] = {
                "anchors_m": {k: list(map(str, v)) for k, v in anchors.items()},
                "path_size": len(path),
                "reference_path": path,
                "sites": [
                    {
                        "rank": idx,
                        "folder": folder,
                        "position_m": list(map(str, site)),
                        "split": side,
                        "anchors": read_observations(archive, members, anchors),
                    }
                    for idx, folder, site, side, members in locations
                ],
            }
            print(
                json.dumps({"environment": env, "verified_sites": len(locations)}),
                flush=True,
            )
    (workdir / (STEM + "-observations.json.gz")).write_bytes(
        gzip.compress(json.dumps(fixtures, separators=(",", ":")).encode(), mtime=0)
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    parser.add_argument("--workers", type=int, default=8)
    args = parser.parse_args()
    build(args.output, args.workers)
