"""Finite deterministic rule identification from independently reset episodes."""

from collections import Counter
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from fractions import Fraction
from itertools import product
import json
import os
from pathlib import Path
import tempfile
from types import MappingProxyType


Trace = tuple[str, ...]
Rule = Callable[[Trace], object]
_PENDING = "Adapter outcome unknown (interrupted before checkpoint completion)"


def _trace(actions):
    if isinstance(actions, (str, bytes)):
        raise ValueError("a trace must be a sequence of action names")
    seq = tuple(actions)
    if any(not isinstance(s, str) or not s for s in seq):
        raise ValueError("actions must be nonempty strings")
    return seq


def traces(actions: Iterable[str], max_depth: int):
    """Enumerate nonempty cold-start sequences in length, then declaration order."""
    alphabet = _trace(actions)
    if type(max_depth) is not int or max_depth < 1 or len(set(alphabet)) != len(alphabet):
        raise ValueError("provide distinct actions and a positive depth")
    for depth in range(1, max_depth + 1):
        yield from product(alphabet, repeat=depth)


def _json(value):
    # Reject coercions (e.g. integer object keys) that would merge distinct answers.
    data = json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False, separators=(",", ":"))
    if json.loads(data) != value:
        raise ValueError("observations must round-trip as JSON values")
    return data


def _units(n):
    if type(n) is not int or n < 0:
        raise ValueError("costs and budgets must be nonnegative integers")
    return n


@dataclass(frozen=True)
class Budget:
    queries: int
    cost: int

    def __post_init__(self):
        _units(self.queries)
        _units(self.cost)


class Domain:
    """Version the id when changing action semantics, costs, rules or probe sets."""

    def __init__(self, id: str, rules: Mapping[str, Rule], probes: Iterable[Trace],
                 *, checks: Iterable[Trace] = (), cost: Callable[[Trace], int] = len):
        if not isinstance(id, str) or not id or not rules:
            raise ValueError("a versioned domain id and at least one rule are required")
        if any(not isinstance(k, str) or not k or not callable(v) for k, v in rules.items()):
            raise ValueError("rules must map nonempty names to prediction functions")
        self.id = id
        self.rules = MappingProxyType(dict(rules))
        self.probes = tuple(dict.fromkeys(map(_trace, probes)))
        self.checks = tuple(dict.fromkeys(map(_trace, checks)))
        if set(self.probes).intersection(self.checks):
            raise ValueError("validation traces must be held out from planning")
        self.costs = MappingProxyType({q: _units(cost(q)) for q in (*self.probes, *self.checks)})


@dataclass(frozen=True)
class Entry:
    actions: Trace
    cost: int
    answer_json: str | None
    error: str | None = None

    def record(self):
        out = {"actions": list(self.actions), "cost": self.cost}
        if self.error is None:
            out["observation"] = json.loads(self.answer_json)
        else:
            out["error"] = self.error
        return out


@dataclass(frozen=True)
class Journal:
    domain: str
    entries: tuple[Entry, ...] = ()
    budget: Budget | None = None
    strategy: str = "active"
    source_id: str | None = None

    def save(self, path):
        path = Path(path)
        data = {"format": "stateful-id/1", "domain": self.domain, "strategy": self.strategy,
                "entries": [e.record() for e in self.entries]}
        if self.budget is not None:
            data["budget"] = {"queries": self.budget.queries, "cost": self.budget.cost}
        if self.source_id is not None:
            data["source_id"] = self.source_id
        payload = json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False)
        with tempfile.NamedTemporaryFile("w", dir=path.parent, encoding="utf-8", delete=False) as f:
            temp = Path(f.name)
            try:
                f.write(payload)
            except BaseException:
                f.close()
                temp.unlink(missing_ok=True)
                raise
        try:
            os.replace(temp, path)
        finally:
            temp.unlink(missing_ok=True)

    @classmethod
    def load(cls, path):
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        if (not isinstance(data, dict) or data.get("format") != "stateful-id/1"
                or not isinstance(data.get("domain"), str) or not isinstance(data.get("entries"), list)):
            raise ValueError("invalid evidence journal")
        entries = []
        for r in data["entries"]:
            if not isinstance(r, dict) or set(r) not in (
                {"actions", "cost", "observation"}, {"actions", "cost", "error"}
            ) or not isinstance(r["actions"], list):
                raise ValueError("invalid evidence entry")
            if "error" in r and (not isinstance(r["error"], str) or not r["error"]):
                raise ValueError("invalid observation error")
            answer = _json(r["observation"]) if "observation" in r else None
            entries.append(Entry(_trace(r["actions"]), _units(r["cost"]), answer, r.get("error")))
        limits = data.get("budget")
        if limits is not None and (not isinstance(limits, dict) or set(limits) != {"queries", "cost"}):
            raise ValueError("invalid journal budget")
        strategy = data.get("strategy", "active")
        if strategy not in ("active", "fixed"):
            raise ValueError("invalid journal strategy")
        source_id = data.get("source_id")
        if source_id is not None and (not isinstance(source_id, str) or not source_id):
            raise ValueError("invalid source id")
        return cls(data["domain"], tuple(entries), Budget(**limits) if limits is not None else None,
                   strategy, source_id)


