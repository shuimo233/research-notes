"""Decide an all-zero claim under a global budget of faulty evidence sources."""

import argparse
from dataclasses import dataclass
from functools import lru_cache
import json
from pathlib import Path


def fields(obj, *keys):
    if not isinstance(obj, dict) or set(obj) != set(keys):
        raise ValueError(f"expected fields {keys}")


def name(value):
    if not isinstance(value, str) or not value:
        raise ValueError("names must be nonempty strings")
    return value


def number(value):
    if type(value) is not int or value < 0:
        raise ValueError("cost and fault_budget must be nonnegative integers")
    return value


def bit(value):
    if type(value) not in (int, bool) or value not in (0, 1):
        raise ValueError("bit must be 0 or 1")
    return int(value)


def positions(mask):
    while mask:
        flag = mask & -mask
        yield flag.bit_length() - 1
        mask ^= flag


@dataclass(frozen=True)
class Probe:
    name: str
    root: int
    condition: int
    cost: int


class SourceAudit:
    def __init__(self, problem):
        fields(problem, "conditions", "sources", "fault_budget", "history", "menu")
        for key in ("conditions", "history", "menu"):
            if not isinstance(problem[key], list):
                raise ValueError(f"{key} must be an array")
        self.conditions = tuple(name(i) for i in problem["conditions"])
        if not self.conditions or len(set(self.conditions)) != len(self.conditions):
            raise ValueError("conditions must be nonempty and distinct")
        indices = {s: i for i, s in enumerate(self.conditions)}
        sources = problem["sources"]
        if not isinstance(sources, dict):
            raise ValueError("sources must map source names to fault roots")
        roots = {name(src): name(root) for src, root in sources.items()}
        self.roots = sorted(set(roots.values()))
        root_index = {s: i for i, s in enumerate(self.roots)}
        self.f = number(problem["fault_budget"])

        def cell(row):
            src, cond = name(row["source"]), name(row["condition"])
            if src not in roots or cond not in indices:
                raise ValueError("undeclared source or condition")
            return root_index[roots[src]], indices[cond]

        self.history = []
        for row in problem["history"]:
            fields(row, "source", "condition", "bit")
            self.history.append((*cell(row), bit(row["bit"])))
        self.menu = []
        for row in problem["menu"]:
            fields(row, "name", "source", "condition", "cost")
            self.menu.append(Probe(name(row["name"]), *cell(row), number(row["cost"])))
        if len({p.name for p in self.menu}) != len(self.menu):
            raise ValueError("each menu entry needs a distinct name")
        self.zeros = [0] * len(self.roots)
        self.ones = [0] * len(self.roots)
        for r, i, value in self.history:
            (self.ones if value else self.zeros)[r] |= 1 << i

    def risk_supports(self, ones):
        for i in range(len(self.conditions)):
            yield 1 << i
        unions = {0}
        for positive in set(ones) - {0}:
            unions |= {current | positive for current in unions}
        yield from sorted(s for s in unions if s.bit_count() > 1)

    @staticmethod
    def mismatches(zeros, ones, truth):
        return sum(1 << r for r, (z, o) in enumerate(zip(zeros, ones)) if z & truth or o & ~truth)

    def consistent(self, zeros, ones):
        # Removing faulty roots must cover each pair of conflicting reporters, including self conflicts.
        forced = sum(1 << r for r, (z,o) in enumerate(zip(zeros,ones)) if z & o)
        if forced.bit_count() > self.f:
            return False
        active = [r for r, (z,o) in enumerate(zip(zeros,ones)) if (z or o) and not forced & (1 << r)]
        conflicts = [(1 << a, 1 << b) for j,a in enumerate(active) for b in active[j+1:]
                     if zeros[a] & ones[b] or ones[a] & zeros[b]]

        @lru_cache(maxsize=None)
        def cover(removed):
            for a,b in conflicts:
                if not removed & (a | b):
                    return (removed.bit_count() < self.f and
                            (cover(removed | a) or cover(removed | b)))
            return True
        return cover(forced)

    def classes(self, zeros, ones):
        if sum(bool(o) for o in ones) > self.f:
            return False, self.consistent(zeros, ones)
        unsafe = any(self.mismatches(zeros, ones, s).bit_count() <= self.f for s in self.risk_supports(ones))
        return True, unsafe

    def witness(self):
        base = sum(1 << r for r, positives in enumerate(self.ones) if positives)
        coverage = [0] * len(self.roots)
        for p in self.menu:
            coverage[p.root] |= 1 << p.condition
        for support in self.risk_supports(self.ones):
            faults = self.mismatches(self.zeros, self.ones, support)
            if faults.bit_count() > self.f:
                continue
            distinct = sum(1 << r for r, covered in enumerate(coverage) if covered & support)
            extra = distinct & ~(base | faults)
            base_room = self.f - base.bit_count()
            if extra.bit_count() <= base_room + self.f - faults.bit_count():
                base_faults = base
                for r in positions(extra):
                    if base_room:
                        base_faults |= 1 << r
                        base_room -= 1
                    else:
                        faults |= 1 << r
                return self.describe_pair(support, faults, base_faults)
        return None

    def describe_pair(self, support, faults, base_faults):
        shared = {}
        combined = list(self.history)
        for p in self.menu:
            reported = 0
            if base_faults & (1 << p.root):
                if not faults & (1 << p.root):
                    reported = (support >> p.condition) & 1
                else:
                    reported = (self.ones[p.root] >> p.condition) & 1
            shared[p.name] = reported
            combined.append((p.root, p.condition, reported))

        def world(truth):
            mismatches = {self.roots[r] for r, i, value in combined if ((truth >> i) & 1) != value}
            return {"requests_at": [self.conditions[i] for i in positions(truth)],
                    "mismatching_roots": sorted(mismatches)}

        return {"all_zero": world(0), "nonzero": world(support), "common_future_bits": shared}

    def verify_witness(self, certificate):
        """Check a supplied witness against raw history and every purchased reading; no hypothesis search."""
        fields(certificate, "all_zero", "nonzero", "common_future_bits")
        shared = certificate["common_future_bits"]
        if not isinstance(shared, dict) or set(shared) != {p.name for p in self.menu}:
            raise ValueError("the shared transcript must contain the complete menu")
        observed = [*self.history, *((p.root, p.condition, bit(shared[p.name])) for p in self.menu)]
        for label in ("all_zero", "nonzero"):
            world = certificate[label]
            fields(world, "requests_at", "mismatching_roots")
            for key, allowed in (("requests_at", self.conditions), ("mismatching_roots", self.roots)):
                values = world[key]
                if not isinstance(values, list) or any(not isinstance(v, str) for v in values):
                    raise ValueError(f"expected name list: {key}")
                if len(set(values)) != len(values) or set(values).difference(allowed):
                    raise ValueError(f"duplicate or unknown name in {key}")
            requests = set(world["requests_at"])
            if bool(requests) != (label == "nonzero"):
                raise ValueError("worlds must reach opposite conclusions")
            disagree = {self.roots[r] for r,i,v in observed if (self.conditions[i] in requests) != v}
            if disagree != set(world["mismatching_roots"]) or len(disagree) > self.f:
                raise ValueError("claimed faulty roots do not explain the transcript within budget")

    def plan(self):
        if self.f == 0:
            # On the all-zero path every unobserved condition needs one reading from any source.
            known = {i for _, i, _ in self.history}
            first = {}
            for p in sorted(self.menu, key=lambda item: (item.cost, item.name)):
                if p.condition not in known:
                    first.setdefault(p.condition, p)
            return sum(p.cost for p in first.values()), next(iter(first.values())).name
        # A same-root same-condition retry can always echo the first response. Buy the cheapest copy.
        cheapest = {}
        for p in self.menu:
            cell = p.root, p.condition
            if (self.zeros[p.root] | self.ones[p.root]) & (1 << p.condition):
                continue
            old = cheapest.get(cell)
            if old is None or (p.cost, p.name) < (old.cost, old.name):
                cheapest[cell] = p
        probes = sorted(cheapest.values(), key=lambda p: (p.cost, p.name))

        @lru_cache(maxsize=None)
        def solve(unread, positives):
            zeros, ones = self.zeros.copy(), self.ones.copy()
            for j, p in enumerate(probes):
                if not (unread >> j) & 1:
                    target = ones if (positives >> j) & 1 else zeros
                    target[p.root] |= 1 << p.condition
            if self.classes(zeros, ones) != (True, True):
                return 0, None
            if not unread:
                raise RuntimeError("ambiguous leaf in a separating menu")
            best = choice = None
            for j in positions(unread):
                p = probes[j]
                if best is not None and p.cost >= best:
                    break
                left = unread ^ (1 << j)
                refuse = solve(left, positives)[0]
                if best is not None and p.cost + refuse >= best:
                    continue
                request = solve(left, positives | (1 << j))[0]
                total = p.cost + max(refuse, request)
                if best is None or total < best:
                    best, choice = total, p
            return best, choice

        cost, choice = solve((1 << len(probes)) - 1, 0)
        return cost, choice.name

    def report(self, *, feasibility_only=False):
        status = {(False, False): "inconsistent", (True, False): "all_zero",
                  (False, True): "some_request", (True, True): "ambiguous"}
        current = status[self.classes(self.zeros, self.ones)]
        if current != "ambiguous":
            return {"status": current, "next_probe": None,
                    "worst_case_cost": None if current == "inconsistent" else 0}
        witness = self.witness()
        if witness:
            return {"status": "unidentifiable", "next_probe": None, "witness": witness}
        if feasibility_only:
            return {"status": "resolvable"}
        cost, choice = self.plan()
        return {"status": "resolvable", "worst_case_cost": cost, "next_probe": choice}


