"""Freeze public GitHub Actions step times for the registered disclosure study."""

import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
import gzip
from hashlib import sha256
import json
from pathlib import Path
import subprocess


PINS = Path(__file__).with_name("slack-certificate-pins.json")


def digest(raw):
    return sha256(raw).hexdigest()


def documents(pin, directory, cached):
    repo, run, attempt = pin["repo"], pin["id"], pin["run_attempt"]
    src = f"repos/{repo}/actions/runs/{run}/attempts/{attempt}/jobs?per_page=100"
    file = directory / f"{repo.replace('/', '--')}--{run}--{attempt}.json"
    if cached:
        raw = file.read_bytes()
    else:
        raw = subprocess.check_output(
            ["gh", "api", "--paginate", "--slurp", src], timeout=125
        )
    pages = json.loads(raw)
    jobs = [row for page in pages for row in page["jobs"]]
    if len(jobs) != pages[0]["total_count"]:
        raise ValueError(f"incomplete pagination for {src}")
    if len(jobs) != len({row["id"] for row in jobs}):
        raise ValueError(f"repeated job ID for {src}")
    if not cached:
        file.write_bytes(raw)
    return jobs, dict(pin, endpoint=src, jobs=len(jobs), raw_sha256=digest(raw))


def ticks(iso):
    stamp = datetime.fromisoformat(iso)
    if stamp.utcoffset() is None or stamp.microsecond:
        raise ValueError("expected an integral number of seconds with a UTC offset")
    return int(stamp.timestamp())


def record(pin, job):
    if job["status"] != "completed":
        return None, "unfinished"
    steps = []
    for s in job["steps"]:
        a, b = s["started_at"], s["completed_at"]
        if a and b:
            steps.append((s["number"], ticks(a), ticks(b)))
    if len(steps) < 5:
        return None, "fewer_than_five_steps"
    steps.sort()
    if len(steps) != len({number for number, _, _ in steps}):
        raise ValueError(f"duplicate step number in {job['id']}")
    kept = steps[:24]
    epoch = 60 * (min(t for _, a, b in kept for t in (a, b)) // 60)
    return dict(
        repo=pin["repo"],
        run=pin["id"],
        attempt=pin["run_attempt"],
        head_sha=pin["head_sha"],
        job=job["id"],
        origin_epoch=epoch,
        steps=[[number, a - epoch, b - epoch] for number, a, b in kept],
    ), "truncated" if len(steps) > len(kept) else "in_window"


def prepare(sources, output, cached):
    pins = json.loads(PINS.read_bytes())
    sources.mkdir(parents=True, exist_ok=True)
    output.mkdir(parents=True, exist_ok=False)
    rows, manifest = [], []
    with ThreadPoolExecutor(max_workers=5) as pool:
        pending = [pool.submit(documents, p, sources, cached) for p in pins]
        for p, work in zip(pins, pending, strict=True):
            jobs, source = work.result()
            candidates, counts = [], Counter()
            for job in jobs:
                task, status = record(p, job)
                counts[status] += 1
                if task is not None:
                    key = "\n".join(map(str, (p["repo"], p["id"], task["job"])))
                    candidates.append((digest(key.encode()), task))
            retained = [row for _, row in sorted(candidates, key=lambda x: x[0])[:8]]
            rows.extend(retained)
            manifest.append(dict(source, retained=len(retained), status=counts))
    body = (json.dumps(rows, separators=(",", ":")) + "\n").encode()
    (output / "slack-certificate-fixtures.json.gz").write_bytes(
        gzip.compress(body, mtime=0)
    )
    manifest_data = dict(
        records=len(rows), fixture_sha256=digest(body), sources=manifest
    )
    (output / "slack-certificate-sources.json").write_bytes(
        (json.dumps(manifest_data, indent=2) + "\n").encode()
    )
    return dict(records=len(rows), sources=len(manifest))


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("sources", type=Path)
    p.add_argument("output", type=Path)
    p.add_argument("--cached", action="store_true")
    a = p.parse_args()
    print(json.dumps(prepare(a.sources, a.output, a.cached)))