@dataclass(frozen=True)
class Probe:
    actions: Trace
    cost: int
    phase: str


@dataclass(frozen=True)
class Step:
    entry: Entry
    phase: str
    before: tuple[str, ...]
    after: tuple[str, ...]
    expected: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True)
class Result:
    status: str
    reason: str
    candidates: tuple[str, ...]
    model: Rule | None
    next_probe: Probe | None
    spent: Budget
    journal: Journal
    steps: tuple[Step, ...]

    @property
    def conflict_predictions(self):
        """Candidate outputs for the first observation that contradicted every survivor."""
        if self.status != "conflict":
            return None
        return {k: json.loads(v) for k, v in self.steps[-1].expected}


class _Session:
    def __init__(self, domain, budget, strategy, journal, source_id):
        if strategy not in ("active", "fixed"):
            raise ValueError("strategy must be active or fixed")
        self.domain, self.budget, self.strategy = domain, budget, strategy
        self.source_id = source_id
        self.live = tuple(domain.rules)
        self.used = set()
        self.cost = 0
        self.steps = []
        self.cache = {}
        self.failed = False
        if journal is not None:
            if journal.domain != domain.id:
                raise ValueError("journal/domain version mismatch")
            for entry in journal.entries:
                self.accept(entry)

    def predictions(self, q):
        cache = self.cache.setdefault(q, {})
        for key in self.live:
            if key not in cache:
                cache[key] = _json(self.domain.rules[key](q))
        return cache

    def affordable(self, q):
        return len(self.steps) < self.budget.queries and self.cost + self.domain.costs[q] <= self.budget.cost

    def accept(self, entry):
        q = entry.actions
        if (self.failed or not self.live or q in self.used or q not in self.domain.costs
                or _units(entry.cost) != self.domain.costs[q] or not self.affordable(q)):
            raise ValueError("invalid evidence sequence, price or cumulative budget")
        if (entry.error is None) == (entry.answer_json is None):
            raise ValueError("an entry must contain exactly one observation or error")
        before = self.live
        check = q in self.domain.checks
        if check and len(before) != 1:
            raise ValueError("validation evidence cannot select a model")
        if len(before) == 1:
            pending = next((item for item in self.domain.checks if item not in self.used), None)
            if pending is not None and q != pending:
                raise ValueError("expected the next held-out check")
            if pending is None and self.steps:
                raise ValueError("evidence after identification")
        expected = ()
        if entry.error is None:
            predictions = self.predictions(q)
            self.live = tuple(k for k in self.live if predictions[k] == entry.answer_json)
            if not self.live:
                expected = tuple((k, predictions[k]) for k in before)
        self.failed = entry.error is not None
        self.used.add(q)
        self.cost += entry.cost
        self.steps.append(Step(entry, "check" if check else "probe", before, self.live, expected))

    def ranked_probe(self):
        if len(self.live) == 1 and self.strategy == "active":
            return min((q for q in self.domain.probes if q not in self.used),
                       key=self.domain.costs.__getitem__, default=None)
        best_score = best_affordable_score = None
        best = best_affordable = None
        for q in self.domain.probes:
            if q in self.used:
                continue
            if self.strategy == "fixed":
                return q
            predictions = self.predictions(q)
            counts = Counter(predictions[k] for k in self.live)
            gain = len(self.live) - max(counts.values())
            if not gain:
                continue
            # Worst-case candidates eliminated per (one reset + declared cost).
            score = (Fraction(gain, 1 + self.domain.costs[q]), gain)
            if best_score is None or score > best_score:
                best, best_score = q, score
            if self.affordable(q) and (best_affordable_score is None or score > best_affordable_score):
                best_affordable, best_affordable_score = q, score
        return best_affordable if best_affordable is not None else best

    def decision(self):
        if self.failed:
            reason = "outcome_unknown" if self.steps[-1].entry.error == _PENDING else "observation_failed"
            return "error", reason, None
        if not self.live:
            return "conflict", "no_consistent_rule", None
        single = len(self.live) == 1
        pending = next((q for q in self.domain.checks if q not in self.used), None)
        if single and self.steps and pending is None:
            return "identified", "unique_within_domain", None
        if single and pending is not None:
            q, phase = pending, "check"
        else:
            q, phase = self.ranked_probe(), "probe"
        if q is None:
            return ("unverified", "no_observation", None) if single else ("ambiguous", "probe_set_exhausted", None)
        proposal = Probe(q, self.domain.costs[q], phase)
        return ("unverified" if single else "ambiguous",
                "ready" if self.affordable(q) else "budget", proposal)

    def journal(self, pending=None):
        entries = tuple(s.entry for s in self.steps)
        if pending is not None:
            entries += (pending,)
        return Journal(self.domain.id, entries, self.budget, self.strategy, self.source_id)

    def result(self, decision):
        status, reason, proposal = decision
        model = self.domain.rules[self.live[0]] if status == "identified" else None
        return Result(status, reason, self.live, model, proposal, Budget(len(self.steps), self.cost),
                      self.journal(), tuple(self.steps))


