"""Independently score timetable transcripts with raw difference-constraint checks."""

import argparse
from collections import Counter
import csv
import gzip
from hashlib import sha256
from io import TextIOWrapper
from itertools import combinations
import json
from pathlib import Path
import sys
from zipfile import ZipFile

sys.path.insert(0, str(Path(__file__).resolve().parent))
from public_optimality_check import check_shorter, groups_valid, model
from slack_certificate_check import potential


def unpack(path):
    return gzip.decompress(path.read_bytes())


def values(rows):
    return tuple(
        int(h) * 3600 + int(m) * 60 + int(s)
        for h, m, s in (field.split(":") for field in rows)
    )


def source_matches(fixtures, manifest, original=None):
    source = json.loads(manifest.read_bytes())
    normalized = unpack(fixtures)
    assert sha256(normalized).hexdigest() == source["fixture_sha256"]
    cases = json.loads(normalized)
    assert len(cases) == source["selected"] == 500
    if original is not None:
        assert sha256(original.read_bytes()).hexdigest() == source["archive_sha256"]
        selection = {
            (e["trip"], e["station"], str(e["sequence"]), e["role"]): e["second"]
            for case in cases
            for e in case["events"]
        }
        seen = {}
        with ZipFile(original) as z, z.open("stop_times.txt") as f:
            for row in csv.DictReader(TextIOWrapper(f, encoding="utf-8-sig")):
                for role, perm in (
                    ("arrival", "drop_off_type"),
                    ("departure", "pickup_type"),
                ):
                    identity = (
                        row["trip_id"],
                        row["stop_id"],
                        row["stop_sequence"],
                        role,
                    )
                    if identity in selection:
                        assert row[perm] != "1"
                        seen[identity] = values([row[role + "_time"]])[0]
        assert seen == selection
    return cases


def packets_match(case, packet):
    proof, archive = packet["certificate"], packet["archive"]
    actual = (0, *(v["second"] for v in case["events"]))
    lows = [u - u % 300 for u in actual[1:]]
    assert archive["bands"] == [[u, u + 299] for u in lows]
    arrivals = [i for i, e in enumerate(case["events"], 1) if e["role"] == "arrival"]
    departures = [
        i for i, e in enumerate(case["events"], 1) if e["role"] == "departure"
    ]
    events = {i: e for i, e in enumerate(case["events"], 1)}
    expected = [
        [u, v]
        for u in arrivals
        for v in departures
        if events[u]["route"] != events[v]["route"]
        and events[u]["trip"] != events[v]["trip"]
    ]
    assert expected == case["pairs"] and len(expected) >= 6
    reconstructed = []
    for u, v in expected:
        delta = actual[v] - actual[u]
        lower = [b for b in (0, 120, 300, 600) if b <= delta]
        upper = [b - 1 for b in (0, 120, 300, 600) if delta < b]
        reconstructed.append(
            [
                u,
                v,
                max([lows[v - 1] - lows[u - 1] - 299, *lower]),
                min([lows[v - 1] - lows[u - 1] + 299, *upper]),
            ]
        )
    assert archive["bounds"] == reconstructed
    assert archive["targets"] == [[u, v, [0, 180, 420, 720]] for u, v in expected]
    assert proof["labels"] == [
        sum(actual[v] - actual[u] >= b for b in cuts)
        for u, v, cuts in archive["targets"]
    ]
    assert all(actual[i] == value for i, value in proof["disclosed"])
    return actual


def known_can_certify(n, x, alternatives, size):
    requirements = []
    for b in alternatives.values():
        tests = [
            (1 << i | 1 << j) & ~1
            for i, j in combinations(range(n), 2)
            if x[j] - x[i] > b[i][j] or x[i] - x[j] > b[j][i]
        ]
        requirements.append(tests)
    requirements.sort(key=len)
    for t in combinations(range(1, n), size):
        present = sum(1 << i for i in t)
        if all(any(present & edge == edge for edge in r) for r in requirements):
            return True
    return False


def someone_can_certify(n, public_edges, public, allowed, groups, size):
    explored = 0
    for candidate in combinations(range(1, n), size):
        if any(not set(candidate).intersection(row[0]) for row in groups):
            continue
        explored += 1
        points = (0, *candidate)
        constraints = set()
        for b in allowed.values():
            pairs = []
            automatic = False
            for i in points:
                for j in points:
                    cut = b[i][j] + 1
                    if -public[j][i] >= cut:
                        automatic = True
                    if public[i][j] >= cut:
                        pairs.append((j, i, -cut))
            if not automatic:
                constraints.add(tuple(pairs))
        arrange = sorted(constraints, key=lambda sequence: (len(sequence), sequence))

        def same_record(index, edges):
            if index == len(arrange):
                return True
            for option in arrange[index]:
                changed = [*edges, option]
                if potential(n, changed) is not None and same_record(
                    index + 1, changed
                ):
                    return True
            return False

        if same_record(0, public_edges):
            return True, explored
    return False, explored


