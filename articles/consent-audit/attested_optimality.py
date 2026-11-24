"""Repair a public minimum-disclosure proof by attesting additional comparisons."""

from itertools import combinations

from conclusion_replay import components, interval
from public_optimality import tighten
from slack_certificate import Cover, minimal_rows, visible


class Exhausted(RuntimeError):
    pass


def impose(zone, facts):
    for u, v, t in facts:
        zone = tighten(zone, v, u, -t)
        if zone is None:
            raise ValueError("attested comparisons conflict with the public record")
    return zone


def new_exact(before, after):
    return [
        i
        for i in range(1, len(before))
        if before[0][i] > -before[i][0] and after[0][i] == -after[i][0]
    ]


def true_comparisons(zone, actual, grid):
    if grid < 1:
        raise ValueError("comparison grid must be a positive integer")
    return [
        (u, v, threshold)
        for u, row in enumerate(zone)
        for v in range(len(row))
        if u != v
        and (threshold := grid * ((actual[v] - actual[u]) // grid)) > -zone[v][u]
    ]


class ShorterWorlds:
    def __init__(self, audit, proof):
        self.start = audit.fibre
        audit.check(proof)
        self.checked = 0
        self.profiles = self.compile(audit, proof)

    @staticmethod
    def compile(audit, proof):
        if not audit.disclosed:
            return {}
        classes = components(audit.archive)
        choices = sorted(set(classes) - {0})
        must_hit = [{classes[i] for i in group} for group, _ in proof]
        alternatives = [
            tighten(audit.archive, v, u, -b - 1) for u, v, b in audit.alternatives
        ]
        d = audit.fibre
        profiles = {}
        for selected in combinations(
            choices, min(len(choices), len(audit.disclosed) - 1)
        ):
            if any(not subset.intersection(selected) for subset in must_hit):
                continue
            keep = (0, *selected)
            clauses = set()
            for alt in alternatives:
                group, automatic = [], False
                for i in keep:
                    for j in keep:
                        threshold = alt[i][j] + 1
                        if -d[j][i] >= threshold:
                            automatic = True
                            break
                        if d[i][j] >= threshold:
                            group.append((i, j, threshold))
                    if automatic:
                        break
                if not automatic:
                    clauses.add(tuple(sorted(group)))
            if () not in clauses:
                ordered = tuple(sorted(clauses, key=lambda cs: (len(cs), cs)))
                profiles.setdefault(ordered, selected)
        return profiles

    def find(self, facts=(), limit=100_000):
        fibre = impose(self.start, facts)
        self.checked += 1
        states = 0

        def extend(i, zone, clauses):
            nonlocal states
            if i == len(clauses):
                return zone[0]
            current = clauses[i]
            if any(-zone[v][u] >= t for u, v, t in current):
                return extend(i + 1, zone, clauses)
            for u, v, t in current:
                if zone[u][v] < t:
                    continue
                if states >= limit:
                    raise Exhausted("substitute-certificate search budget exceeded")
                states += 1
                suffix = extend(i + 1, tighten(zone, v, u, -t), clauses)
                if suffix is not None:
                    return suffix
            return None

        for chunks, readings in self.profiles.items():
            witness = extend(0, fibre, chunks)
            if witness is not None:
                return dict(
                    record=witness, readings=[[i, witness[i]] for i in readings]
                )
        return None

    def weakest(self, others, claim, grid):
        u, v, cut = claim
        retained = impose(self.start, others)
        left = interval(retained, u, v)[0] // grid
        right = cut // grid
        while left + 1 < right:
            mid = (left + right) // 2
            if self.find([*others, (u, v, mid * grid)]) is None:
                right = mid
            else:
                left = mid
        return u, v, right * grid


def repair(oracle, actual, grid, origin_only=False, rounds=500):
    facts = true_comparisons(oracle.start, actual, grid)
    if origin_only:
        facts = [f for f in facts if 0 in f[:2]]
    base = oracle.find()
    if base is None:
        return dict(
            status="proved",
            attested=[],
            trace=[],
            single_unary=False,
            single_pair=False,
            newly_exact=[],
        )
    cap = oracle.find(facts)
    if cap is not None:
        return dict(status="unavailable", counterexample=cap)
    one = []
    for f in facts:
        if oracle.find([f]) is None:
            idea = oracle.weakest([], f, grid)
            newly = new_exact(oracle.start, impose(oracle.start, [idea]))
            one.append((len(newly), idea, newly))
    if one:
        _, claim, fixed = min(one, key=lambda row: (row[0], row[1]))
        return dict(
            status="proved",
            attested=[claim],
            trace=[base],
            newly_exact=fixed,
            single_unary=any(0 in f[:2] for _, f, _ in one),
            single_pair=any(0 not in f[:2] for _, f, _ in one),
        )

    traces, clauses = [], set()
    witness = base
    for _ in range(rounds):
        sample = witness["record"]
        mask = visible(
            i for i, (u, v, c) in enumerate(facts, 1) if sample[v] - sample[u] < c
        )
        assert mask and mask not in clauses
        clauses.add(mask)
        traces.append(witness)
        solver = Cover(minimal_rows(clauses), len(facts) + 1)
        best, _, _, done = solver.minimum((solver.greedy(),), 100_000)
        if not done:
            raise Exhausted("attestation cover search budget exceeded")
        chosen = [facts[i - 1] for i in best]
        witness = oracle.find(chosen)
        if witness is None:
            for i in range(len(chosen)):
                chosen[i] = oracle.weakest(
                    [*chosen[:i], *chosen[i + 1 :]], chosen[i], grid
                )
            rest = new_exact(oracle.start, impose(oracle.start, chosen))
            return dict(
                status="proved",
                attested=chosen,
                trace=traces,
                newly_exact=rest,
                single_unary=False,
                single_pair=False,
            )
    raise Exhausted("attestation counterexample limit exceeded")


def one_exact(oracle, actual):
    for i, value in enumerate(actual[1:], 1):
        if oracle.start[0][i] == -oracle.start[i][0]:
            continue
        if oracle.find(((0, i, value), (i, 0, -value))) is None:
            return i
    return None


def largest_two_read_zone(audit, actual):
    """The largest successful difference zone through actual, for a two-read proof."""
    if len(audit.disclosed) != 2 or not audit.alternatives:
        raise ValueError("expected a report with a two-reading minimum")
    if len(actual) != len(audit.fibre) or actual[0] != 0:
        raise ValueError("the actual record must start at the known reference")
    if any(
        actual[j] - actual[i] > b
        for i, row in enumerate(audit.fibre)
        for j, b in enumerate(row)
    ):
        raise ValueError("the original record conflicts with the public packet")
    alternatives = [
        tighten(audit.archive, v, u, -b - 1) for u, v, b in audit.alternatives
    ]
    facts = []
    for i, value in enumerate(actual[1:], 1):
        merged = []
        for lo, hi in sorted(interval(b, 0, i) for b in alternatives):
            if merged and lo <= merged[-1][1] + 1:
                merged[-1][1] = max(merged[-1][1], hi)
            else:
                merged.append([lo, hi])
        projected = next(((lo, hi) for lo, hi in merged if lo <= value <= hi), None)
        if projected is None:
            raise ValueError("one reading already certifies this actual record")
        publicly_lo, publicly_hi = interval(audit.fibre, 0, i)
        lo, hi = projected
        if publicly_lo < lo:
            facts.append((0, i, lo))
        if hi < publicly_hi:
            facts.append((i, 0, -hi))
    return impose(audit.fibre, facts), facts
