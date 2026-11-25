"""Produce exact certificates for every observation window of three truthful releases."""

import argparse
from collections import Counter, defaultdict
from fractions import Fraction as F
import gzip
from hashlib import sha1
from itertools import permutations
import json
from pathlib import Path

from multi_odds import HALF, subsets
from retuned_odds import binary_pair_policy
from retuned_odds_ci import select
from retuned_odds_run import check_linear
from selection_odds import patterns
from selection_odds_run import rational

SOURCES = {
    "CI": "38632c54456c76ff237bb8bf4cf66257ed6041e7",
    "BART": "86a0e219b9f4d262b3980d1ae75ab44c903ce92b",
}
TARGETS = tuple((str(r), locked) for r in (F(32, 7), F(5)) for locked in (False, True))
PAIRS = (3, 5, 6)


def read(path, domain):
    raw = path.read_bytes()
    if sha1(f"blob {len(raw)}\0".encode() + raw).hexdigest() != SOURCES[domain]:
        raise ValueError("not a registered archive")
    sort = sorted(
        json.loads(gzip.decompress(raw)),
        key=lambda p: (p["repo"], int(p["run"]), int(p["job"])),
    )
    count = Counter()
    for p in sort:
        key = p["repo"] if domain == "CI" else domain
        count[key] += 1
        if count[key] <= (18 if domain == "CI" else 108):
            yield p


def caps(modes):
    limits = {}
    for window in PAIRS:
        first = window & -window
        second = window ^ first
        proj = {(int(bool(s & first)), int(bool(s & second))) for s in modes}
        limits[window] = binary_pair_policy(proj)[0]
    return limits


def constraints(modes, ratio, limit):
    S = {s: subsets(s) for s in modes}
    for s, replies in S.items():
        for sign in (-1, 1):
            yield ("mass", s, sign), {(s, a): sign for a in replies}, F(sign)
            for bit in (1, 2, 4):
                if s & bit:
                    yield (
                        ("service", s, bit, sign),
                        {(s, a): sign for a in replies if a & bit},
                        HALF * sign,
                    )
        for a in replies:
            yield ("floor", s, a), {(s, a): 1}, F(1, 2 ** (s.bit_count() + 1))

    for win in range(1, 8):
        cap = min(ratio, limit.get(win, ratio))
        if win.bit_count() == 1:
            continue
        for answer in subsets(win):
            eligible = [s for s in modes if s & answer == answer]
            for s, z in permutations(eligible, 2):
                left = {(s, a): cap for a in S[s] if a & win == answer}
                right = {(z, a): -1 for a in S[z] if a & win == answer}
                yield ("odds", win, answer, s, z), left | right, F(0)


def solve(modes, ratio, limits):
    from scipy import __version__
    from scipy.optimize import linprog
    from scipy.sparse import coo_matrix

    if __version__ != "1.16.3":
        raise RuntimeError("this replay pins scipy 1.16.3")
    rows = list(constraints(modes, ratio, limits))
    names = [(s, a) for s in modes for a in subsets(s)]
    positions = {k: i for i, k in enumerate(names)}
    rowlist, cols, values = [], [], []
    for i, (_, form, _) in enumerate(rows):
        for key, x in form.items():
            rowlist.append(i)
            cols.append(positions[key])
            values.append(-float(x))
        rowlist.append(i)
        cols.append(len(names))
        values.append(-1.0)
    mat = coo_matrix(
        (values, (rowlist, cols)), shape=(len(rows), len(names) + 1)
    ).tocsr()
    result = linprog(
        [0] * len(names) + [1],
        A_ub=mat,
        b_ub=[-float(b) for _, _, b in rows],
        method="highs",
    )
    if not result.success:
        raise ArithmeticError(result.message)
    if rational(result.fun) > 0:
        dual = [-rational(x) for x in result.ineqlin.marginals]
        if not check_linear(rows, None, dual):
            raise ArithmeticError("could not recover a rational contradiction")
        return dict(
            status="infeasible",
            certificate=[
                [key, str(p)] for (key, _, _), p in zip(rows, dual, strict=True) if p
            ],
        )
    values = dict(zip(names, map(rational, result.x[:-1]), strict=True))
    if min(values.values()) < 0 or any(
        sum(values[j] * a for j, a in form.items()) < b for _, form, b in rows
    ):
        raise ArithmeticError("could not recover a rational feasible table")
    return dict(
        status="feasible", rows=[[str(values[s, a]) for a in subsets(s)] for s in modes]
    )


def evaluate(domain, p, cache):
    labels, fibre = select(p, limit=3)
    identity = {k: p[k] for k in ("repo", "run", "job")}
    if len(labels) != 3:
        return dict(domain=domain, **identity, status="fewer_than_three", labels=labels)
    masks, empty, _ = patterns(fibre, labels)
    assert empty
    modes = (0, *masks)
    if modes not in cache:
        pair = caps(modes)
        targets = [
            dict(ratio=r, lock=locked, **solve(modes, F(r), pair if locked else {}))
            for r, locked in TARGETS
        ]
        cache[modes] = dict(
            modes=modes, pair={k: str(x) for k, x in pair.items()}, targets=targets
        )
    return dict(
        domain=domain, **identity, status="scored", labels=labels, **cache[modes]
    )


def summarize(rows):
    counters = defaultdict(Counter)
    layouts = defaultdict(set)
    for row in rows:
        k = row["domain"]
        for group in ("all", k):
            c = counters[group]
            c["sampled"] += 1
            if row["status"] != "scored":
                continue
            c["scored"] += 1
            layout = tuple(row["modes"])
            layouts[group].add(layout)
            c["full_cube"] += len(layout) == 8
            c["targets"] += len(row["targets"])
            a, b, free5, locked5 = [x["status"] == "feasible" for x in row["targets"]]
            c["free_at_base"] += a
            c["locked_at_base"] += b
            c["free_at_five"] += free5
            c["locked_at_five"] += locked5
            c["tradeoff"] += a and not b
            c["tradeoff_recovers_at_five"] += a and not b and locked5
    summaries = {k: dict(v, mode_families=len(layouts[k])) for k, v in counters.items()}
    return dict(
        results=summaries,
        gate=summaries["all"]["scored"] >= 40 and summaries["all"]["tradeoff"] >= 10,
    )


def run(ci, bart, out):
    cache = {}
    records = [
        evaluate(domain, p, cache)
        for domain, path in (("CI", ci), ("BART", bart))
        for p in read(path, domain)
    ]
    summary = summarize(records)
    out.mkdir(parents=True, exist_ok=True)
    (out / "multi-odds-policies.json.gz").write_bytes(
        gzip.compress(
            json.dumps(records, separators=(",", ":"), ensure_ascii=True).encode(),
            mtime=0,
        )
    )
    (out / "multi-odds-results.json").write_text(
        json.dumps(summary, indent=2) + "\n", encoding="utf-8", newline="\n"
    )
    print(json.dumps(summary))


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("ci", type=Path)
    p.add_argument("bart", type=Path)
    p.add_argument("output", type=Path)
    a = p.parse_args()
    run(a.ci, a.bart, a.output)
