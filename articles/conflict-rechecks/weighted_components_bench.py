"""Replay exact component plans on actual Cargo lock dependency versions."""

from argparse import ArgumentParser
import gzip
from hashlib import sha256
from itertools import combinations, product
import json
from pathlib import Path, PurePosixPath
import tarfile

from weighted_overlap import Diagnostic
from weighted_components import ComponentDiagnosis, ProductPlan, Profile


def catalog(path, source):
    prefix = source["name"] + "-" + source["version"]
    package = path.read_bytes()
    assert (
        sha256(package).hexdigest() == source["sha256"]
        and len(package) == source["bytes"]
    )
    members = {"@archive": package}
    with tarfile.open(path, mode="r:gz") as z:
        for item in z:
            key = PurePosixPath(item.name)
            if (
                item.isfile()
                and item.size > 0
                and len(key.parts) > 2
                and key.parts[:2] == (prefix, "src")
                and ".." not in key.parts
                and key.suffix == ".rs"
            ):
                member = PurePosixPath(*key.parts[1:]).as_posix()
                assert member not in members
                with z.extractfile(item) as r:
                    members[member] = r.read()
    return members


def component(name, variants, source_index, cache):
    inputs = [source_index[name, p["version"], p["sha256"]] for p in variants]
    a = [catalog(cache / d["file"], d) for d in inputs]
    rows = []
    bodies = []
    for p in sorted(set.intersection(*(set(x) for x in a))):
        files = tuple(x[p] for x in a)
        stamps = [sha256(w).hexdigest() for w in files]
        mask = sum(1 << i for i, w in enumerate(stamps[:-1]) if w != stamps[-1])
        if mask:
            rows.append(
                {
                    "path": p,
                    "price": max(map(len, files)),
                    "sha256": stamps,
                    "sizes": list(map(len, files)),
                    "mask": mask,
                }
            )
            bodies.append(files)
    record = {"name": name, "sources": inputs, "rows": rows}
    return record, bodies


def positions(healthy):
    targets = tuple(range(len(healthy)))
    for k in (1, 2):
        for where in combinations(targets, k):
            for choices in product(*(range(healthy[i]) for i in where)):
                v = list(healthy)
                for i, u in zip(where, choices, strict=True):
                    v[i] = u
                yield tuple(v)
    if len(healthy) > 2:
        yield (0,) * len(healthy)


def replay(engine, plan, f, records, files, world, flips):
    paid = payload = calls = 0

    def sensor(keys):
        nonlocal paid, payload, calls
        bits = []
        for c, j in keys:
            m = records[c]["rows"][j]
            observed = files[c][j][world[c]]
            bit = sha256(observed).hexdigest() != m["sha256"][-1]
            assert bit == bool(m["mask"] & (1 << world[c]))
            bits.append(int(bit) ^ int(calls in flips))
            calls += 1
            paid += m["price"]
            payload += len(observed)
        return bits

    decision = engine.run(plan, f, sensor)
    expected = (
        "target" if world == tuple(d.old_count for d in engine.components) else "old"
    )
    assert decision.family == expected
    assert expected == "target" or all(
        v in opts for v, opts in zip(world, decision.compatible_choices, strict=True)
    )
    assert payload <= paid <= plan.worst and len(decision.observations) <= 2
    return {
        "world": world,
        "flips": flips,
        "paid": paid,
        "bytes": payload,
        "observations": decision.observations,
    }


def evaluate(cache, source):
    versions = {
        (p["name"], p["version"], p["sha256"]): p for p in source["dependencies"]
    }
    all_rows = {}
    for application, value in source["applications"].items():
        if "unavailable" in value or not value["choices"]:
            all_rows[application] = {
                "unavailable": value.get("unavailable", "no eligible components")
            }
            continue
        prepared = [
            component(n, v, versions, cache) for n, v in value["choices"].items()
        ]
        records, bodies = map(list, zip(*prepared, strict=True))
        ds = tuple(
            Diagnostic(
                len(c["sources"]) - 1,
                [p["mask"] for p in c["rows"]],
                [p["price"] for p in c["rows"]],
            )
            for c in records
        )
        engine = ComponentDiagnosis(ds)
        healthy = tuple(d.old_count for d in ds)
        supported = [i for i, d in enumerate(ds) if d.available != d.full]
        row = {
            "components": records,
            "non_target_worlds": engine.product_size - 1,
            "single_component_worlds": sum(healthy),
            "effective_probe_counts": [len(d.probes) for d in ds],
        }
        all_rows[application] = row
        if supported:
            row["unsupported"] = supported
            continue
        quote = {}
        for f in (1, 2):
            two = engine.compile(f)
            first = engine.compile(f, cover_first=True)
            sub = [d.fixed(d.full, f + 1) for d in ds]
            fixed_cost = sum(p for p, _ in sub)
            fixed = ProductPlan(
                tuple(Profile(q, p, 0, 0) for p, q in sub), fixed_cost, False, 0
            )
            assert fixed_cost == engine.fixed_cost(f)
            cases = [(world, ()) for world in positions(healthy)] + [
                (healthy, tuple(range(j))) for j in range(f + 1)
            ]
            policies = {}
            for key, plan in (("exact2", two), ("full_first", first), ("fixed", fixed)):
                events = [
                    replay(engine, plan, f, records, bodies, w, m) for w, m in cases
                ]
                assert max(r["paid"] for r in events) == plan.worst
                policies[key] = {
                    "cost": plan.worst,
                    "first": [p.first for p in plan.profiles],
                    "frontier_states": plan.convolution_states,
                    "max_payload": max(r["bytes"] for r in events),
                    "events": events,
                }
            quote[str(f)] = policies
        row["quote"] = quote
        print(application, len(ds), engine.product_size - 1, flush=True)
    summary = {}
    for f in ("1", "2"):
        scoped = [p for p in all_rows.values() if "quote" in p]
        fees = {
            mode: sum(p["quote"][f][mode]["cost"] for p in scoped)
            for mode in ("exact2", "full_first", "fixed")
        }
        summary[f] = {
            "valid": len(scoped),
            "four_or_more": sum(len(p["components"]) >= 4 for p in scoped),
            "strict_better_full_first": sum(
                p["quote"][f]["exact2"]["cost"] < p["quote"][f]["full_first"]["cost"]
                for p in scoped
            ),
            "total": fees,
        }
    prime = summary["1"]
    gate = (
        prime["four_or_more"] >= 3
        and prime["strict_better_full_first"] >= 2
        and 100 * prime["total"]["exact2"] <= 85 * prime["total"]["fixed"]
    )
    return {"applications": all_rows, "summary": summary, "passed_primary_gate": gate}


if __name__ == "__main__":
    p = ArgumentParser(description=__doc__)
    for field in ("cache", "intake", "output"):
        p.add_argument(field, type=Path)
    args = p.parse_args()
    result = evaluate(args.cache, json.loads(args.intake.read_bytes()))
    args.output.write_bytes(
        gzip.compress(json.dumps(result, separators=(",", ":")).encode(), mtime=0)
    )
    print(json.dumps({k: result[k] for k in ("summary", "passed_primary_gate")}))
