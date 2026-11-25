"""Cross-check exact allocations by enumerating small assignments."""

from itertools import product
import json
from random import Random

from audit_runtime_calibration import CalibratedPlanner, optimal_tasks


def tests():
    rng = Random(7765)
    tasks = 0
    for n in range(1, 8):
        for k in range(1, min(n, 4) + 1):
            for _ in range(4):
                values = [rng.randrange(1, 20) * 10003 for _ in range(n)]
                jobs = optimal_tasks(values, k)
                assert (
                    sorted(j for b in jobs for j in b) == list(range(n))
                    and len(jobs) <= k
                )
                actual = max(sum(values[i] for i in b) for b in jobs)
                best = min(
                    max(
                        sum(v for v, j in zip(values, z, strict=True) if j == b)
                        for b in range(k)
                    )
                    for z in product(range(k), repeat=n)
                )
                assert actual == best
                tasks += 1
    fixed = [1900003, 1700277, 1700277, 1300099, 1100001, 500001, 500001, 500001]
    jobs = optimal_tasks(fixed, 4)
    alternate = [sum(fixed[i] for i in b) for b in ((0, 5), (1, 6), (2, 7), (3, 4))]
    assert max(sum(fixed[i] for i in b) for b in jobs) == max(alternate) == 2400100
    profile = CalibratedPlanner({"16": 100, "32": 300, "64": 1000})
    assert [profile.cost(w) for w in (1, 16, 20, 32, 64, 128)] == [
        100,
        100,
        150,
        300,
        1000,
        1000,
    ]
    return {"brute_force": tasks + 1, "interpolation_checks": 6}


if __name__ == "__main__":
    print(json.dumps(tests()))
