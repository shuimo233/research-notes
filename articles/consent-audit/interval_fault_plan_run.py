"""Replay trusted channels and exact costs on the fixed weather and GTFS archives."""

import argparse
from collections import Counter, defaultdict
import gzip
from hashlib import sha256
from itertools import combinations
import json
from pathlib import Path

from interval_fault_cut_run import EDGES, days
from interval_fault_delta import compile_two
from interval_fault_delta_run import BART, injected, is_connected
from interval_fault_path import compile_path
from interval_fault_plan import Probe, finite_plan, fixed_cost, interval_plan


def cycle(size, edges):
    neighbors = [set() for _ in range(size)]
    for u, v in edges:
        neighbors[u].add(v)
        neighbors[v].add(u)

    def extend(path, length):
        origin, last = path[0], path[-1]
        if len(path) == length:
            return path if origin in neighbors[last] else None
        for v in sorted(neighbors[last]):
            if v > origin and v not in path:
                found = extend((*path, v), length)
                if found is not None:
                    return found
        return None

    for length in (6, 4):
        for u in range(size):
            found = extend((u,), length)
            if found is not None:
                return found
    return None


def single_reports(key, values, edges):
    scope = key.split("/")[0]
    if scope == "weather":
        b = sha256(key.removeprefix("weather/").encode()).digest()
        i, size, negative = b[0] % 6, (1, 5, 15)[b[2] % 3], not b[1] % 2
    else:
        b = sha256((key + "/1").encode()).digest()
        i, size, negative = b[0] % len(edges), (60, 180, 300)[b[1] % 3], not b[2] % 2
    return [
        (s, t, values[t] - values[s] + ((-size if negative else size) if j == i else 0))
        for j, (s, t) in enumerate(edges)
    ]


def cases(weather, bart, transfer):
    for panel, date, values, bands in days(weather):
        key = f"weather/{panel}/{date}"
        targets = (
            [p for p in combinations(range(5), 2) if p not in EDGES]
            if transfer
            else EDGES
        )
        yield key, 1, values, bands, EDGES, 10, None, targets
        if not transfer:
            yield key, 2, values, bands, EDGES, 10, None, EDGES
    raw = bart.read_bytes()
    assert sha256(raw).hexdigest() == BART
    for row in json.loads(gzip.decompress(raw)):
        values = tuple(x["second"] for x in row["events"])
        bands = [(x - x % 300, x - x % 300 + 299) for x in values]
        key = f"bart/{row['station']}/{row['date']}/{row['start']}"
        edges = tuple((u - 1, v - 1) for u, v in row["pairs"])
        ring = cycle(len(values), edges)
        if ring is None:
            yield key, 1, None, None, None, None, "no_cycle", None
        else:
            e = tuple((i, (i + 1) % len(ring)) for i in range(len(ring)))
            targets = e
            if transfer:
                position = {original: rank for rank, original in enumerate(ring)}
                ring_edges = {tuple(sorted(pair)) for pair in e}
                candidates = [
                    (position[u], position[v])
                    for u, v in edges
                    if u in position and v in position
                ]
                targets = [
                    pair for pair in candidates if tuple(sorted(pair)) not in ring_edges
                ]
            yield (
                key,
                1,
                tuple(values[i] for i in ring),
                [bands[i] for i in ring],
                e,
                180,
                list(ring),
                targets,
            )
        if not transfer:
            if is_connected(len(values), edges):
                yield key, 2, values, bands, edges, 180, None, edges
            else:
                yield key, 2, None, None, None, None, "disconnected", None


def channels(key, budget, size, edges, transfer):
    pairs = {tuple(sorted(edge)) for edge in edges}
    result = []
    for u, v in combinations(range(size), 2):
        b = sha256(f"{key}/{budget}/probe/{u}/{v}".encode()).digest()
        if transfer and b[2] % 3 == 0:
            continue
        if (u, v) in pairs:
            cost = 1 + b[1] % 4
        elif b[0] % 3 == 0:
            cost = 3 + b[1] % 4
        else:
            continue
        result.append((u, v, cost))
    return result


def path_worlds(path):
    worlds = []
    for j, edge in zip(path.kept_positions, path.repair_edges, strict=True):
        shifted = tuple(
            a + path.residual * (v >= j)
            for a, v in zip(path.base, path.position, strict=True)
        )
        worlds.append(([edge], tuple(v - shifted[0] for v in shifted)))
    return worlds


