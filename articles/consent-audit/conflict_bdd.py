"""A reduced ordered BDD checker for finite evidence conditions, using Shannon expansion."""

from functools import lru_cache
from math import inf


class Diagram:
    def __init__(self):
        self.nodes = [None, None]
        self.unique = {}
        self.join = lru_cache(None)(self._join)
        self.restrict = lru_cache(None)(self._restrict)
        self.distance = lru_cache(None)(self._distance)

    def node(self, i, low, high):
        if low == high:
            return low
        entry = (i, low, high)
        if entry not in self.unique:
            self.unique[entry] = len(self.nodes)
            self.nodes.append(entry)
        return self.unique[entry]

    def _join(self, op, a, b):
        if a < 2 and b < 2:
            return int({"and": a and b, "or": a or b, "xor": a != b}[op])
        va = self.nodes[a][0] if a >= 2 else inf
        vb = self.nodes[b][0] if b >= 2 else inf
        i = min(va, vb)
        al, ah = self.nodes[a][1:] if va == i else (a, a)
        bl, bh = self.nodes[b][1:] if vb == i else (b, b)
        return self.node(i, self.join(op, al, bl), self.join(op, ah, bh))

    def _restrict(self, root, i, value):
        if root < 2:
            return root
        var, lo, hi = self.nodes[root]
        if var > i:
            return root
        if var == i:
            return hi if value else lo
        return self.node(var, self.restrict(lo, i, value), self.restrict(hi, i, value))

    def _distance(self, root):
        if root < 2:
            return 0 if root else inf
        _, lo, hi = self.nodes[root]
        return min(1 + self.distance(lo), self.distance(hi))

    def at(self, root, world):
        while root >= 2:
            i, lo, hi = self.nodes[root]
            root = hi if world & (1 << i) else lo
        return bool(root)

    def family(self, paths, index):
        r = 0
        for path in paths:
            branch = 1
            for i in sorted((index[e] for e in path), reverse=True):
                branch = self.node(i, 0, branch)
            r = self.join("or", r, branch)
        return r

    def polarity(self, root, i):
        lo, hi = self.restrict(root, i, 0), self.restrict(root, i, 1)
        up = self.join("and", self.join("xor", lo, 1), hi) != 0
        down = self.join("and", lo, self.join("xor", hi, 1)) != 0
        return up, down
