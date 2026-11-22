"""Standalone integer checker for fixed-plan action claims. Uses only the standard library."""

import argparse
from dataclasses import asdict, dataclass
import hashlib
from itertools import combinations
import json
from pathlib import Path


def fingerprint(problem):
    encoded = json.dumps(problem, sort_keys=True, ensure_ascii=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(encoded.encode("ascii")).hexdigest()


@dataclass(frozen=True)
class Verification:
    status: str
    detail: str
    nodes: int


class _Limit(Exception):
    pass


def _check(ok, message):
    if not ok:
        raise ValueError(message)


def _keys(obj, names):
    _check(isinstance(obj, dict) and set(obj) == set(names), "missing or unexpected fields")


def _natural(x):
    return type(x) is int and x >= 0


def _count(text):
    _check(isinstance(text, str) and text.isascii() and text.isdecimal()
           and (text == "0" or not text.startswith("0")), "expected a canonical unsigned decimal string")
    return int(text)


def _strings(values):
    return isinstance(values, list) and all(isinstance(x, str) and x for x in values)


def _read_problem(problem):
    _keys(problem, ("format", "domain", "probes", "rules"))
    _check(problem["format"] == "stateful-id/audit-1", "unknown problem format")
    _check(isinstance(problem["domain"], str) and problem["domain"], "invalid domain")
    _check(isinstance(problem["probes"], list), "invalid probes")
    traces, counts = set(), []
    for probe in problem["probes"]:
        _keys(probe, ("trace", "count"))
        _check(_strings(probe["trace"]), "invalid probe")
        trace = tuple(probe["trace"])
        _check(trace not in traces, "duplicate probe")
        traces.add(trace)
        counts.append(_count(probe["count"]))
    rules = problem["rules"]
    _check(isinstance(rules, list) and rules, "invalid rule list")
    by_name = {}
    for row in rules:
        _keys(row, ("name", "bits", "errors", "actions"))
        name = row["name"]
        _check(isinstance(name, str) and name and name not in by_name, "invalid or duplicate rule name")
        _check(isinstance(row["bits"], list) and len(row["bits"]) == len(counts)
               and all(type(b) is int and b in (0, 1) for b in row["bits"]), "invalid predictions or error budget")
        actions = row["actions"]
        _check(_strings(actions) and actions and len(set(actions)) == len(actions), "invalid actions")
        by_name[name] = {**row, "errors": _count(row["errors"])}
    return counts, by_name


def _overlap(rows, counts, charge, hints=()):
    """Solve raw integer count inequalities without the planner's graph or intersection code."""
    if not rows:
        return True
    # A constant prediction can always be matched in full by a common transcript.
    used = [i for i,n in enumerate(counts) if n and any(r["bits"][i] != rows[0]["bits"][i] for r in rows)]
    upper = [counts[i] for i in used]
    lower = [0]*len(upper)
    inequalities = {}
    named = {}
    for row in rows:
        signs = tuple(1 - 2 * row["bits"][i] for i in used)
        rhs = row["errors"] - sum(counts[i] for i in used if row["bits"][i])
        named[row["name"]] = (signs, rhs)
        inequalities[signs] = min(rhs, inequalities.get(signs, rhs))
    # Recompute every suggested sum directly from the selected original rows.
    for names in hints:
        if not all(name in named for name in names):
            continue
        terms = [named[name] for name in names]
        rhs = sum(value for _, value in terms)
        support = [(j, sum(col)) for j,col in enumerate(zip(*(normal for normal,_ in terms))) if sum(col)]
        if not support and rhs < 0:
            return False
        if len(support) == 1:
            j, a = support[0]
            if a > 0:
                upper[j] = min(upper[j], rhs // a)
            else:
                lower[j] = max(lower[j], -((-rhs) // a))
            if lower[j] > upper[j]:
                return False
    # Half the sum of two sign rows has integral coefficients. Round its RHS down.
    # This shortcut is optional; wider cores still use exact box search.
    if len(inequalities) <= 16:
        for (a,b), (c,d) in combinations(list(inequalities.items()), 2):
            normal = tuple((x+y)//2 for x,y in zip(a,c))
            rhs = (b+d)//2
            inequalities[normal] = min(rhs, inequalities.get(normal, rhs))
    pending = [(lower, upper)]
    while pending:
        charge()
        lo, hi = pending.pop()
        # Each tightening is necessary throughout the current box. One pass suffices
        # for correctness; further deductions can be made in child boxes.
        for normal, rhs in inequalities.items():
            slack = rhs - sum(l if a == 1 else -h if a == -1 else 0
                              for a,l,h in zip(normal,lo,hi))
            if slack < 0:
                break
            for j, a in enumerate(normal):
                if a == 1:
                    hi[j] = min(hi[j], lo[j] + slack)
                elif a == -1:
                    lo[j] = max(lo[j], hi[j] - slack)
        else:
            middle = [(l+h)//2 for l,h in zip(lo,hi)]
            if all(sum(a*z for a,z in zip(normal,middle)) <= rhs for normal,rhs in inequalities.items()):
                return True
            j = max(range(len(lo)), key=lambda k: hi[k]-lo[k], default=None)
            if j is not None and lo[j] < hi[j]:
                lower_hi, upper_lo = hi.copy(), lo.copy()
                lower_hi[j], upper_lo[j] = middle[j], middle[j]+1
                pending.append((upper_lo, hi))
                pending.append((lo, lower_hi))
    return False


def _coverage(by_name, cores, charge):
    # For each available action, a bad set must contain at least one row denying it.
    actions = set().union(*(r["actions"] for r in by_name.values()))
    rejectors = sorted((tuple(name for name,r in by_name.items() if a not in r["actions"])
                        for a in sorted(actions)), key=len)
    pending = [frozenset()]
    while pending:
        charge()
        selected = pending.pop()
        if any(core <= selected for core in cores):
            continue
        for rejected_by in rejectors:
            if selected.isdisjoint(rejected_by):
                pending.extend(selected | {name} for name in rejected_by)
                break
        else:
            raise ValueError("cores leave incompatible actions uncovered")


def verify(problem, claim, *, max_nodes=100_000, require_minimal=False):
    """Check a claim against an independently trusted problem. Return verified/rejected/inconclusive."""
    nodes = 0

    def charge():
        nonlocal nodes
        if nodes >= max_nodes:
            raise _Limit
        nodes += 1

    try:
        _check(_natural(max_nodes), "invalid node limit")
        counts, by_name = _read_problem(problem)
        _check(isinstance(claim, dict) and type(claim.get("guaranteed")) is bool, "invalid verdict")
        ok = claim["guaranteed"]
        minimal = claim.get("minimal", True)
        fields = ["problem_sha256", "guaranteed", "cores" if ok else "ones"]
        if ok and "minimal" in claim:
            _check(type(minimal) is bool, "invalid minimality flag")
            fields.append("minimal")
        _check(not (ok and require_minimal and not minimal), "minimum verification scope requires deletion checks")
        if ok and "row_sums" in claim:
            fields.append("row_sums")
        _keys(claim, fields)
        _check(claim["problem_sha256"] == fingerprint(problem), "claim refers to a different problem")
        if ok:
            _check(isinstance(claim["cores"], list), "invalid cores")
            hints = claim.get("row_sums", [])
            _check(isinstance(hints, list) and all(_strings(g) and 1 <= len(g) <= 4
                   and set(g) <= by_name.keys() for g in hints), "invalid row sum")
            cores = set()
            for names in claim["cores"]:
                _check(_strings(names) and names and len(set(names)) == len(names)
                       and set(names) <= by_name.keys(), "invalid core rows")
                core = frozenset(names)
                if core in cores:
                    continue
                rows = [by_name[name] for name in names]
                _check(not _overlap(rows, counts, charge, hints), "claimed core has a common record")
                if minimal:
                    for j in range(len(rows)):
                        _check(_overlap(rows[:j]+rows[j+1:], counts, charge, hints), "claimed core contains a redundant row")
                cores.add(core)
            _coverage(by_name, cores, charge)
        else:
            _check(isinstance(claim["ones"], list) and len(claim["ones"]) == len(counts), "invalid transcript counts")
            ones = [_count(z) for z in claim["ones"]]
            _check(all(z <= n for z,n in zip(ones,counts)), "invalid transcript counts")
            live = [set(r["actions"]) for r in by_name.values()
                    if sum(n-z if b else z for b,n,z in zip(r["bits"],counts,ones)) <= r["errors"]]
            _check(live and not set.intersection(*live), "transcript does not leave incompatible actions")
    except ValueError as error:
        return Verification("rejected", str(error), nodes)
    except _Limit:
        return Verification("inconclusive", "search node limit reached", nodes)
    if not ok:
        return Verification("verified", "ambiguous transcript checked", nodes)
    return Verification("verified", "guarantee and minimal cores checked" if minimal else "guarantee only checked", nodes)


def _unique_object(pairs):
    obj = dict(pairs)
    _check(len(obj) == len(pairs), "duplicate JSON key")
    return obj


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("problem", type=Path)
    parser.add_argument("claim", type=Path)
    parser.add_argument("--max-nodes", type=int, default=100_000)
    parser.add_argument("--require-minimal", action="store_true", help="require deletion checks on guaranteed claims")
    args = parser.parse_args()
    try:
        problem, claim = [json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=_unique_object)
                          for path in (args.problem, args.claim)]
        result = verify(problem, claim, max_nodes=args.max_nodes, require_minimal=args.require_minimal)
    except (OSError, ValueError, RecursionError) as error:
        result = Verification("rejected", str(error), 0)
    print(json.dumps(asdict(result), ensure_ascii=True))
    return {"verified": 0, "rejected": 1, "inconclusive": 2}[result.status]


if __name__ == "__main__":
    raise SystemExit(main())
