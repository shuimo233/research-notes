"""Independently verify public proofs using raw constraints and explicit finite worlds."""

import argparse
from collections import Counter, defaultdict
import gzip
from itertools import combinations, product
import json
from pathlib import Path
from random import Random
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from slack_certificate_check import attach, potential, problem


def raw(packet):
    archive, cert = packet["archive"], packet["certificate"]
    n = len(archive["bands"]) + 1
    edges = []
    for u, (lo, hi) in enumerate(archive["bands"], 1):
        edges.extend(((0, u, hi), (u, 0, -lo)))
    for u, v, lo, hi in archive["bounds"]:
        edges.extend(((u, v, hi), (v, u, -lo)))
    cuts = set()
    for (u, v, thresholds), label in zip(
        archive["targets"], cert["labels"], strict=True
    ):
        assert 0 <= label <= len(thresholds)
        if label:
            cuts.add((v, u, -thresholds[label - 1]))
        if label < len(thresholds):
            cuts.add((u, v, thresholds[label] - 1))
    return n, edges, cuts


def distances(n, edges):
    if potential(n, edges) is None:
        return None
    return [potential(n, edges, i) for i in range(n)]


def model(packet):
    n, edges, bounds = raw(packet)
    d = distances(n, edges)
    fibre_edges = attach(edges, packet["certificate"]["disclosed"])
    f = distances(n, fibre_edges)
    assert d is not None and f is not None
    possible = {}
    for u, v, limit in sorted(bounds):
        assert f[u][v] <= limit
        violation = distances(n, [*edges, (v, u, -limit - 1)])
        if violation is not None:
            possible[(u, v, limit)] = violation
    return n, edges, bounds, d, fibre_edges, f, possible


def groups_valid(n, f, alternatives, proof):
    used = set()
    for members, bound in proof:
        assert (
            members
            and len(members) == len(set(members))
            and min(members) >= 1
            and max(members) < n
        )
        assert not used.intersection(members)
        alt = alternatives[tuple(bound)]
        assert all(
            f[i][j] <= alt[i][j]
            for i in range(n)
            if i not in members
            for j in range(n)
            if j not in members
        )
        used.update(members)


def check_shorter(packet, novel, generated):
    n, edges, bounds = raw(packet)
    original = packet["certificate"]["disclosed"]
    values, selected = generated["record"], generated["disclosed"]
    assert len(selected) == novel < len(original)
    assert len(values) == n and values[0] == 0
    assert all(type(value) is int for value in values)
    assert all(values[j] - values[i] <= t for i, j, t in edges)
    assert all(values[i] == value for i, value in (*original, *selected))
    assert len({i for i, _ in selected}) == len(selected)
    for u, v, t in bounds:
        assert potential(n, attach(edges, selected), u)[v] <= t


def complete(n, d, fibre_edges, f, alternatives, proof):
    """Independently exhaust the final one-read gap using raw Bellman–Ford."""
    choices = []
    for members, _ in proof:
        selected = []
        for i in members:
            if all(d[u][i] > -d[i][u] for u in selected):
                selected.append(i)
        choices.append(selected)

    tested = 0
    for points in product(*choices):
        tested += 1
        hits = []
        vertices = (0, *points)
        for b in alternatives.values():
            options = []
            for j in vertices:
                for i in vertices:
                    if f[j][i] > b[j][i]:
                        # Exclude the violating B projection by making x[i]-x[j] too large.
                        options.append((i, j, -b[j][i] - 1))
            hits.append(options)
        hits.sort(key=len)

        def extend(index, edges):
            if index == len(hits):
                return True
            return any(
                potential(n, [*edges, c]) is not None and extend(index + 1, [*edges, c])
                for c in hits[index]
            )

        if extend(0, fibre_edges):
            return True, tested
    return False, tested


def read_compressed(path):
    return gzip.decompress(path.read_bytes())


