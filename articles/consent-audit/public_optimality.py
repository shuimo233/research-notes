"""Public lower bounds for exact reading certificates in integer difference networks."""

from collections import defaultdict
from itertools import combinations

from conclusion_replay import components, interval, pin
from slack_certificate import claims, sites, visible


def tighten(d, u, v, value):
    """Append x[v] - x[u] <= value to a closed network."""
    if value + d[v][u] < 0:
        return None
    return tuple(
        tuple(min(bound, d[i][u] + value + d[v][j]) for j, bound in enumerate(row))
        for i, row in enumerate(d)
    )


def conflicts(public, alternative):
    return tuple(
        ((1 << i) | (1 << j)) & ~1
        for i, j in combinations(range(len(public)), 2)
        if public[i][j] > alternative[i][j] or public[j][i] > alternative[j][i]
    )


class PublicAudit:
    def __init__(self, archive, targets, certificate):
        self.archive = archive
        self.targets = targets
        self.labels = certificate["labels"]
        if any(type(level) is not int for level in self.labels):
            raise ValueError("report labels must be integers")
        self.disclosed = {}
        self.fibre = archive
        for site, value in certificate["disclosed"]:
            if (
                type(site) is not int
                or type(value) is not int
                or not 0 < site < len(archive)
                or site in self.disclosed
            ):
                raise ValueError("invalid public reading")
            self.disclosed[site] = value
            self.fibre = pin(self.fibre, site, value)
        self.alternatives = {}
        for bound in claims(targets, self.labels):
            u, v, b = bound
            if self.fibre[u][v] > b:
                raise ValueError("disclosed values do not determine the claimed report")
            alternative = tighten(archive, v, u, -b - 1)
            if alternative is not None:
                self.alternatives[bound] = conflicts(self.fibre, alternative)

    def check(self, proof):
        used = 0
        for members, bound in proof:
            if (
                not members
                or any(
                    type(i) is not int or not 0 < i < len(self.archive) for i in members
                )
                or len(members) != len(set(members))
            ):
                raise ValueError("invalid witness group")
            key = tuple(bound)
            if key not in self.alternatives:
                raise ValueError("unknown or impossible counterfactual bound")
            group = visible(members)
            if group & used:
                raise ValueError("witness groups overlap")
            if any(not e & group for e in self.alternatives[key]):
                raise ValueError(
                    "a public-compatible record has no required counterfactual in this group"
                )
            used |= group
        return len(proof)

    def baseline(self, rigid):
        partition = defaultdict(list)
        mapping = components(self.archive) if rigid else range(len(self.archive))
        for i, point in enumerate(mapping):
            partition[point].append(i)
        proof = []
        for point, members in partition.items():
            if point == 0:
                continue
            mask = visible(members)
            witness = next(
                (
                    bound
                    for bound, edges in self.alternatives.items()
                    if all(mask & e for e in edges)
                ),
                None,
            )
            if witness is not None:
                proof.append((members, witness))
        return proof

    def options(self):
        public = visible(self.disclosed)
        for site in sorted(self.disclosed):
            own = 1 << site
            choices = {}
            for bound, edges in self.alternatives.items():
                needs = {e & ~public for e in edges if not e & own}
                if 0 in needs:
                    continue
                forced = {e for e in needs if e.bit_count() == 1}
                forced_mask = sum(forced)
                rest = (e for e in needs if not e & forced_mask)
                choices.setdefault(tuple(sorted(forced)) + tuple(sorted(rest)), bound)
            sorted_choices = sorted(
                choices.items(),
                key=lambda pair: (
                    len(pair[0]),
                    sum(r.bit_count() for r in pair[0]),
                    pair[1],
                ),
            )
            if sorted_choices:
                yield site, sorted_choices

    def pack(self, initial, limit=5_000):
        options = sorted(self.options(), key=lambda row: (len(row[1]), row[0]))
        best = initial
        tested = 0
        stopped = False

        def visit(k, previous):
            nonlocal best, tested, stopped
            if len(previous) + len(options) - k <= len(best):
                return
            site, choices = options[k]
            for requirement, bound in choices:
                if tested >= limit:
                    stopped = True
                    return
                tested += 1
                attempt = (*previous, (site, bound, requirement))
                found = disjoint_covers(attempt)
                if found is None:
                    continue
                if len(found) > len(best):
                    best = found
                visit(k + 1, attempt)
                if stopped or len(best) == len(self.disclosed):
                    return
            visit(k + 1, previous)

        visit(0, ())
        return best, tested, stopped


def solve_2sat(count, clauses):
    graph = [[] for _ in range(2 * count)]
    reverse = [[] for _ in graph]

    def code(lit):
        return 2 * (abs(lit) - 1) + (lit < 0)

    for left, right in clauses:
        a, b = code(left), code(right)
        for u, v in ((a ^ 1, b), (b ^ 1, a)):
            graph[u].append(v)
            reverse[v].append(u)

    seen = set()
    finished = []
    for root in range(len(graph)):
        stack = [root]
        while stack:
            current = stack.pop()
            if current < 0:
                finished.append(~current)
            elif current not in seen:
                seen.add(current)
                stack.append(~current)
                stack.extend(graph[current])

    component = [-1] * len(graph)
    for sweep, root in enumerate(reversed(finished)):
        if component[root] != -1:
            continue
        stack = [root]
        while stack:
            u = stack.pop()
            if component[u] == -1:
                component[u] = sweep
                stack.extend(reverse[u])
    values = []
    for v in range(0, len(graph), 2):
        if component[v] == component[v + 1]:
            return None
        values.append(component[v] > component[v + 1])
    return values


def disjoint_covers(requirements):
    """Solve the binary clauses after selecting one report bound for each group."""
    clauses = []
    by_site = defaultdict(list)
    variables = {}
    for group, (_, _, masks) in enumerate(requirements):
        for row in masks:
            lits = []
            for i in sites(row):
                if (group, i) not in variables:
                    variables[group, i] = len(variables) + 1
                    by_site[i].append(variables[group, i])
                lits.append(variables[group, i])
            clauses.append((lits[0], lits[-1]))
    for options in by_site.values():
        clauses.extend((-a, -b) for a, b in combinations(options, 2))
    assignment = solve_2sat(len(variables), clauses)
    if assignment is None:
        return None
    made = [([site], bound) for site, bound, _ in requirements]
    for (group, site), number in variables.items():
        if assignment[number - 1]:
            made[group][0].append(site)
    return [(sorted(members), bound) for members, bound in made]


def candidate_records(audit):
    d = audit.fibre

    def extremes(matrix):
        yield tuple(-row[0] for row in matrix)
        yield matrix[0]

    seen = set()
    for x in extremes(d):
        if x not in seen:
            yield x
            seen.add(x)
    for i in range(1, len(d)):
        lo, hi = interval(d, 0, i)
        if lo == hi:
            continue
        for value in (lo, hi):
            for x in extremes(pin(d, i, value)):
                if x not in seen:
                    yield x
                    seen.add(x)