def observe(problem, probe_name, value):
    probe = next((p for p in problem["menu"] if p["name"] == probe_name), None)
    if probe is None:
        raise ValueError(f"unknown or already spent probe: {probe_name}")
    row = {"source": probe["source"], "condition": probe["condition"], "bit": bit(value)}
    return {**problem, "menu": [p for p in problem["menu"] if p["name"] != probe_name],
            "history": [*problem["history"], row]}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("problem", type=Path)
    parser.add_argument("--feasibility-only", action="store_true", help="skip the exponential cost search")
    parser.add_argument("--verify-witness", type=Path, help="validate a saved unidentifiable report against the input")
    parser.add_argument("--record", nargs=2, action="append", default=[], metavar=("PROBE", "BIT"))
    args = parser.parse_args()
    try:
        current = json.loads(args.problem.read_text(encoding="utf-8"))
        audit = SourceAudit(current)
        for label, answer in args.record:
            current = observe(current, label, int(answer))
            audit = SourceAudit(current)
        if args.verify_witness:
            saved = json.loads(args.verify_witness.read_text(encoding="utf-8-sig"))
            if not isinstance(saved, dict) or saved.get("status") != "unidentifiable" or "witness" not in saved:
                raise ValueError("expected an unidentifiable report with a witness")
            audit.verify_witness(saved["witness"])
            answer = {"status":"verified"}
        else:
            answer = audit.report(feasibility_only=args.feasibility_only)
        print(json.dumps(answer, indent=2, ensure_ascii=False))
    except (OSError, ValueError) as error:
        parser.exit(2, f"{error}\n")
