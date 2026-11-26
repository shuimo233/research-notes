"""Replay priced diagnostic plans against published, non-executed wheel members."""

import argparse
from collections import Counter
from hashlib import sha256
import json
from pathlib import Path, PurePosixPath
from shutil import which
import stat
import subprocess
from urllib.parse import urlparse
from zipfile import ZipFile

from weighted_batches import (
    BatchPlan,
    best_prefix,
    execute,
    guaranteed,
    optimal,
    sequential_bound,
)

PACKAGES = (
    ("requests", "2.32.3", "2.32.5", ("requests",)),
    ("urllib3", "2.2.3", "2.5.0", ("urllib3",)),
    ("click", "8.1.7", "8.1.8", ("click",)),
    ("packaging", "24.1", "24.2", ("packaging",)),
    ("Jinja2", "3.1.4", "3.1.6", ("jinja2",)),
    ("httpx", "0.27.2", "0.28.1", ("httpx",)),
    ("rich", "13.8.1", "14.0.0", ("rich",)),
    ("pytest", "8.3.3", "8.4.0", ("pytest", "_pytest")),
    ("pydantic", "2.9.2", "2.11.7", ("pydantic",)),
    ("attrs", "24.2.0", "25.3.0", ("attrs", "attr")),
)


def fetch(url, path):
    stage = path.with_name(path.name + ".part")
    args = [
        which("curl.exe") or "curl",
        "--fail",
        "--location",
        "--silent",
        "--show-error",
        "--connect-timeout",
        "12",
        "--max-time",
        "45",
        "--retry",
        "1",
        "--output",
        str(stage),
        url,
    ]
    subprocess.run(args, check=True, capture_output=True)
    stage.replace(path)


def releases(root, package, version):
    release = root / f"{package}-{version}.json"
    listing = f"https://pypi.org/pypi/{package}/{version}/json"
    if not release.exists():
        fetch(listing, release)
    parsed = json.loads(release.read_bytes())
    assert parsed["info"]["version"] == version
    wheels = [r for r in parsed["urls"] if r["filename"].endswith("-none-any.whl")]
    if len(wheels) != 1:
        raise ValueError(
            f"{package} {version}: expected one platform-independent wheel"
        )
    info = wheels[0]
    name = info["filename"]
    assert (
        Path(name).name == name
        and urlparse(info["url"]).hostname == "files.pythonhosted.org"
    )
    path = root / name
    expected = info["digests"]["sha256"]
    if not path.exists() or sha256(path.read_bytes()).hexdigest() != expected:
        fetch(info["url"], path)
    assert path.stat().st_size == info["size"]
    assert sha256(path.read_bytes()).hexdigest() == expected
    return path, {
        "version": version,
        "file": name,
        "metadata": listing,
        "url": info["url"],
        "sha256": expected,
        "size": info["size"],
    }


def catalog(older, newer, roots):
    def source_paths(archive):
        out = set()
        for item in archive.infolist():
            p = PurePosixPath(item.filename)
            if (
                p.parts[0] in roots
                and p.suffix == ".py"
                and item.file_size > 0
                and not item.is_dir()
                and not stat.S_ISLNK(item.external_attr >> 16)
            ):
                assert item.filename not in out
                out.add(item.filename)
        return out

    components = []
    for name in sorted(source_paths(older) & source_paths(newer)):
        old, new = older.read(name), newer.read(name)
        if old != new:
            components.append(
                {
                    "path": name,
                    "old_length": len(old),
                    "new_length": len(new),
                    "old_sha256": sha256(old).hexdigest(),
                    "new_sha256": sha256(new).hexdigest(),
                    "reserve": max(len(old), len(new)),
                }
            )
    return components