def audit(source, exports, public, exact_file):
    cases = json.loads(unpack(source))
    packets = json.loads(unpack(exports / "transit-optimality-packets.json.gz"))
    private = json.loads(unpack(exports / "transit-optimality-private-counts.json.gz"))
    events = map(
        json.loads, unpack(public / "public-optimality-ledger.jsonl.gz").splitlines()
    )
    exact = json.loads(exact_file.read_bytes())
    later = {r["job"]: r for r in exact["followup"]}
    tally = Counter()
    for case, packet, secret, event in zip(
        cases, packets, private, events, strict=True
    ):
        assert all(
            case[k] == packet[k] == secret[k] == event[k]
            for k in ("job", "run", "repo")
        )
        actual = packets_match(case, packet)
        n, _, _, d, pub_edges, fibre, alternatives = model(packet)
        repeats = {min(j for j in range(n) if d[i][j] == -d[j][i]) for i in range(1, n)}
        assert repeats
        anchors = {
            min(j for j in range(n) if d[i][j] == -d[j][i])
            for u, v, cuts in packet["archive"]["targets"]
            if any(-d[v][u] < b <= d[u][v] for b in cuts)
            for i in (u, v)
        }
        assert secret["fixed"] == len(anchors - {0})
        assert secret["full"] == n - 1 and secret["targets"] == len(case["pairs"])
        p = event["reads"]
        assert p == secret["optimum"] == len(packet["certificate"]["disclosed"])
        assert p == 0 or not known_can_certify(n, actual, alternatives, p - 1)
        for proof in event["proofs"].values():
            groups_valid(n, fibre, alternatives, proof)
            assert len(proof) <= p
        for rigid in (False, True):
            singles = (
                {i: {i} for i in range(1, n)}
                if not rigid
                else {
                    k: {i for i in range(1, n) if d[k][i] == -d[i][k]}
                    for k in repeats - {0}
                }
            )
            count = sum(
                any(
                    all(
                        fibre[i][j] <= alt[i][j]
                        for i in range(n)
                        for j in range(n)
                        if i not in group and j not in group
                    )
                    for alt in alternatives.values()
                )
                for group in singles.values()
            )
            assert count == len(event["proofs"]["rigid" if rigid else "single"])

        proof = event["proofs"]["groups"]
        if event["shorter"] is not None:
            check_shorter(packet, len(event["shorter"]["disclosed"]), event["shorter"])
        if len(proof) == p:
            tally["certified_by_groups"] += 1
        else:
            f = later.pop(case["job"])
            if f["status"] == "shorter":
                check_shorter(packet, len(f["disclosed"]), f)
                tally["genuine_information_limit"] += 1
            elif f["status"] == "proved_by_search":
                exists, sets = someone_can_certify(
                    n, pub_edges, fibre, alternatives, proof, p - 1
                )
                assert not exists
                tally["additional_exact"] += 1
                tally["independently_excluded_reading_sets"] += sets
            else:
                raise AssertionError("unresolved extra phase")
        tally["jobs"] += 1
        tally["full"] += secret["full"]
        tally["labels"] += secret["targets"]
        tally["fixed"] += secret["fixed"]
        tally["minimum"] += p
        tally["rigid"] += len(event["proofs"]["rigid"])
        tally["rigid_complete"] += bool(p and p == len(event["proofs"]["rigid"]))
        tally["groups"] += len(proof)
        tally["nonempty"] += bool(p)
        tally["branches"] += event["branches"]
        tally["search_capped"] += event["capped"]
    assert not later
    result = json.loads((public / "public-optimality-results.json").read_bytes())[
        "by_source"
    ]["total"]
    assert (
        tally["jobs"] == result["tasks"] and tally["groups"] == result["groups_lower"]
    )
    assert (
        tally["minimum"] == result["revealed"]
        and tally["certified_by_groups"] == result["groups_complete_nonempty"]
    )
    return dict(
        counts=tally,
        gate=tally["jobs"] >= 200
        and 10 * tally["certified_by_groups"] >= 9 * tally["nonempty"]
        and 100 * tally["groups"] >= 95 * tally["minimum"],
    )


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("fixtures", type=Path)
    p.add_argument("manifest", type=Path)
    p.add_argument("exports", type=Path)
    p.add_argument("public", type=Path)
    p.add_argument("exact", type=Path)
    p.add_argument("--gtfs", type=Path)
    a = p.parse_args()
    if not __debug__:
        raise RuntimeError("enable assertions")
    source_matches(a.fixtures, a.manifest, a.gtfs)
    print(json.dumps(audit(a.fixtures, a.exports, a.public, a.exact), indent=2))
