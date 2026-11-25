"""An exact small-batch planner using measured marginal row costs."""

from bisect import bisect_left


def optimal_tasks(costs, k):
    if not 1 <= k <= len(costs) <= 8 or any(
        type(w) is not int or w <= 0 for w in costs
    ):
        raise ValueError(
            "expected up to eight positive integer costs and a valid task count"
        )
    order = sorted(range(len(costs)), key=lambda j: (-costs[j], j))
    loads = [0] * k
    greedy = [[] for _ in range(k)]
    for i in order:
        slot = min(range(k), key=lambda j: (loads[j], j))
        loads[slot] += costs[i]
        greedy[slot].append(i)
    lower = max(costs[order[0]], (sum(costs) + k - 1) // k)
    higher = max(loads)
    best = greedy
    if lower < higher:
        sums = {0}
        for c in costs:
            sums |= {v + c for v in sums}
        targets = sorted(v for v in sums if lower <= v < higher)

        def assign(limit):
            available = [limit] * k
            parts = [[] for _ in range(k)]
            rejected = set()

            def visit(j):
                if j == len(order):
                    return True
                state = (j, tuple(sorted(available)))
                if state in rejected:
                    return False
                index = order[j]
                c = costs[index]
                seen = set()
                for lane, capacity in enumerate(available):
                    if capacity < c or capacity in seen:
                        continue
                    seen.add(capacity)
                    available[lane] -= c
                    parts[lane].append(index)
                    if visit(j + 1):
                        return True
                    parts[lane].pop()
                    available[lane] += c
                rejected.add(state)
                return False

            return parts if visit(0) else None

        a, b = 0, len(targets)
        while a < b:
            m = (a + b) // 2
            found = assign(targets[m])
            if found is not None:
                b = m
                best = found
            else:
                a = m + 1
    return [sorted(p) for p in best if p]


class CalibratedPlanner:
    def __init__(self, table):
        self.table = {int(w): v for w, v in table.items()}
        self.widths = sorted(self.table)
        if not self.widths or any(
            not 1 <= w <= 512 or type(v) is not int or v <= 0
            for w, v in self.table.items()
        ):
            raise ValueError(
                "expected positive integer row costs indexed by widths 1–512"
            )

    def cost(self, w):
        price = self.table.get(w)
        if price is not None:
            return price
        j = bisect_left(self.widths, w)
        if j == 0:
            return self.table[self.widths[0]]
        if j == len(self.widths):
            return self.table[self.widths[-1]]
        a, b = self.widths[j - 1 : j + 1]
        span = b - a
        return ((b - w) * self.table[a] + (w - a) * self.table[b] + span - 1) // span

    def __call__(self, widths, workers):
        return optimal_tasks(
            [self.cost(w) for w in widths], min(workers, len(set(widths)))
        )
