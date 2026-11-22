"""Independent exact dual LP on every support of size at most four (small feasible test tables)."""

from fractions import Fraction
from itertools import combinations, product
import json
from math import floor, ceil
from pathlib import Path
from random import Random
import runpy

exp = runpy.run_path(str(Path(__file__).with_name("experiment.py")))


def axis_solutions(normals):
    d,k = len(normals[0]),len(normals)
    a = [[Fraction(v[j]) for v in normals] + [Fraction(i == j) for i in range(d)] for j in range(d)]
    for col in range(k):
        pivot = next((i for i in range(col,d) if a[i][col]), None)
        if pivot is None:
            return
        a[col],a[pivot] = a[pivot],a[col]
        a[col] = [v/a[col][col] for v in a[col]]
        for i in range(d):
            if i != col and a[i][col]:
                a[i] = [v-a[i][col]*w for v,w in zip(a[i],a[col])]
    for j in range(d):
        if any(row[k+j] for row in a[k:]):
            continue
        weights = [row[k+j] for row in a[:k]]
        if all(x >= 0 for x in weights) or all(x <= 0 for x in weights):
            yield j, weights


def oracle(rows,sizes,radii):
    normals = [[1-2*b for b in row] for row in rows]
    rhs = [r-sum(n*b for n,b in zip(sizes,row)) for r,row in zip(radii,rows)]
    lo,hi = [0]*len(sizes), sizes[:]
    examined = 0
    for k in range(1,5):
        for ids in combinations(range(len(rows)),k):
            examined += 1
            for j,w in axis_solutions([normals[i] for i in ids]):
                value = sum(value*rhs[i] for value,i in zip(w,ids))
                if min(w) >= 0:
                    hi[j] = min(hi[j],floor(value))
                else:
                    lo[j] = max(lo[j],ceil(value))
    return list(zip(lo,hi)), examined


def run():
    rng = Random(771136)
    examined, better, tested = 0,0,0
    for trial in range(32):
        d = 4 + trial%2
        rows = rng.sample(list(product((0,1),repeat=d)),rng.randint(6,11))
        sizes = [rng.randint(4,20) for _ in range(d)]
        z = [rng.randrange(n+1) for n in sizes]
        radii = [exp["distance"](row,sizes,z)+rng.randrange(4) for row in rows]
        cols = exp["columns"](rows,sizes)
        if len(cols) != d:
            continue
        expected, count = oracle(rows,sizes,radii)
        actual = exp["four_intervals"](cols,radii)
        exp["check"](expected == actual,(rows,radii,expected,actual))
        examined += count
        better += exp["count_intervals"](cols,radii) != actual
        tested += 1
    return {"tables":tested,"supports_examined":examined,"four_strictly_better_than_two":better}


if __name__ == "__main__":
    print(json.dumps(run(),indent=2))
