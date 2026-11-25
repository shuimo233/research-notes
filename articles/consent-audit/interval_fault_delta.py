"""Exact possible readings and labels when two bad reports exhaust the graph budget."""

from dataclasses import dataclass

from interval_fault_path import _route, _tree, compile_path


def conflict_cycle(size, reports):
    base, tree, tree_edges = _tree(size, reports, None)
    for i, (u, v, value) in enumerate(reports):
        if not tree_edges[i] and base[v] - base[u] != value:
            return (i, *_route(tree, u, v)[1])
    return ()


@dataclass(frozen=True)
class TwoRepairPaths:
    minimum: int
    cycle: tuple
    graph_paths: tuple = ()
    paths: tuple = ()

    def values(self, u, v, *, ignore_intervals=False):
        paths = self.graph_paths if ignore_intervals else self.paths
        return {value for _, path in paths for value in path.values(u, v)}

    def labels(self, u, v, threshold, *, ignore_intervals=False):
        return {
            value >= threshold
            for value in self.values(u, v, ignore_intervals=ignore_intervals)
        }

    def probe_labels(self, source, target, threshold, u, v):
        """Group every feasible probe answer by the target labels it permits."""
        support = {}
        for _, path in self.paths:
            for answer in path.values(u, v):
                labels = path.after_probe(source, target, threshold, u, v, answer)
                support.setdefault(answer, set()).update(labels)
        return support

    def repair_coordinates(self):
        """Normalized coordinates and both wrong report indices, for audit."""
        result = {}
        for omitted, path in self.paths:
            for j, local in zip(path.kept_positions, path.repair_edges, strict=True):
                second = local if local < omitted else local + 1
                key = tuple(sorted((omitted, second)))
                values = tuple(
                    x + path.residual * (p >= j)
                    for x, p in zip(path.base, path.position, strict=True)
                )
                values = tuple(v - values[0] for v in values)
                if key in result:
                    assert result[key] == values
                result[key] = values
        return result


def compile_two(intervals, reports):
    """Find the graph-only minimum capped at 3; produce paths for minimum 2.

    Minimum 3 denotes no graph repair within the two-report budget. A result
    with minimum 2 can have no band-compatible paths.
    """
    size = len(intervals)
    cycle = conflict_cycle(size, reports)
    if not cycle:
        return TwoRepairPaths(0, ())
    limit = 1 + sum(abs(d) for _, _, d in reports)
    unrestricted = [(-limit, limit)] * size
    graph_paths, paths = [], []
    for i in cycle:
        retained = reports[:i] + reports[i + 1 :]
        if not conflict_cycle(size, retained):
            return TwoRepairPaths(1, cycle)
        graph = compile_path(unrestricted, retained)
        if not graph.repair_edges:
            continue
        graph_paths.append((i, graph))
        bounded = compile_path(intervals, retained)
        if bounded.repair_edges:
            paths.append((i, bounded))
    if not graph_paths:
        return TwoRepairPaths(3, cycle)
    return TwoRepairPaths(2, cycle, tuple(graph_paths), tuple(paths))


def signed_sums(residuals):
    sums = {0}
    for d in residuals:
        sums = {a + shift for a in sums for shift in (-d, 0, d)}
    return sums


def label_ranges(support):
    """Canonical interval form shared by the finite and general-budget results."""
    from interval_fault_cut import merge_ranges

    return [
        merge_ranges(
            (answer, answer) for answer, labels in support.items() if flag in labels
        )
        for flag in (False, True)
    ]
