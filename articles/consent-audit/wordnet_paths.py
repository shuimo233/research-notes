"""Read fixed WordNet 3.0 noun senses, corpus counts, and strict hypernym-path evidence."""

from collections import Counter, defaultdict
from functools import lru_cache
import re
from zipfile import ZipFile


NOUN_SUFFIXES = (
    ("s", ""),
    ("ses", "s"),
    ("ves", "f"),
    ("xes", "x"),
    ("zes", "z"),
    ("ches", "ch"),
    ("shes", "sh"),
    ("men", "man"),
    ("ies", "y"),
)


class NounPaths:
    def __init__(self, archive):
        with ZipFile(archive) as z:

            def lines(name):
                return z.read("wordnet/" + name).decode("utf8").splitlines()

            self.parents = {}
            for text in lines("data.noun"):
                if text.startswith(" "):
                    continue
                parts = text.split("|", 1)[0].split()
                i = 4 + 2 * int(parts[3], 16)
                pointers = parts[i + 1 : i + 1 + 4 * int(parts[i])]
                self.parents[int(parts[0])] = sorted(
                    {
                        int(pointers[j + 1])
                        for j in range(0, len(pointers), 4)
                        if pointers[j] in ("@", "@i") and pointers[j + 2] == "n"
                    }
                )
            self.index = {}
            for text in lines("index.noun"):
                if text.startswith(" "):
                    continue
                fields = text.split()
                self.index[fields[0]] = tuple(map(int, fields[-int(fields[2]) :]))
            self.exceptions = {}
            for text in lines("noun.exc"):
                form, *variants = text.split()
                self.exceptions[form] = variants
            self.frequency = Counter()
            for text in lines("cntlist.rev"):
                key, _, count = text.split()
                word, kind = key.split("%", 1)
                if kind.startswith("1:") and re.fullmatch("[a-z]+", word):
                    self.frequency[word] += int(count)
        # Keep graph caches local to this archive and release them with its instance.
        self.ancestors = lru_cache(None)(self._ancestors)

    def senses(self, word):
        word = word.lower()
        variants = self.exceptions.get(word)
        if variants is None:
            variants = [word[: -len(end)] + rep for end, rep in NOUN_SUFFIXES if word.endswith(end)]
        return frozenset(s for w in [word, *variants] for s in self.index.get(w, ()))

    def _ancestors(self, node):
        result = set(self.parents[node])
        for parent in self.parents[node]:
            result.update(self.ancestors(parent))
        return frozenset(result)

    def ranked_words(self, n):
        return sorted(self.frequency, key=lambda w: (-self.frequency[w], w))[:n]

    def reciprocal(self, words):
        owners = defaultdict(set)
        for w in words:
            for syn in self.senses(w):
                owners[syn].add(w)
        directed = set()
        for w in words:
            for s in self.senses(w):
                directed.update((w, v) for p in self.ancestors(s) for v in owners.get(p, ()) if w != v)
        return sorted((a, b) for a, b in directed if a < b and (b, a) in directed), len(directed)

    def paths(self, a, b):
        ends = self.senses(b)

        def visit(node, prefix):
            for parent in self.parents[node]:
                step = prefix + ((node, parent),)
                if parent in ends:
                    yield frozenset(step)
                if ends & self.ancestors(parent):
                    yield from visit(parent, step)

        return {
            path
            for start in self.senses(a)
            if ends & self.ancestors(start)
            for path in visit(start, ())
        }