def check(packet_file, result_folder, exact_file):
    packets = json.loads(read_compressed(packet_file))
    ledger = map(
        json.loads,
        read_compressed(
            result_folder / "public-optimality-ledger.jsonl.gz"
        ).splitlines(),
    )
    exact = json.loads(exact_file.read_bytes())
    expected = {r["job"]: r for r in exact["cases"]}
    tally = defaultdict(Counter)
    final = Counter()
    for packet, event in zip(packets, ledger, strict=True):
        assert all(event[k] == packet[k] for k in ("repo", "run", "job"))
        disclosed = packet["certificate"]["disclosed"]
        n, _, _, d, f_edges, f, alternatives = model(packet)
        p = event["reads"]
        assert len(disclosed) == p and len({i for i, _ in disclosed}) == p
        proofs = event["proofs"]
        for proof in proofs.values():
            groups_valid(n, f, alternatives, proof)
            assert len(proof) <= p
        original = [min(j for j in range(n) if d[i][j] == -d[j][i]) for i in range(n)]

        def baseline(points):
            count = 0
            for i in set(points) - {0}:
                group = {j for j, q in enumerate(points) if q == i}
                for alt in alternatives.values():
                    if all(
                        f[u][v] <= alt[u][v]
                        for u, v in product(range(n), repeat=2)
                        if u not in group and v not in group
                    ):
                        count += 1
                        break
            return count

        assert len(proofs["single"]) == baseline(list(range(n)))
        assert len(proofs["rigid"]) == baseline(original)
        contenders = proofs["groups"]
        if len(contenders) == p:
            final["packing_proved"] += 1
        else:
            followup = expected.pop(packet["job"])
            assert (
                followup["run"] == packet["run"] and followup["repo"] == packet["repo"]
            )
            assert p == len(contenders) + 1
            exists, sets = complete(n, d, f_edges, f, alternatives, contenders)
            final["independent_sets"] += sets
            if followup["status"] == "shorter":
                assert exists
                check_shorter(packet, p - 1, followup)
                final["actual_information_gap"] += 1
            elif followup["status"] == "proven":
                assert not exists
                final["exact_followup_proved"] += 1
            else:
                raise AssertionError("a follow-up case was not resolved")
        if event["shorter"] is not None:
            check_shorter(packet, len(event["shorter"]["disclosed"]), event["shorter"])
        for key in ("total", packet["repo"]):
            c = tally[key]
            c["tasks"] += 1
            c["revealed"] += p
            c["nonempty"] += bool(p)
            c["branches"] += event["branches"]
            c["capped"] += event["capped"]
            c["max_branches"] = max(c["max_branches"], event["branches"])
            c["shorter_exists"] += event["shorter"] is not None
            c["stronger_than_rigid"] += len(contenders) > len(proofs["rigid"])
            for name, proof in proofs.items():
                c[name + "_lower"] += len(proof)
                c[name + "_complete_nonempty"] += bool(p and len(proof) == p)
    assert not expected
    results = json.loads(
        (result_folder / "public-optimality-results.json").read_bytes()
    )
    assert tally == results["by_source"]
    assert exact["totals"] == {
        "proven": final["exact_followup_proved"],
        "shorter": final["actual_information_gap"],
    }
    t = tally["total"]
    gates = {
        "count": t["tasks"] >= 400,
        "fully_public": t["groups_complete_nonempty"] / t["nonempty"] >= 0.9,
        "public_lower": t["groups_lower"] / t["revealed"] >= 0.95,
    }
    assert gates == results["gates"] and all(gates.values()) == results["gate"]
    return dict(tasks=len(packets), groups=t["groups_lower"], **final)


def export_matches(packets, fixtures, old_ledger):
    exported = json.loads(read_compressed(packets))
    source = json.loads(read_compressed(fixtures))
    ledger = map(json.loads, read_compressed(old_ledger).splitlines())
    for public, original, report in zip(exported, source, ledger, strict=True):
        assert all(
            public[k] == original[k] == report[k] for k in ("repo", "run", "job")
        )
        x, archive, _, answer, targets = problem(original)
        n, edges, _ = raw(public)
        assert n == len(x) and distances(n, edges) == distances(n, archive)
        assert public["archive"]["targets"] == [
            [u, v, list(cuts)] for u, v, cuts in targets
        ]
        pub = public["certificate"]
        assert pub["labels"] == answer == report["labels"]
        assert pub["disclosed"] == [[i, x[i]] for i in report["paths"]["optimum"]]


