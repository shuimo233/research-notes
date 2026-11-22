"""Fixed-plan certification for overlapping actions and adversarial binary read errors."""

from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass
from itertools import combinations, combinations_with_replacement

from .core import Budget, Domain, _trace, _units
from ._layer import joint_witness, tree_layer


def _bit(value):
    if type(value) not in (bool, int) or value not in (0, 1):
        raise ValueError("action planning requires binary observations")
    return int(value)


def _blockers(allowed):
    """Minimal sets of rules that have no jointly valid action."""
    groups = {frozenset()}
    for action in sorted(set.union(*map(set, allowed))):
        reject = {i for i, actions in enumerate(allowed) if action not in actions}
        if not reject:
            return ()
        expanded = set()
        for group in groups:
            if group & reject:
                expanded.add(group)
            else:
                expanded.update(group | {i} for i in reject)
        groups = set()
        for group in sorted(expanded, key=len):
            if not any(g <= group for g in groups):
                groups.add(group)
    return tuple(sorted((tuple(sorted(g)) for g in groups), key=lambda g: (len(g), g)))


def _integer_point(limits, directions):
    """Intersect integer half-planes in at most two exceptional count variables."""
    x_max, y_max = (*limits, 0, 0)[:2]
    lo, hi = 0, x_max
    lowers, uppers = [(0, 0)], [(0, y_max)]

    def restrict_x(a, c):
        nonlocal lo, hi
        if a > 0:
            hi = min(hi, c // a)
        elif a < 0:
            lo = max(lo, -((-c) // a))
        elif c < 0:
            return False
        return lo <= hi

    for direction, c in directions.items():
        a, b = (*direction, 0, 0)[:2]
        if b == 1:
            uppers.append((-a, c))
        elif b == -1:
            lowers.append((a, -c))
        elif not restrict_x(a, c):
            return False
    # At integral x every endpoint for y is integral. Eliminate y exactly.
    return all(restrict_x(l - u, cu - cl) for l, cl in lowers for u, cu in uppers)


def _small_cover(edges):
    """Find at most two columns meeting every crossing edge, if possible."""
    if not edges:
        return ()
    for a in edges[0]:
        remaining = [e for e in edges if a not in e]
        if not remaining:
            return (a,)
    for a in edges[0]:
        remaining = [e for e in edges if a not in e]
        for b in remaining[0]:
            if all(b in e for e in remaining):
                return (a, b)
    return None


def _two_colors(edges):
    neighbors = {}
    for a, b in edges:
        neighbors.setdefault(a, []).append(b)
        neighbors.setdefault(b, []).append(a)
    colors = {}
    for start in neighbors:
        if start in colors:
            continue
        colors[start] = False
        stack = [start]
        while stack:
            a = stack.pop()
            for b in neighbors[a]:
                if b not in colors:
                    colors[b] = not colors[a]
                    stack.append(b)
                elif colors[b] == colors[a]:
                    return False
    return True


def _intersection(columns, radii, evidence=None):
    """Can all these rules explain one transcript with these budgets?"""
    full = (1 << len(radii)) - 1
    edges = [(a, b) for a, b in combinations(columns, 2)
             if a & b and a & (full ^ b) and b & (full ^ a) and full & ~(a | b)]
    cut = _small_cover(edges)
    if cut is None:
        if _two_colors(edges):
            # Products of two trees are bipartite absolute retracts. Balls
            # restricted to one bipartition side have the pairwise Helly property.
            pairs = {(i, j): sum(n for c, n in columns.items() if ((c >> i) ^ (c >> j)) & 1)
                     for i, j in combinations_with_replacement(range(len(radii)), 2)}
            for parity in (0, 1):
                adjusted = [r - ((r + pairs[0, i] + parity) % 2) for i, r in enumerate(radii)]
                if min(adjusted) >= 0 and all(d <= adjusted[i] + adjusted[j] for (i, j), d in pairs.items()):
                    return True, "two_trees"
            return False, "two_trees"
        layer = tree_layer(edges)
        if layer is not None:
            core = joint_witness(columns, radii, layer, minimize=evidence is not None)
            if core is not None and evidence is not None:
                evidence.extend(core)
            return core is None, "halfball_tree"
        # Exact fallback: condition on the count for a high-degree crossing column.
        degree = Counter(x for edge in edges for x in edge)
        col = max(degree, key=lambda c: (degree[c], -columns[c]))
        tail = dict(columns)
        n = tail.pop(col)
        for z in range(n + 1):
            left = tuple(r - (n - z if col & (1 << i) else z) for i, r in enumerate(radii))
            if min(left) >= 0 and _intersection(tail, left)[0]:
                return True, "count_search"
        return False, "count_search"

    rest = [(c, n) for c, n in columns.items() if c not in cut]
    limits = tuple(columns[c] for c in cut)
    directions = {}
    for i, j in combinations_with_replacement(range(len(radii)), 2):
        tree_distance = sum(n for c, n in rest if ((c >> i) ^ (c >> j)) & 1)
        ones = tuple(((c >> i) & 1) + ((c >> j) & 1) for c in cut)
        direction = tuple(1 - b for b in ones)
        rhs = (radii[i] + radii[j] - tree_distance - sum(n*b for n, b in zip(limits, ones))) // 2
        directions[direction] = min(directions.get(direction, rhs), rhs)
    return _integer_point(limits, directions), ("tree", "one_column", "two_columns")[len(cut)]


@dataclass(frozen=True)
class Assessment:
    guaranteed: bool
    obstruction: tuple[str, ...]
    methods: tuple[str, ...]
    witnesses: tuple[tuple[str, ...], ...] = ()
    counterexample_ones: tuple | None = None


@dataclass(frozen=True)
class ActionResult:
    status: str
    action: str | None
    candidates: tuple[str, ...]
    spent: Budget
    observations: tuple
    error: str | None = None


@dataclass(frozen=True)
class ActionDecision:
    status: str
    action: str | None
    candidates: tuple[str, ...]


class ActionPlanner:
    """Minimize worst-case length of a fixed schedule within both budget caps."""

    def __init__(self, domain: Domain, allowed: Mapping, errors=0):
        self.domain = domain
        self.names = tuple(domain.rules)
        if set(allowed) != set(self.names):
            raise ValueError("allowed actions must be specified for every rule")
        if any(isinstance(allowed[k], (str, bytes)) for k in self.names):
            raise ValueError("each rule needs a collection of actions")
        self.allowed = tuple(frozenset(allowed[k]) for k in self.names)
        if any(not a or any(not isinstance(x, str) or not x for x in a) for a in self.allowed):
            raise ValueError("each rule needs nonempty action names")
        if isinstance(errors, Mapping) and set(errors) != set(self.names):
            raise ValueError("error allowances must cover every rule")
        self.radii = tuple(_units(errors[k] if isinstance(errors, Mapping) else errors) for k in self.names)
        self.groups = _blockers(self.allowed)
        self.bits = {q: tuple(_bit(rule(q)) for rule in domain.rules.values()) for q in domain.probes}

    def _possible(self, group, counts, radii=None, evidence=None):
        if radii is None:
            radii = tuple(self.radii[i] for i in group)
        length = sum(counts.values())
        active = tuple(j for j, r in enumerate(radii) if r < length)
        if not active:
            return True, "vacuous"
        if len(active) < len(group):
            group = tuple(group[j] for j in active)
            radii = tuple(radii[j] for j in active)
        columns = Counter()
        full = (1 << len(group)) - 1
        for q, n in counts.items():
            if n:
                c = sum(self.bits[q][i] << j for j, i in enumerate(group))
                c = min(c, full ^ c)  # Complementing all answers preserves joint feasibility.
                if c:
                    columns[c] += n
        local = [] if evidence is not None else None
        possible, method = _intersection(columns, radii, local)
        if not possible and evidence is not None:
            if not local:
                local = tuple(range(len(group)))
                for j in local:
                    keep = tuple(k for k in local if k != j)
                    if keep and not self._possible(tuple(group[k] for k in keep), counts,
                                                   tuple(radii[k] for k in keep))[0]:
                        local = keep
            evidence.extend(active[j] for j in local)
        return possible, method

    def _record(self, group, counts):
        """Recover a common transcript in run-length counts, using joint feasibility."""
        remaining = dict(counts)
        radii = tuple(self.radii[i] for i in group)
        record = []
        for q, n in counts.items():
            bits = [self.bits[q][i] for i in group]
            lo, hi = 0, n
            while lo < hi:
                mid = (lo + hi + 1) // 2
                left = tuple(r - (1-b)*mid for r, b in zip(radii, bits))
                remaining[q] = n - mid
                if min(left) >= 0 and self._possible(group, remaining, left)[0]:
                    lo = mid
                else:
                    hi = mid - 1
            del remaining[q]
            radii = tuple(r - (n-lo if b else lo) for r, b in zip(radii, bits))
            record.append((q, lo))
        return tuple(record)

    def _counts(self, schedule):
        if isinstance(schedule, Mapping):
            counts = {_trace(q): _units(n) for q, n in schedule.items()}
        else:
            counts = Counter(_trace(q) for q in schedule)
        if any(q not in self.bits for q in counts):
            raise ValueError("schedule contains an undeclared probe")
        return counts

    def decide(self, schedule, ones: Mapping):
        """Select a valid action for an existing report; one count per scheduled probe."""
        counts = self._counts(schedule)
        positive = {_trace(q): _units(n) for q, n in ones.items()}
        if counts.keys() != positive.keys() or any(positive[q] > n for q, n in counts.items()):
            raise ValueError("report needs one valid positive count for each scheduled probe")
        live = [i for i, radius in enumerate(self.radii)
                if sum(n - positive[q] if self.bits[q][i] else positive[q]
                       for q, n in counts.items()) <= radius]
        return self._decision(live)

    def _decision(self, live):
        names = tuple(self.names[i] for i in live)
        if not names:
            return ActionDecision("conflict", None, ())
        shared = frozenset.intersection(*(self.allowed[i] for i in live))
        if shared:
            return ActionDecision("ready", min(shared), names)
        return ActionDecision("ambiguous", None, names)

    def assess(self, schedule, *, witnesses=False):
        """Certify an iterable of traces or a compact mapping {trace: repeat_count}."""
        counts = self._counts(schedule)
        methods = set()
        separated = []
        for group in self.groups:
            evidence = [] if witnesses else None
            possible, method = self._possible(group, counts, evidence=evidence)
            methods.add(method)
            if possible:
                record = self._record(group, counts) if witnesses else None
                return Assessment(False, tuple(self.names[i] for i in group), tuple(sorted(methods)),
                                  counterexample_ones=record)
            if witnesses:
                separated.append(tuple(self.names[group[j]] for j in evidence))
        return Assessment(True, (), tuple(sorted(methods)), tuple(separated))

    def audit(self, schedule):
        """Export a JSON-compatible problem and a claim for the standalone verifier."""
        from .audit import fingerprint

        counts = self._counts(schedule)
        result = self.assess(counts, witnesses=True)
        problem = {
            "format": "stateful-id/audit-1",
            "domain": self.domain.id,
            "probes": [{"trace": list(q), "count": str(n)} for q, n in counts.items()],
            "rules": [{"name": name, "bits": [self.bits[q][i] for q in counts],
                       "errors": str(self.radii[i]), "actions": sorted(self.allowed[i])}
                      for i, name in enumerate(self.names)],
        }
        claim = {"problem_sha256": fingerprint(problem), "guaranteed": result.guaranteed}
        if result.guaranteed:
            claim["cores"] = [list(core) for core in result.witnesses]
        else:
            ones = dict(result.counterexample_ones)
            claim["ones"] = [str(ones[q]) for q in counts]
        return problem, claim

    def plan(self, budget: Budget):
        """Return a shortest feasible fixed schedule; break ties by declared cost."""
        if not self.groups:
            return ()
        cheapest = {}
        for q, bits in self.bits.items():
            if len(set(bits)) == 1:
                continue
            split = min(bits, tuple(1 - y for y in bits))
            if split not in cheapest or self.domain.costs[q] < self.domain.costs[cheapest[split]]:
                cheapest[split] = q
        probes = tuple(cheapest.values())
        cap = 2 * max(self.radii) + 1
        if not self.assess(dict.fromkeys(probes, cap)).guaranteed:
            return None
        for size in range(1, min(budget.queries, cap * len(probes)) + 1):
            best, best_cost = None, None
            for candidate in combinations_with_replacement(probes, size):
                cost = sum(self.domain.costs[q] for q in candidate)
                if cost > budget.cost or (best_cost is not None and cost >= best_cost):
                    continue
                counts = Counter(candidate)
                if max(counts.values()) <= cap and self.assess(counts).guaranteed:
                    best, best_cost = candidate, cost
            if best is not None:
                return best
        return None

    def run(self, observe, budget: Budget):
        """Recommend an action. Charge every dispatched observation, including a failed call."""
        schedule = self.plan(budget)
        if schedule is None:
            return ActionResult("no_guaranteed_plan", None, self.names, Budget(0, 0), ())
        live = dict(enumerate(self.radii))
        history = []
        cost = 0
        for step in range(len(schedule) + 1):
            decision = self._decision(live)
            spent = Budget(step, cost)
            if decision.status != "ambiguous":
                return ActionResult(decision.status, decision.action, decision.candidates, spent, tuple(history))
            if step == len(schedule):
                raise AssertionError("certified schedule ended without a common action")
            q = schedule[step]
            cost += self.domain.costs[q]
            try:
                y = _bit(observe(q))
            except Exception as exc:
                return ActionResult("error", None, decision.candidates, Budget(step + 1, cost), tuple(history),
                                    f"{q!r}: {type(exc).__name__}: {exc}")
            history.append((q, y))
            for i in tuple(live):
                if self.bits[q][i] != y:
                    live[i] -= 1
                    if live[i] < 0:
                        del live[i]
        raise AssertionError("unreachable")
