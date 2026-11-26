"""Validate priced multi-file release signatures on fixed public wheel families."""

from argparse import ArgumentParser
from concurrent.futures import ThreadPoolExecutor
from hashlib import sha256
import json
from pathlib import Path, PurePosixPath
from stat import S_ISLNK
from subprocess import SubprocessError
from zipfile import ZipFile

from weighted_bench import releases
from weighted_overlap import Diagnostic, Plan

RELEASES = {
    "filelock": ("3.15.4", "3.16.1", "3.17.0", "3.18.0", "3.19.1"),
    "platformdirs": ("4.2.2", "4.3.2", "4.3.6", "4.3.7", "4.3.8"),
    "starlette": ("0.40.0", "0.41.3", "0.42.0", "0.44.0", "0.46.2"),
    "fastapi": ("0.112.0", "0.113.0", "0.114.2", "0.115.0", "0.115.12"),
    "anyio": ("4.5.0", "4.6.2.post1", "4.7.0", "4.8.0", "4.9.0"),
    "jsonschema": ("4.20.0", "4.21.1", "4.22.0", "4.23.0", "4.24.0"),
    "networkx": ("3.1", "3.2.1", "3.3", "3.4.1", "3.4.2"),
    "Babel": ("2.13.1", "2.14.0", "2.15.0", "2.16.0", "2.17.0"),
}
EXCLUDED = {"tests", "test", "testing", "docs", "benchmarks", "examples"}
METADATA = ".dist-info/METADATA"


def intake(cache):
    cache.mkdir(parents=True, exist_ok=True)
    with ThreadPoolExecutor(max_workers=8) as pool:
        jobs = {
            n: [pool.submit(releases, cache, n, v) for v in vs]
            for n, vs in RELEASES.items()
        }
        result = {}
        for name, fs in jobs.items():
            paths = []
            try:
                paths.extend(f.result() for f in fs)
            except (OSError, RuntimeError, SubprocessError, ValueError) as exc:
                result[name] = {"versions": RELEASES[name], "error": str(exc)}
            else:
                result[name] = {"sources": [data for _, data in paths]}
            print(name, "ok" if "sources" in result[name] else "incomplete", flush=True)
    return result


def sources(path, name):
    out = {}
    with ZipFile(path) as z:
        for entry in z.infolist():
            p = PurePosixPath(entry.filename)
            if (
                entry.is_dir()
                or S_ISLNK(entry.external_attr >> 16)
                or not entry.file_size
                or ".." in p.parts
            ):
                continue
            if (
                len(p.parts) == 2
                and p.parts[0].endswith(".dist-info")
                and p.name == "METADATA"
            ):
                key = METADATA
            elif (
                p.parts[0] == name.casefold()
                and p.suffix == ".py"
                and not EXCLUDED.intersection(s.casefold() for s in p.parts)
            ):
                key = entry.filename
            else:
                continue
            if key in out:
                raise ValueError(f"duplicate member {key} in {path.name}")
            out[key] = z.read(entry)
    return out


def digest(data):
    return sha256(data).hexdigest()


def catalogs(cache, inputs):
    books = {}
    for package, row in inputs.items():
        if "error" in row:
            books[package] = row
            continue
        records = [sources(cache / s["file"], package) for s in row["sources"]]
        files = {}
        for key in sorted(set.intersection(*(set(r) for r in records))):
            contents = tuple(r[key] for r in records)
            digests = tuple(map(digest, contents))
            differs = sum(
                1 << i for i, g in enumerate(digests[:-1]) if g != digests[-1]
            )
            if differs:
                files[key] = (
                    {
                        "mask": differs,
                        "price": max(map(len, contents)),
                        "sizes": list(map(len, contents)),
                        "sha256": digests,
                    },
                    contents,
                )
        books[package] = {**row, "files": files}
    return books


def replay(diagnostic, plan, f, data, world, flips):
    read = bought = delivered = 0

    def answer(queries):
        nonlocal read, bought, delivered
        replies = []
        for i in queries:
            member, worlds = data[i]
            body = worlds[world]
            observed = digest(body) != member["sha256"][-1]
            assert observed == bool(member["mask"] & (1 << world))
            flip = read in flips
            replies.append(int(observed ^ flip))
            read += 1
            bought += member["price"]
            delivered += len(body)
        return replies

    result = diagnostic.run(plan, f, answer)
    expected = "old" if world < diagnostic.old_count else "extension"
    assert result.family == expected
    assert expected == "extension" or world in result.possible_old
    assert (
        bought <= plan.worst and delivered <= bought and len(result.observations) <= 2
    )
    return {
        "world": world,
        "flip_input_positions": flips,
        "charge": bought,
        "bytes": delivered,
        "batches": result.observations,
    }


