"""Use a relation table to request only the word senses still needed for a decision."""

from fractions import Fraction


class SenseInquiry:
    def __init__(self, left, right, relation):
        if not callable(relation):
            raise TypeError("relation must map a pair of senses to a label")
        left, right = tuple(sorted(set(left))), tuple(sorted(set(right)))
        self.senses = left, right
        if not all(self.senses):
            raise ValueError("both words need at least one candidate sense")
        self.cells = {(a, b): relation(a, b) for a in left for b in right}
        if None in self.cells.values():
            raise ValueError("None is reserved for an undetermined answer")
        self.constant = self._single(self.cells.values())
        self.after = (
            {a: self._single(self.cells[a, b] for b in right) for a in left},
            {b: self._single(self.cells[a, b] for a in left) for b in right},
        )
        self.rates = tuple(
            Fraction(sum(v is not None for v in side.values()), len(side))
            for side in self.after
        )

    @staticmethod
    def _single(outcomes):
        labels = set(outcomes)
        return next(iter(labels)) if len(labels) == 1 else None

    def first(self, policy="table"):
        left, right = map(len, self.senses)
        if right == 1:
            return 0
        if left == 1:
            return 1
        return {
            "table": int(self.rates[1] > self.rates[0]),
            "left": 0,
            "right": 1,
            "fewer": int(right < left),
            "more": int(right > left),
        }[policy]

    def advance(self, observed, policy="table"):
        """Return ('answer', label) or ('ask', side), with 0 for left and 1 for right."""
        if any(
            side not in (0, 1) or value not in self.senses[side]
            for side, value in observed.items()
        ):
            raise ValueError("answer outside the candidate senses")
        if self.constant is not None:
            return "answer", self.constant
        if len(observed) == 2:
            return "answer", self.cells[observed[0], observed[1]]
        if observed:
            side, value = next(iter(observed.items()))
            label = self.after[side][value]
            return ("answer", label) if label is not None else ("ask", 1 - side)
        return "ask", self.first(policy)

    def replay(self, truth, policy="table"):
        observed = {}
        while True:
            action, result = self.advance(observed, policy)
            if action == "answer":
                return result, tuple(observed)
            observed[result] = truth[result]
