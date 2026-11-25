"""Independently audit three-request truth patterns, odds bounds, and certificates."""

import argparse
from collections import defaultdict
from fractions import Fraction as F
import gzip
from hashlib import sha1
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from public_optimality_check import model
from selection_odds_check import independent_patterns
from slack_certificate_check import potential

PINS = {
    "CI": "38632c54456c76ff237bb8bf4cf66257ed6041e7",
    "BART": "86a0e219b9f4d262b3980d1ae75ab44c903ce92b",
}


def sample(path, kind):
    content = path.read_bytes()
    assert sha1(f"blob {len(content)}\0".encode() + content).hexdigest() == PINS[kind]
    archives = defaultdict(list)
    for p in json.loads(gzip.decompress(content)):
        archives[p["repo"] if kind == "CI" else "all"].append(p)
    for group in sorted(archives):
        by_id = sorted(
            archives[group], key=lambda p: (p["repo"], int(p["run"]), int(p["job"]))
        )
        for p in by_id[: 18 if kind == "CI" else 108]:
            yield p | {"domain": kind}


def selection(packet):
    n, _, _, _, base, d, _ = model(packet)
    chosen = []
    keep = []
    for i, j in sorted({tuple(x[:2]) for x in packet["archive"]["targets"]}):
        assert -d[j][i] <= d[i][j]
        if -d[j][i] == d[i][j]:
            continue
        cut = (d[i][j] - d[j][i] + 1) // 2
        false = (i, j, cut - 1)
        if potential(n, [*base, *keep, false]) is not None:
            chosen.append([i, j, cut])
            keep.append(false)
            if len(chosen) == 3:
                break
    return n, base, chosen


def allowed(modes):
    return {s: [a for a in range(8) if a & ~s == 0] for s in modes}


def pair_minima(modes):
    lower = {}
    for w in (3, 5, 6):
        states = {s & w for s in modes}
        lower[w] = F(2) if w not in states else F(8, 3) if len(states) == 2 else F(3)
    return lower


def view_cap(w, ratio, locks):
    return F(2) if w.bit_count() == 1 else min(ratio, locks.get(w, ratio))


def verify_policy(modes, packed, ratio, locks):
    book = {}
    for (x, A), line in zip(allowed(modes).items(), packed, strict=True):
        probabilities = dict(zip(A, map(F, line), strict=True))
        assert all(p >= F(1, 2 ** (x.bit_count() + 1)) for p in probabilities.values())
        assert sum(probabilities.values()) == 1
        for bit in (1, 2, 4):
            if x & bit:
                assert sum(p for a, p in probabilities.items() if a & bit) == F(1, 2)
        book[x] = probabilities
    worst = {}
    for w in range(1, 8):
        by_message = defaultdict(list)
        for row in book.values():
            levels = defaultdict(F)
            for a, p in row.items():
                levels[a & w] += p
            for message, probability in levels.items():
                by_message[message].append(probability)
        worst[w] = max(max(ps) / min(ps) for ps in by_message.values())
        assert worst[w] <= view_cap(w, ratio, locks)
    return worst


def verify_negative(modes, proof, ratio, locks):
    forms = allowed(modes)
    coeff = defaultdict(F)
    rhs = F(0)
    seen = set()
    for tag, raw in proof:
        assert tuple(tag) not in seen and all(type(i) is int for i in tag[1:])
        seen.add(tuple(tag))
        p = F(raw)
        assert p > 0
        if tag[0] == "floor":
            _, x, a = tag
            assert a in forms[x]
            coeff[x, a] += p
            rhs += p * F(1, 2 ** (x.bit_count() + 1))
        elif tag[0] == "mass":
            _, x, sign = tag
            assert sign in (-1, 1)
            for a in forms[x]:
                coeff[x, a] += p * sign
            rhs += p * sign
        elif tag[0] == "service":
            _, x, bit, sign = tag
            assert sign in (-1, 1) and bit in (1, 2, 4) and x & bit
            for a in forms[x]:
                if a & bit:
                    coeff[x, a] += p * sign
            rhs += p * sign / 2
        else:
            assert tag[0] == "odds"
            _, w, out, x, y = tag
            assert (
                1 <= w <= 7
                and x != y
                and out in forms[x]
                and out in forms[y]
                and out & ~w == 0
            )
            for s, k in ((x, p * view_cap(w, ratio, locks)), (y, -p)):
                for a in forms[s]:
                    if a & w == out:
                        coeff[s, a] += k
    assert rhs > 0 and all(v <= 0 for v in coeff.values())


def check_case(packet, row):
    assert all(row[k] == packet[k] for k in ("domain", "repo", "run", "job"))
    n, edges, labels = selection(packet)
    assert row["labels"] == labels
    if len(labels) < 3:
        assert row["status"] == "fewer_than_three"
        return None
    assert row["status"] == "scored"
    modes = independent_patterns(n, edges, [{"comparison": label} for label in labels])
    assert modes[0] == 0 and row["modes"] == modes
    caps = pair_minima(modes)
    assert caps == {int(k): F(v) for k, v in row["pair"].items()}
    decisions = []
    variants = [(r, lock) for r in (F(32, 7), F(5)) for lock in (False, True)]
    for target, (r, l) in zip(row["targets"], variants, strict=True):
        assert F(target["ratio"]) == r and target["lock"] is l
        locks = caps if l else {}
        if target["status"] == "feasible":
            verify_policy(modes, target["rows"], r, locks)
            decisions.append(True)
        else:
            assert target["status"] == "infeasible"
            verify_negative(modes, target["certificate"], r, locks)
            decisions.append(False)
    return tuple(modes), decisions


def check(ci, bart, out):
    fresh = iter([*sample(ci, "CI"), *sample(bart, "BART")])
    data = json.loads(
        gzip.decompress((out / "multi-odds-policies.json.gz").read_bytes())
    )
    report = json.loads((out / "multi-odds-results.json").read_bytes())
    scored = defaultdict(list)
    groups = defaultdict(int)
    for p, r in zip(fresh, data, strict=True):
        kind = p["domain"]
        verdict = check_case(p, r)
        for k in ("all", kind):
            groups[k] += 1
            if verdict is not None:
                scored[k].append(verdict)
    tables = {}
    for k, n in groups.items():
        verified = scored[k]
        d = [x for _, x in verified]
        classify = [a and not b for a, b, _, _ in d]
        tables[k] = dict(
            sampled=n,
            scored=len(verified),
            full_cube=sum(len(m) == 8 for m, _ in verified),
            targets=sum(len(x) for x in d),
            free_at_base=sum(x[0] for x in d),
            locked_at_base=sum(x[1] for x in d),
            free_at_five=sum(x[2] for x in d),
            locked_at_five=sum(x[3] for x in d),
            tradeoff=sum(classify),
            tradeoff_recovers_at_five=sum(
                t and x[3] for t, x in zip(classify, d, strict=True)
            ),
            mode_families=len({m for m, _ in verified}),
        )
    gate = tables["all"]["scored"] >= 40 and tables["all"]["tradeoff"] >= 10
    assert report == dict(results=tables, gate=gate)
    return report | {"verified": True}


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("ci", type=Path)
    p.add_argument("bart", type=Path)
    p.add_argument("output", type=Path)
    a = p.parse_args()
    if not __debug__:
        raise RuntimeError("enable assertions")
    print(json.dumps(check(a.ci, a.bart, a.output)))
