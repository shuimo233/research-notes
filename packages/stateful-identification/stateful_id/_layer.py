"""Joint record feasibility for a compatible layer plus a cube-free median factor."""

from itertools import combinations_with_replacement


def tree_layer(edges):
    """Try independent sets meeting every triangle. None means use the general solver."""
    neighbors = {}
    for a, b in edges:
        neighbors.setdefault(a, set()).add(b)
        neighbors.setdefault(b, set()).add(a)
    triangles = [(a, b, c) for a, b in edges for c in neighbors[a] & neighbors[b] if c > max(a, b)]
    if not triangles:
        return set()
    # Every valid layer hits the first triangle. Try its three possible seeds;
    # a greedy miss can cost planning time but cannot change the verdict.
    for first in triangles[0]:
        chosen, blocked = {first}, set(neighbors[first])
        remaining = [t for t in triangles if first not in t]
        while remaining:
            scores = {}
            for triangle in remaining:
                options = [c for c in triangle if c not in blocked]
                if not options:
                    break
                for c in options:
                    scores[c] = scores.get(c, 0) + 1
            else:
                col = max(scores, key=lambda c: (scores[c], -c))
                chosen.add(col)
                blocked.update(neighbors[col])
                remaining = [t for t in remaining if col not in t]
                continue
            break
        if not remaining:
            return chosen
    return None


def _distances(columns, size):
    distances = [[0] * size for _ in range(size)]
    for i in range(size):
        for j in range(i):
            d = sum(n for mask, n in columns if ((mask >> i) ^ (mask >> j)) & 1)
            distances[i][j] = distances[j][i] = d
    return distances


def joint_witness(columns, radii, layer, *, minimize=False):
    """Return at most eight local row indices proving emptiness, or None for overlap."""
    size = len(radii)
    tree = _distances([(c,n) for c,n in columns.items() if c in layer], size)
    base = _distances([(c,n) for c,n in columns.items() if c not in layer], size)
    core = _certificate(tree, base, radii)
    if core is not None and minimize:
        for i in core:
            keep = tuple(j for j in core if j != i)
            if not keep:
                continue
            t = [[tree[a][b] for b in keep] for a in keep]
            g = [[base[a][b] for b in keep] for a in keep]
            if _certificate(t, g, [radii[j] for j in keep]) is not None:
                core = keep
    return core


def _certificate(tree, base, radii):
    size = len(radii)
    depths = tree[0]
    core = set()
    for parity in (0, 1):
        limits = [r - ((r + depths[i] + base[0][i] + parity) % 2) for i, r in enumerate(radii)]
        gate_depth, endpoint, source = 0, 0, (0, 0)
        for i, j in combinations_with_replacement(range(size), 2):
            slack = limits[i] + limits[j] - base[i][j] - tree[i][j]
            if slack < 0:
                core.update((i, j))
                break
            # Closest point to the root in this thickened i--j path lies
            # on root--i, at LCA(i,j) depth minus the thickening radius.
            lca = (depths[i] + depths[j] - tree[i][j]) // 2
            depth = max(0, lca - slack // 2)
            if depth > gate_depth:
                gate_depth, endpoint, source = depth, i, (i, j)
        else:
            at_gate = []
            for i in range(size):
                lca = (depths[i] + depths[endpoint] - tree[i][endpoint]) // 2
                at_gate.append(depths[i] + gate_depth - 2 * min(gate_depth, lca))
            for i, j in combinations_with_replacement(range(size), 2):
                if at_gate[i] + at_gate[j] + base[i][j] > limits[i] + limits[j]:
                    # Two intersecting subtrees must contain the deeper of their gates.
                    core.update((*source, i, j))
                    break
            else:
                return None
    return tuple(sorted(core))
