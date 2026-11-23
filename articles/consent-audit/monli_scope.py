"""Transport an identified lexical inclusion through a known downward-monotone slot."""

from collections import deque
from dataclasses import dataclass
import re


WORD = r"[a-z]+(?:[-'][a-z]+)*"
TOKENS = re.compile(WORD + r"|[^a-z\s]")


def affirmative(sentence):
    if len(re.findall(r"\bnot\b", sentence, flags=re.IGNORECASE)) != 1:
        raise ValueError("need a single explicit 'not' in the licensed downward frame")
    text, changed = re.subn(
        r"^(there is) not a single\b", r"\1 at least one", sentence, flags=re.IGNORECASE
    )
    if not changed:
        text, removed = re.subn(r"\bnot\b\s+", "", text, flags=re.IGNORECASE)
        if not removed:
            raise ValueError("the negative marker must precede a complement")
    text = re.sub(r"\bany\b", "some", text, flags=re.IGNORECASE)
    return re.sub(r"\s+at all\b", "", text, flags=re.IGNORECASE)


def changed_terms(left, right):
    a, b = (TOKENS.findall(s.casefold()) for s in (left, right))
    start, end_a, end_b = 0, len(a), len(b)
    while start < min(end_a, end_b) and a[start] == b[start]:
        start += 1
    while min(end_a, end_b) > start and a[end_a - 1] == b[end_b - 1]:
        end_a -= 1
        end_b -= 1
    a, b = ([w for w in span if w not in ("a", "an")] for span in (a[start:end_a], b[start:end_b]))
    if len(a) == len(b) == 1 and a != b and all(re.fullmatch(WORD, w) for w in (a[0], b[0])):
        return a[0], b[0]
    return None


class LexicalEvidence:
    """An edge records the first supplied positive-context source row entailing its target."""

    def __init__(self, rows):
        self.edges = {}
        for line, row in enumerate(rows, 1):
            if row["gold_label"] == "entailment":
                terms = changed_terms(row["sentence1"], row["sentence2"])
                if terms:
                    a, b = terms
                    self.edges.setdefault(a, {}).setdefault(b, line)

    def shortest(self, start, end):
        queue = deque([start])
        previous = {start: None}
        while queue:
            word = queue.popleft()
            if word == end:
                lines = []
                while previous[word] is not None:
                    word, line = previous[word]
                    lines.append(line)
                return tuple(reversed(lines))
            for nxt, line in sorted(self.edges.get(word, {}).items()):
                if nxt not in previous:
                    previous[nxt] = word, line
                    queue.append(nxt)
        return ()

    def downward(self, left, right):
        terms = changed_terms(left, right)
        if terms:
            a, b = terms
            forward, reverse = self.shortest(a, b), self.shortest(b, a)
            if bool(forward) != bool(reverse):
                return Decision("reverse" if forward else "forward", "evidence", forward or reverse)
        return None


@dataclass(frozen=True)
class Decision:
    direction: str
    basis: str
    source_lines: tuple = ()


def opposite(direction):
    return {"forward": "reverse", "reverse": "forward", "abstain": "abstain"}[direction]


def decide_downward_pair(left, right, evidence, compare):
    """Both directions describe one known strict inclusion in a known downward context.

    compare takes the two affirmative sentences and returns forward/reverse/abstain.
    A uniquely grounded path skips this call. Callers establish the semantic preconditions.
    """
    a, b = affirmative(left), affirmative(right)
    proof = evidence.downward(left, right)
    if proof is not None:
        return proof
    return Decision(opposite(compare(a, b)), "affirmative-model")
