"""Exact robust pairwise querying after a compulsory prefix with known observations."""

from collections import Counter
from fractions import Fraction as Q
from math import prod
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from frontier_inquiry import RelationInquiry
from frontier_information import actual_cost
from frontier_plan import FrontierPlan, bits
from mixture_query import MixturePlan
from robust_game import solve_game


class ContextGame:
    """One independently uncertain component with pre-query obligation masks of known law."""

    def __init__(self, service, laws, contexts=None):
        self.service = service
        base = service.plan
        if any(n != 1 for n in base.counts):
            raise ValueError("use one planning type per location")
        if not laws:
            raise ValueError("supply at least one conditional model")
        self.contexts = {0: Q(1)} if contexts is None else contexts
        if sum(self.contexts.values()) != 1 or any(
            p <= 0 for p in self.contexts.values()
        ):
            raise ValueError("expected a distribution of compulsory masks")
        prices = dict(zip(base.names, base.cost))
        edges = [
            (u, base.names[j])
            for i, u in enumerate(base.names)
            for j in bits(base.neighbors[i])
            if i < j
        ]
        self.modes = []
        self.conditional = {u: [] for u in base.names}
        for law in laws:
            choices = {}
            if set(law) != set(service.service.domains):
                raise ValueError("each mode needs a law for every location")
            for i, u in enumerate(base.names):
                location = service.members[i][0]
                row = law[location]
                if (
                    set(row) != set(service.service.domains[location])
                    or sum(row.values()) != 1
                    or any(p <= 0 for p in row.values())
                ):
                    raise ValueError("every candidate needs positive probability")
                self.conditional[u].append(row)
                choices[u] = [
                    (tuple(base.names[j] for j in bits(service.masks[location][x])), p)
                    for x, p in row.items()
                ]
            self.modes.append(
                FrontierPlan(dict.fromkeys(base.names, 1), choices, edges, prices)
            )
        self.costs = prices
        self.budgets = tuple(
            sum(
                p * mode.optimum(mode.counts, mask)[0]
                for mask, p in self.contexts.items()
            )
            for mode in self.modes
        )
        self.oracles = {}

    def _solver(self, weight):
        if weight not in self.oracles:
            self.oracles[weight] = MixturePlan(
                self.service, weight, self.conditional, self.costs
            )
        return self.oracles[weight]

    def oracle_cost(self, weight):
        solver = self._solver(weight)
        return sum(
            p * solver.optimum(*solver.initial(mask))[0]
            for mask, p in self.contexts.items()
        )

    def regrets(self, weight):
        if 1 in weight:
            policy = self.modes[weight.index(1)]
            costs = [
                sum(
                    p * actual_cost(policy, mode, mask)
                    for mask, p in self.contexts.items()
                )
                for mode in self.modes
            ]
        else:
            solver = self._solver(weight)
            costs = [
                sum(
                    p * solver.cost_in_mode(z, mask)
                    for mask, p in self.contexts.items()
                )
                for z in range(len(self.modes))
            ]
        return tuple(a - b for a, b in zip(costs, self.budgets, strict=True))

    def solve(self):
        initial = {}
        m = len(self.modes)
        for z in range(m):
            weight = tuple(Q(i == z) for i in range(m))
            initial[weight] = self.regrets(weight)
            if not any(initial[weight]):
                break
        value, adversary, controller, risks = solve_game(initial, self.regrets)
        if value:
            assert (
                self.oracle_cost(adversary)
                - sum(w * v for w, v in zip(adversary, self.budgets))
                == value
            )
        return dict(
            regret=value, least_favorable=adversary, policies=controller, risks=risks
        )

    def execute(self, policy, forced, ask):
        if 1 in policy:
            mode = self.modes[policy.index(1)]
            path, labels, _ = self.service.execute(
                ask, planner=mode, initial_forced=forced
            )
            return path, labels
        return self._solver(policy).execute(ask, initial_forced=forced)


def partition(service):
    base = service.plan
    if any(n != 1 for n in base.counts):
        raise ValueError("use one planning type per location")
    forced = base.obligations(base.counts, 0)
    live = tuple(0 if forced >> i & 1 else n for i, n in enumerate(base.counts))
    return forced, base.parts(live)


def component_service(original, locations, first_law):
    labels = original.service
    # Tag values because the same reading can have a different meaning at different locations.
    domains = {u: tuple((u, x) for x in labels.domains[u]) for u in locations}
    edges = [(u, v) for u, v in labels.order if u in domains and v in domains]

    def read(left, right):
        u, a = left
        v, b = right
        return labels.tables[u, v].cells[a, b]

    return RelationInquiry(
        domains,
        edges,
        read,
        {u: {(u, x): p for x, p in first_law[u].items()} for u in locations},
        costs={u: original.plan.cost[original.types_by_id[u]] for u in locations},
    )


def law_for_prefix(base, forced, block):
    mass = {0: Q(1)}
    for i in bits(forced):
        update = Counter()
        for a, p in mass.items():
            for b, q in base.projections(i, block):
                update[a | b] += p * q
        mass = update
    return mass


class FactoredPlan:
    """Compose independently uncertain components, preserving legal labels."""

    def __init__(self, service, local_models):
        self.service = service
        self.forced, parts = partition(service)
        base = service.plan
        self.locations = tuple(group[0] for group in service.members)
        self.sources = [self.locations[i] for i in bits(self.forced)]
        self.components = []
        groups = {
            tuple(sorted(self.locations[i] for i in bits(block))): block
            for block, _ in parts
        }
        if set(local_models) != set(groups) or any(
            not laws for laws in local_models.values()
        ):
            raise ValueError(
                "specify a nonempty ambiguity set for each residual component"
            )
        for names, block in groups.items():
            laws = local_models[names]
            local = component_service(service, names, laws[0])
            mapping = {i: local.plan.indices[self.locations[i]] for i in bits(block)}
            mass = law_for_prefix(base, self.forced, block)
            exposure = {
                sum(1 << mapping[i] for i in bits(mask)): p for mask, p in mass.items()
            }
            converted = [
                {u: {(u, x): p for x, p in law[u].items()} for u in names}
                for law in laws
            ]
            game = ContextGame(local, converted, exposure)
            self.components.append((names, mapping, game))

    def solve(self):
        parts = [
            dict(component=names, **game.solve()) for names, _, game in self.components
        ]
        return dict(
            regret=sum(x["regret"] for x in parts),
            components=parts,
            scenario_count=prod(len(game.modes) for _, _, game in self.components),
        )

    def execute(self, answer, ask, rng):
        seen = {}
        flags = 0
        for u in self.sources:
            x = ask(u)
            seen[u] = x
            try:
                flags |= self.service.masks[u][x]
            except KeyError:
                raise ValueError(
                    "compulsory reading outside candidate support"
                ) from None

        def tagged(u):
            x = ask(u)
            seen[u] = x
            return u, x

        for (_, mapping, game), part in zip(
            self.components, answer["components"], strict=True
        ):
            forced = sum(1 << mapping[i] for i in mapping if flags >> i & 1)
            # Draw a single exact rational lottery per component.
            remaining = Q(1)
            for policy, mass in part["policies"]:
                ratio = mass / remaining
                if rng.randrange(ratio.denominator) < ratio.numerator:
                    game.execute(policy, forced, tagged)
                    break
                remaining -= mass
        labels = {
            e: self.service.service.answer(e, seen) for e in self.service.service.order
        }
        if None in labels.values():
            raise ArithmeticError(
                "a factored controller did not return an exact certificate"
            )
        return list(seen), labels