def replay(archives, members, plan, f, changed=None, false_positive=False):
    old, new = archives
    bought = fetched = queries = flipped = 0
    batches = 0

    def read_batch(indices):
        nonlocal bought, fetched, queries, flipped, batches
        batches += 1
        replies = []
        for i in indices:
            model = members[i]
            source = old if i == changed else new
            data = source.read(model["path"])
            predicted = sha256(data).hexdigest() != model["new_sha256"]
            assert predicted == (i == changed)
            # In a fixed plan, use the entire budget on the first listed file.
            # Otherwise send one misleading reply first and use the rest after feedback.
            boundary = queries < f if not plan.first else queries == 0 or batches == 2
            should_flip = false_positive and flipped < f and boundary
            replies.append(int(predicted ^ should_flip))
            flipped += should_flip
            bought += model["reserve"]
            fetched += len(data)
            queries += 1
        return replies

    outcome = execute(plan, len(members), f, read_batch)
    assert outcome.family == ("extension" if changed is None else "old")
    if changed is not None:
        assert outcome.possible_old == (changed,)
    assert fetched <= bought <= plan.worst_cost and batches <= 2
    assert flipped == (f if false_positive else 0)
    return {
        "changed": changed,
        "reserved": bought,
        "actual": fetched,
        "queries": queries,
        "batches": batches,
        "flips": flipped,
    }


def trace(archives, members, plan, f):
    observations = [
        replay(archives, members, plan, f, changed=i) for i in range(len(members))
    ]
    observations.extend(
        replay(archives, members, plan, f, false_positive=testing)
        for testing in (False, True)
    )
    worst = max(observations, key=lambda r: (r["reserved"], r["actual"]))
    assert worst["reserved"] == plan.worst_cost
    return {
        "cases": len(observations),
        "replay_actual_bytes_total": sum(r["actual"] for r in observations),
        "max_actual_bytes": max(r["actual"] for r in observations),
        "max_batches": max(r["batches"] for r in observations),
        "worst_reserved_witness": worst,
        "boundary_flip_witness": observations[-1],
    }


def evaluate(older, newer, roots):
    with ZipFile(older) as old, ZipFile(newer) as new:
        members = catalog(old, new, roots)
        if not members:
            return {"members": [], "data_status": "no_selected_members"}
        costs = tuple(r["reserve"] for r in members)
        outcomes = {}
        for f in (1, 2):
            fixed_value = (f + 1) * sum(costs)
            sequential = sequential_bound(costs, f)
            policies = {
                "fixed": BatchPlan((), fixed_value),
                "equal_count": BatchPlan(
                    tuple(range(len(costs))), sum(costs) + f * max(costs)
                ),
                "best_prefix": best_prefix(costs, f),
                "guaranteed": guaranteed(costs, f),
                "optimal": optimal(costs, f),
            }
            assert (
                sequential
                <= policies["optimal"].worst_cost
                <= min(p.worst_cost for p in policies.values())
            )
            assert policies["guaranteed"].worst_cost * (f + 1) ** 2 <= sequential * (
                (f + 1) ** 2 + f * f
            )
            measured = {
                name: trace((old, new), members, policies[name], f)
                for name in ("fixed", "guaranteed")
            }
            outcomes[str(f)] = {
                "sequential": sequential,
                "policies": {
                    name: {"worst_bytes": p.worst_cost, "first": p.first}
                    for name, p in policies.items()
                },
                "replays": measured,
            }
    return {"members": members, "by_error_allowance": outcomes, "data_status": "ok"}


def run(root):
    jobs = {}
    for name, older, newer, roots in PACKAGES:
        paths, sources = zip(
            *(releases(root, name, version) for version in (older, newer)), strict=True
        )
        row = evaluate(*paths, roots)
        row["sources"] = list(sources)
        jobs[name] = row
        print(name, len(row["members"]), row["data_status"], flush=True)
    stats = Counter()
    for package in jobs.values():
        if package["data_status"] != "ok":
            stats["excluded"] += 1
            continue
        phase = package["by_error_allowance"]["1"]
        policies = phase["policies"]
        if (
            100 * policies["guaranteed"]["worst_bytes"]
            <= 85 * policies["fixed"]["worst_bytes"]
        ):
            stats["passed"] += 1
        for key, value in policies.items():
            stats[key] += value["worst_bytes"]
        stats["sequential"] += phase["sequential"]
    return {
        "packages": jobs,
        "f1_totals": dict(stats),
        "passed_primary_gate": stats["passed"] >= 8,
    }


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("data", type=Path)
    p.add_argument("output", type=Path)
    a = p.parse_args()
    a.data.mkdir(parents=True, exist_ok=True)
    result = run(a.data)
    a.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "f1_totals": result["f1_totals"],
                "passed_primary_gate": result["passed_primary_gate"],
            }
        )
    )