def replay(domain: Domain, journal: Journal, budget: Budget | None = None, *, strategy=None) -> Result:
    """Recompute evidence, survivor history and next decision without calling the environment."""
    limits = budget if budget is not None else journal.budget
    if limits is None:
        raise ValueError("replay needs a budget for this journal")
    session = _Session(domain, limits, journal.strategy if strategy is None else strategy, journal, journal.source_id)
    return session.result(session.decision())


def identify(domain: Domain, observe: Rule, budget: Budget, *, strategy=None,
             journal: Journal | None = None, checkpoint: str | Path | None = None,
             source_id: str | None = None) -> Result:
    """Run a resettable adapter. Budget is cumulative across any resumed journal."""
    if strategy is None:
        strategy = journal.strategy if journal is not None else "active"
    if source_id is not None and (not isinstance(source_id, str) or not source_id):
        raise ValueError("source_id must be a nonempty string")
    if journal is not None and journal.source_id != source_id:
        raise ValueError("journal/adapter source mismatch")
    session = _Session(domain, budget, strategy, journal, source_id)
    if checkpoint is not None:
        session.journal().save(checkpoint)
    while True:
        decision = session.decision()
        if decision[1] != "ready":
            return session.result(decision)
        probe = decision[2]
        # Validate model predictions before spending a request on the adapter.
        session.predictions(probe.actions)
        if checkpoint is not None:
            # Reserve the full query before dispatch. Recovery cannot safely infer
            # whether an interrupted call reached the external system.
            session.journal(Entry(probe.actions, probe.cost, None, _PENDING)).save(checkpoint)
        try:
            answer = _json(observe(probe.actions))
        except Exception as exc:
            entry = Entry(probe.actions, probe.cost, None, f"{type(exc).__name__}: {exc}")
        else:
            entry = Entry(probe.actions, probe.cost, answer)
        session.accept(entry)
        if checkpoint is not None:
            session.journal().save(checkpoint)