def synthetic():
    from conclusion_replay_inquiry import parse
    from public_optimality import PublicAudit, disjoint_covers, solve_2sat
    from public_optimality_exact import close_gap

    rng = Random(190975)
    totals = Counter()
    for _ in range(300):
        n = rng.randint(1, 6)
        p = [
            (
                rng.choice((-1, 1)) * rng.randint(1, n),
                rng.choice((-1, 1)) * rng.randint(1, n),
            )
            for _ in range(rng.randrange(16))
        ]
        result = solve_2sat(n, p)

        def meets(x):
            return all(any(x[abs(l) - 1] == (l > 0) for l in clause) for clause in p)

        exists = any(meets(x) for x in product((False, True), repeat=n))
        assert exists == (result is not None) and (result is None or meets(result))
        totals["sat_formulas"] += 1

    for _ in range(200):
        n = rng.randint(2, 5)
        x = (0, *(rng.randrange(4) for _ in range(n)))
        pairs = list(combinations(range(n + 1), 2))
        bounds = []
        for u, v in pairs:
            diff = x[v] - x[u]
            if rng.random() < 0.5:
                bounds.append((u, v, diff - rng.randrange(3), diff + rng.randrange(3)))
        worlds = [
            w
            for w in ((0, *rest) for rest in product(range(4), repeat=n))
            if all(lo <= w[v] - w[u] <= hi for u, v, lo, hi in bounds)
        ]
        targets = [
            (u, v, sorted(rng.sample(range(-3, 4), 2)))
            for u, v in pairs
            if rng.random() < 0.35
        ]
        label = [sum(x[v] - x[u] >= h for h in c) for u, v, c in targets]

        def output(w):
            return [sum(w[v] - w[u] >= h for h in c) for u, v, c in targets]

        def minimal(actual):
            return next(
                k
                for k in range(n + 1)
                if any(
                    not any(
                        output(w) != label and all(w[i] == actual[i] for i in s)
                        for w in worlds
                    )
                    for s in combinations(range(1, n + 1), k)
                )
            )

        fixed = list(range(1, n + 1))
        for i in reversed(fixed[:]):
            smaller = [j for j in fixed if i != j]
            if all(
                output(w) == label for w in worlds if all(w[j] == x[j] for j in smaller)
            ):
                fixed = smaller
        compatible = [w for w in worlds if all(w[i] == x[i] for i in fixed)]
        packet = dict(
            archive=dict(bands=[[0, 3]] * n, bounds=bounds, targets=targets),
            certificate=dict(labels=label, disclosed=[[i, x[i]] for i in fixed]),
        )
        audit = PublicAudit(*parse(packet["archive"]), packet["certificate"])
        for u, v, b in raw(packet)[2]:
            bad = [w for w in worlds if w[v] - w[u] > b]
            assert bool(bad) == ((u, v, b) in audit.alternatives)
            if not bad:
                continue
            for mask in range(0, 1 << (n + 1), 2):
                outside = [i for i in range(1, n + 1) if not (mask >> i) & 1]
                projected = {tuple(w[i] for i in outside) for w in bad}
                literal = all(
                    tuple(w[i] for i in outside) in projected for w in compatible
                )
                result = all(mask & e for e in audit.alternatives[u, v, b])
                assert literal == result
                totals["group_conditions"] += 1
        proof, _, capped = audit.pack(audit.baseline(rigid=True))
        assert not capped and audit.check(proof) <= min(minimal(v) for v in compatible)
        follow = close_gap(audit, proof)
        if follow["status"] == "proven":
            assert min(minimal(v) for v in compatible) == len(fixed)
        elif follow["status"] == "shorter":
            check_shorter(packet, len(follow["disclosed"]), follow)
        totals["networks"] += 1

    examples = [
        dict(
            archive=dict(
                bands=[[0, 1]] * 3,
                bounds=[[1, 2, -1, 0], [1, 3, -1, 0]],
                targets=[[0, 2, [1]], [0, 3, [1]]],
            ),
            certificate=dict(labels=[0, 0], disclosed=[[2, 0], [3, 0]]),
        ),
        dict(
            archive=dict(
                bands=[[-2, 2]] * 3,
                bounds=[[1, 2, 0, 1], [2, 3, 0, 1]],
                targets=[[1, 3, [2]]],
            ),
            certificate=dict(labels=[0], disclosed=[[1, 0], [3, 0]]),
        ),
    ]
    for packet, status in zip(examples, ("shorter", "proven"), strict=True):
        audit = PublicAudit(*parse(packet["archive"]), packet["certificate"])
        baseline, _, _ = audit.pack([])
        assert len(baseline) == 1 and close_gap(audit, baseline)["status"] == status
        for bad in (
            [*baseline, *baseline],
            [[[0], baseline[0][1]]],
            [[[1], [0, 0, 0]]],
        ):
            try:
                audit.check(bad)
            except ValueError:
                pass
            else:
                raise AssertionError("corrupt proof accepted")
    impossible = PublicAudit(
        *parse(dict(bands=[[0, 0]], bounds=[], targets=[[0, 1, [1]]])),
        dict(labels=[0], disclosed=[]),
    )
    try:
        impossible.check([[[1], [0, 1, 0]]])
    except ValueError:
        pass
    else:
        raise AssertionError("empty counterfactual accepted")
    bogus = dict(examples[0]["certificate"], labels=[1, 0])
    try:
        PublicAudit(*parse(examples[0]["archive"]), bogus)
    except ValueError:
        pass
    else:
        raise AssertionError("a false report was accepted")
    assert (
        disjoint_covers(((1, (0, 1, 0), (1 << 3,)), (2, (0, 2, 0), (1 << 3,)))) is None
    )
    return dict(totals, triangle_gap=True, information_gap=True)


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("packets", type=Path)
    p.add_argument("results", type=Path)
    p.add_argument("exact", type=Path)
    p.add_argument("--export-sources", type=Path, nargs=2)
    a = p.parse_args()
    if not __debug__:
        raise RuntimeError("enable assertions")
    if a.export_sources:
        export_matches(a.packets, *a.export_sources)
    print(
        json.dumps(
            dict(replay=check(a.packets, a.results, a.exact), synthetic=synthetic()),
            indent=2,
        )
    )