def review(family, include_metadata):
    selected = {
        p: v for p, v in family["files"].items() if include_metadata or p != METADATA
    }
    names = list(selected)
    data = tuple(selected.values())
    d = Diagnostic(
        len(family["sources"]) - 1,
        [m["mask"] for m, _ in data],
        [m["price"] for m, _ in data],
    )
    info = {
        "paths": names,
        "count_masks": len(d.probes),
        "has_overlap": any(
            sum(bool(d.masks[i] & (1 << w)) for i in d.probes) > 1
            for w in range(d.old_count)
        ),
    }
    if d.available != d.full:
        info["unsupported_old"] = [
            j for j in range(d.old_count) if not (d.available & (1 << j))
        ]
        return info
    cheapest = [
        (min(d.costs[i] for i in d.probes if d.masks[i] & (1 << j)), j)
        for j in range(d.old_count)
    ]
    lower, bottleneck = max(cheapest)
    all_hit = [i for i in d.probes if d.masks[i] == d.full]
    universal = min(all_hit, default=None, key=d.costs.__getitem__)
    info["universal_certificate"] = {
        "bottleneck_old": bottleneck,
        "bottleneck_min_price": lower,
        "universal_path": None if universal is None else names[universal],
        "universal_price": None if universal is None else d.costs[universal],
        "optimal_for_any_round_count": universal is not None
        and d.costs[universal] == lower,
    }
    by_errors = {}
    for f in (1, 2):
        quote, fixed = d.fixed(d.full, f + 1)
        plans = {
            "two": d.compile(f),
            "cover_first": d.compile(f, cover_first=True),
            "fixed": Plan(fixed, quote, 0, False),
        }
        if f == 1:
            for covers, baseline in ((False, "two"), (True, "cover_first")):
                repeat = d.compile_repeat(cover_first=covers)
                assert repeat.worst == plans[baseline].worst
                for j in range(d.old_count + 1):
                    replay(d, repeat, f, data, j, ())
        adaptive = d.adaptive(f)
        assert adaptive <= plans["two"].worst <= min(quote, plans["cover_first"].worst)
        row = {}
        for key, p in plans.items():
            cases = [(i, ()) for i in range(d.old_count + 1)]
            cases += [(d.old_count, tuple(range(n))) for n in range(1, f + 1)]
            events = [replay(d, p, f, data, world, flips) for world, flips in cases]
            assert max(x["charge"] for x in events) == p.worst
            row[key] = {
                "quote": p.worst,
                "first": p.first,
                "states": p.examined_states,
                "events": events,
                "max_actual_bytes": max(r["bytes"] for r in events),
            }
        by_errors[str(f)] = {"adaptive": adaptive, "policies": row}
    info["by_errors"] = by_errors
    return info


def evaluate(cache, inputs):
    rows = {}
    for name, family in catalogs(cache, inputs).items():
        if "error" in family:
            rows[name] = family
            continue
        rows[name] = {
            "sources": family["sources"],
            "members": {p: m for p, (m, _) in family["files"].items()},
            "content": review(family, False),
            "with_metadata": review(family, True),
        }
    summary = {}
    for mode in ("content", "with_metadata"):
        arms = [r[mode] for r in rows.values() if mode in r]
        for f in ("1", "2"):
            compared = [r["by_errors"][f] for r in arms if "by_errors" in r]
            totals = {
                m: sum(x["policies"][m]["quote"] for x in compared)
                for m in ("two", "fixed", "cover_first")
            }
            totals["adaptive"] = sum(x["adaptive"] for x in compared)
            chosen = sum(
                x["policies"]["two"]["quote"] < x["policies"]["cover_first"]["quote"]
                for x in compared
            )
            summary[f"{mode}_{f}"] = {
                "comparable": len(compared),
                "overlap": sum(r["has_overlap"] for r in arms),
                "better_than_full_first": chosen,
                "totals": totals,
            }
    lead = summary["content_1"]
    gate = (
        lead["overlap"] >= 5
        and lead["better_than_full_first"] >= 3
        and lead["totals"]["fixed"] > 0
        and 100 * lead["totals"]["two"] <= 90 * lead["totals"]["fixed"]
    )
    return {"packages": rows, "summary": summary, "passed_primary_gate": gate}


if __name__ == "__main__":
    cli = ArgumentParser(description=__doc__)
    cli.add_argument("cache", type=Path)
    cli.add_argument("intake", type=Path)
    cli.add_argument("--result", type=Path)
    params = cli.parse_args()
    if params.result is None:
        inputs = intake(params.cache)
        params.intake.write_text(json.dumps(inputs, indent=2) + "\n", encoding="utf-8")
    else:
        inputs = json.loads(params.intake.read_bytes())
        for row in inputs.values():
            for src in row.get("sources", []):
                assert (
                    digest((params.cache / src["file"]).read_bytes()) == src["sha256"]
                )
        result = evaluate(params.cache, inputs)
        params.result.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
        print(json.dumps({k: result[k] for k in ("summary", "passed_primary_gate")}))