def replay(
    key, budget, values, bands, edges, threshold, selection, targets, *, transfer
):
    packet = {
        "id": key,
        "budget": budget,
        "cycle": selection if isinstance(selection, list) else None,
    }
    if values is None:
        packet["excluded"] = selection
        return packet
    if budget == 1:
        path = compile_path(bands, single_reports(key, values, edges))
        states = path_worlds(path)
    else:
        path = None
        reports, _ = injected(key.split("/")[0], key, values, edges)
        packed = compile_two(bands, reports)
        if packed.minimum != 2:
            packet["excluded"] = f"graph_minimum_{packed.minimum}"
            return packet
        states = [(list(k), v) for k, v in sorted(packed.repair_coordinates().items())]
    actual = tuple(x - values[0] for x in values)
    coords = [x for _, x in states]
    actual_index = coords.index(actual)
    inventory = channels(key, budget, len(values), edges, transfer)
    q = []
    for u, v, cost in inventory:
        window = None
        if path is not None:
            window = path.partition(u, v)[2:]
        q.append(Probe(cost, tuple(x[v] - x[u] for x in coords), window))
    outputs = []
    for s, t in targets:
        active = [
            i for i, probe in enumerate(inventory) if probe[:2] != tuple(sorted((s, t)))
        ]
        allowed = [q[i] for i in active]
        expected = [x[t] - x[s] >= threshold for x in coords]
        plan = (interval_plan if path is not None else finite_plan)(expected, allowed)
        fixed = fixed_cost(expected, allowed)
        assert (fixed is None) == (plan.cost is None)
        if path is not None:
            assert finite_plan(expected, allowed).cost == plan.cost
        if plan.cost is None:
            i, j = plan.counterexample
            assert expected[i] != expected[j] and all(
                p.answers[i] == p.answers[j] for p in allowed
            )
            outputs.append({"counterexample": [i, j], "visited": plan.visited})
            continue
        charged = [plan.walk(i) for i in range(len(states))]
        assert [z[0] for z in charged] == expected and max(
            z[1] for z in charged
        ) == plan.cost
        minimum_two = (
            all(
                len({v for v, e in zip(p.answers, expected, strict=True) if e})
                + len({v for v, e in zip(p.answers, expected, strict=True) if not e})
                > len(set(p.answers))
                for p in allowed
            )
            if plan.cost
            else False
        )
        outputs.append(
            {
                "worst": plan.cost,
                "fixed": fixed,
                "at_least_two": minimum_two,
                "paths": [[active[i] for i in z[2]] for z in charged],
                "actual_cost": charged[actual_index][1],
                "visited": plan.visited,
            }
        )
    packet.update({"repairs": [r for r, _ in states], "targets": outputs})
    return packet


def summarize(ledger, transfer):
    groups = defaultdict(Counter)
    for row in ledger:
        source = row["id"].split("/")[0]
        for name in (source + "-" + str(row["budget"]), str(row["budget"]), "all"):
            counts = groups[name]
            if "excluded" in row:
                counts[row["excluded"]] += 1
                continue
            counts["archives"] += 1
            if not row["targets"]:
                counts["archives_no_targets"] += 1
            counts["max_worlds"] = max(counts["max_worlds"], len(row["repairs"]))
            for outcome in row["targets"]:
                counts["targets"] += 1
                if "counterexample" in outcome:
                    counts["unsettled"] += 1
                    continue
                if not outcome["worst"]:
                    counts["known"] += 1
                    continue
                counts["settleable"] += 1
                counts["needs_multiple"] += outcome["at_least_two"]
                counts["worst"] += outcome["worst"]
                counts["fixed"] += outcome["fixed"]
                counts["realized"] += outcome["actual_cost"]
                counts["strict"] += outcome["worst"] < outcome["fixed"]
    c = groups["all"]
    return {
        "counts": dict(sorted(groups.items())),
        "utility_gate": c["settleable"] >= 50
        and (not transfer or c["unsettled"] >= 20),
        "cost_gate": bool(c["fixed"]) and 20 * (c["fixed"] - c["worst"]) >= c["fixed"],
    }


def run(weather, bart, out, transfer=False):
    ledger = [
        replay(*case, transfer=transfer) for case in cases(weather, bart, transfer)
    ]
    summary = summarize(ledger, transfer)
    stem = "interval-fault-plan" + ("-transfer" if transfer else "")
    out.mkdir(parents=True, exist_ok=True)
    (out / f"{stem}-ledger.json.gz").write_bytes(
        gzip.compress(json.dumps(ledger, separators=(",", ":")).encode(), mtime=0)
    )
    (out / f"{stem}-results.json").write_text(
        json.dumps(summary, indent=2) + "\n", encoding="utf-8", newline="\n"
    )
    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("noaa", "bart", "out"):
        parser.add_argument(name, type=Path)
    parser.add_argument("--transfer", action="store_true")
    args = parser.parse_args()
    print(json.dumps(run(args.noaa, args.bart, args.out, args.transfer)))
