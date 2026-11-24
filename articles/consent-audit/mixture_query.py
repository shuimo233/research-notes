"""Exact query planning for a finite mixture of independent categorical inputs."""

from collections import Counter
from fractions import Fraction as Q
from functools import lru_cache
from math import prod
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from frontier_plan import bits


class MixturePlan:
    """An exact planner using forced-read obligations and a finite predictive belief."""

    def __init__(
        self,
        service,
        weights,
        conditional,
        costs=None,
        disabled=(),
        *,
        observe_values=True,
    ):
        self.service = service
        self.names = service.plan.names
        self.index = service.plan.indices
        if any(n != 1 for n in service.plan.counts):
            raise ValueError("use a separate type for each location")
        self.locations = tuple(group[0] for group in service.members)
        self.neighbors = tuple(service.plan.neighbors)
        self.certain = tuple(service.plan.certain)
        self.cost = tuple(Q(1 if costs is None else costs[v]) for v in self.names)
        if min(self.cost) <= 0:
            raise ValueError("costs must be positive")
        self.weights = tuple(map(Q, weights))
        if (
            not self.weights
            or any(w <= 0 for w in self.weights)
            or sum(self.weights) != 1
        ):
            raise ValueError("mixture weights must be positive and sum to 1")
        self.domain = [tuple(service.masks[v]) for v in self.locations]
        if set(conditional) != set(self.names):
            raise ValueError("conditional laws must match locations")
        self.likelihood = []
        self.rows = []
        self.compact = []
        n = len(self.weights)
        for i, (v, xs) in enumerate(zip(self.names, self.domain)):
            supplied = conditional[v]
            if len(supplied) != n or any(set(p) != set(xs) for p in supplied):
                raise ValueError("supply one row per mode over the full support")
            rows = tuple(tuple(Q(p[x]) for x in xs) for p in supplied)
            if any(sum(p) != 1 or min(p) <= 0 for p in rows):
                raise ValueError("conditional rows must be positive and sum to 1")
            self.rows.append(rows)
            by_value = dict(zip(xs, zip(*rows)))
            groups = {}
            tags = {}
            for x, law in by_value.items():
                tag = (
                    service.masks[self.locations[i]][x],
                    tuple(p / law[0] for p in law) if observe_values else (),
                )
                tags[x] = tag
                if tag not in groups:
                    groups[tag] = [Q(0)] * n
                for j, p in enumerate(law):
                    groups[tag][j] += p
            self.likelihood.append(
                by_value
                if observe_values
                else {x: tuple(groups[tag]) for x, tag in tags.items()}
            )
            self.compact.append(
                tuple((mask, tuple(law)) for (mask, _), law in groups.items())
            )
            # Support and forced-read information depend on the exact relation table.
            assert all(mask & ~self.neighbors[i] == 0 for mask, _ in self.compact[-1])
        self.start = (1 << len(self.names)) - 1
        for v in disabled:
            i = self.index[v]
            if self.neighbors[i]:
                raise ValueError(
                    "only an optional isolated observation may be disabled"
                )
            self.start &= ~(1 << i)
        self.mode_classes = lru_cache(None)(self._mode_classes)
        self.optimum = lru_cache(None)(self._optimum)

    def _mode_classes(self, live):
        classes = {}
        for k in range(len(self.weights)):
            signature = tuple(self.rows[i][k] for i in bits(live))
            classes.setdefault(signature, []).append(k)
        return tuple(tuple(c) for c in classes.values())

    def _canonical(self, live, weights):
        result = [Q(0)] * len(weights)
        for cluster in self.mode_classes(live):
            result[cluster[0]] = sum(weights[i] for i in cluster)
        return tuple(result)

    def _update(self, live_after, belief, likelihood):
        marginal = tuple(w * q for w, q in zip(belief, likelihood, strict=True))
        mass = sum(marginal)
        return mass, self._canonical(live_after, tuple(p / mass for p in marginal))

    def transitions(self, i, live, forced, belief):
        rest = live ^ (1 << i)
        groups = Counter()
        for mask, likelihood in self.compact[i]:
            p, post = self._update(rest, belief, likelihood)
            groups[rest, (forced | mask) & rest, post] += p
        return groups.items()

    def _required(self, live, forced):
        for i in bits(live):
            forced |= self.certain[i]
        return forced & live

    def _force_cover(self, live, forced, belief):
        """If forced vertices cover unresolved edges, the remaining spend has a closed form."""
        value = sum(self.cost[i] for i in bits(forced))
        for j in bits(live & ~forced):
            sources = tuple(bits(self.neighbors[j] & forced))
            if not sources:
                continue
            avoid = sum(
                w
                * prod(
                    sum(law[k] for mask, law in self.compact[i] if not mask & (1 << j))
                    for i in sources
                )
                for k, w in enumerate(belief)
                if w
            )
            value += self.cost[j] * (1 - avoid)
        return value

    def _optimum(self, live, forced, belief):
        forced = self._required(live, forced)
        unforced = live & ~forced
        if not any(self.neighbors[i] & unforced for i in bits(unforced)):
            return self._force_cover(live, forced, belief), next(bits(forced), None)
        if forced:
            actions = (next(bits(forced)),)
        else:
            actions = tuple(
                i
                for i in bits(live)
                if self.neighbors[i] & live
                or len({self.rows[i][k] for k, w in enumerate(belief) if w}) > 1
            )
        return min(
            (
                self.cost[i]
                + sum(
                    p * self.optimum(*state)[0]
                    for state, p in self.transitions(i, live, forced, belief)
                ),
                i,
            )
            for i in actions
        )

    def initial(self):
        return self.start, 0, self._canonical(self.start, self.weights)

    def execute(self, ask, product=None):
        live, forced, belief = self.initial()
        known = {}
        if product is not None and self.start != (1 << len(self.names)) - 1:
            raise ValueError("product policy expects all locations enabled")
        while True:
            i = (
                self.optimum(live, forced, belief)[1]
                if product is None
                else product.action(
                    tuple(int(bool(live & (1 << j))) for j in range(len(self.names))),
                    forced,
                )[0]
            )
            if i is None:
                break
            v = self.locations[i]
            x = ask(v)
            if x not in self.likelihood[i]:
                raise ValueError("reading outside the legal interval")
            known[v] = x
            live ^= 1 << i
            forced = (forced | self.service.masks[v][x]) & live
            _, belief = self._update(live, belief, self.likelihood[i][x])
        answers = {
            e: self.service.service.answer(e, known) for e in self.service.service.order
        }
        if any(label is None for label in answers.values()):
            raise ArithmeticError("policy stopped without an exact certificate")
        return list(known), answers

    def product_policy_cost(self, product):
        @lru_cache(None)
        def evaluate(live, forced, belief):
            counts = tuple(int(bool(live & (1 << j))) for j in range(len(self.names)))
            i = product.action(counts, forced)[0]
            if i is None:
                return Q(0)
            return self.cost[i] + sum(
                p * evaluate(*state)
                for state, p in self.transitions(i, live, forced, belief)
            )

        value = evaluate(*self.initial())
        evaluate.cache_clear()
        return value

    def cost_in_mode(self, mode):
        """Evaluate the nominal posterior policy while inputs actually follow one mode."""

        @lru_cache(None)
        def evaluate(live, forced, belief):
            _, i = self.optimum(live, forced, belief)
            if i is None:
                return Q(0)
            rest = live ^ (1 << i)
            total = self.cost[i]
            for mask, likelihood in self.compact[i]:
                _, posterior = self._update(rest, belief, likelihood)
                total += likelihood[mode] * evaluate(
                    rest, (forced | mask) & rest, posterior
                )
            return total

        value = evaluate(*self.initial())
        evaluate.cache_clear()
        return value

    def clear(self):
        self.optimum.cache_clear()
        self.mode_classes.cache_clear()
