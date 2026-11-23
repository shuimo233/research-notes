"""Compare price-tier formula and first moves to a full-information adversarial decision-tree search."""

from collections import Counter
from itertools import product
import json
from pathlib import Path
from random import Random
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from sequential_check import oracle
from weighted import recommend


def entry(name, low, high, cost, capacity):
    return dict(name=name, low=low, high=high, cost=cost, capacity=capacity)


def row(low, high, request):
    return dict(low=low, high=high, consent=False, effect=False, request=request)


def run():
    totals = Counter()

    def check(problem):
        return oracle(problem, recommend(problem), totals, weighted=True)

    def scenario(b, f, history, menu):
        return dict(max_offer=b, errors=f, history=history, menu=menu)

    fixture = json.loads(Path(__file__).with_name("weighted-example.json").read_text(encoding="utf-8"))
    costs = check(fixture)
    assert [costs[name] for name in ("low-a", "mid-a", "high-a")] == [15, 14, 19], costs
    assert recommend(fixture)["fixed_batch_cost"] == 29
    swapped = {**fixture, "menu": [{**item, "cost": {"low-b":12, "mid-b":3}.get(item["name"],item["cost"])}
                                   for item in fixture["menu"]]}
    swapped_costs = check(swapped)
    assert [swapped_costs[name] for name in ("low-a", "mid-a", "high-a")] == [13, 15, 18], swapped_costs
    # Cross unequal positive/negative interval evidence with free, flat and steeply priced extra readings.
    pairs = [(0, 0), (0, 2), (1, 2), (2, 2), (2, 7), (5, 9)]
    histories = [[], [row(1, 2, True)], [row(1, 2, False), row(2, 2, False)]]
    grid = 0
    for x,y,f,h in product(pairs, pairs, (1, 2), histories):
        menu = [entry(f"{i}-{k}", i, i, cost, f+1 if k == 0 else f)
                for i, prices in enumerate((x,y), 1) for k, cost in enumerate(prices)]
        menu.append(entry("wide", 1, 2, 0, 1))
        check(scenario(2, f, h, menu))
        grid += 1
    rng = Random(929503)
    for case in range(150):
        b = rng.choice((2, 3))
        f = rng.choice((0, 1, 2))
        history = []
        for _ in range(rng.randrange(5)):
            low = rng.randint(1,b)
            record = row(low, rng.randint(low,b), rng.choice((True, False, None)))
            if rng.randrange(4)==0:
                record["consent"] = True
            record["effect"] = record["consent"] if rng.randrange(5) else not record["consent"]
            history.append(record)
        menu = []
        for i in range(1,b+1):
            stock = 2*f+1 if case % 2 else rng.randrange(2*f+2)
            a = rng.randint(0, stock)
            menu.extend([entry(f"{i}:a",i,i,rng.randrange(9),a),
                         entry(f"{i}:b",i,i,rng.randrange(14),stock-a)])
        menu.append(entry("wide",1,b,rng.randrange(3),rng.randrange(2)))
        check(scenario(b,f,history,menu))

    # Independent exhaustive searches with three allowed lies, and with a nontrivial third coordinate.
    for f,b in [(3,2),(1,3),(2,3)]:
        history = [row(i,i,False) for i in range(1,b+1) for _ in range(f)]
        menu = [entry(f"{i}-{k}",i,i,price,1 if k == 0 else f)
                for i in range(1,b+1) for k,price in enumerate((4-i,2*i+1))]
        check(scenario(b, f, history, menu))
    check(scenario(2, 0, [row(1,1,False),row(2,2,False)], []))
    free_reserve = scenario(2,1,[],[entry(f"{i}-{k}",i,i,c,n) for i in (1,2)
                                    for k,(c,n) in enumerate(((0,2),(9,1)))])
    check(free_reserve)
    assert recommend(free_reserve)["worst_case_cost"] == 9
    assert recommend(free_reserve)["fixed_batch_cost"] == 18
    gap_examples = []
    for m, price in ((2,10),(3,100),(20,100),(20,10**6)):
        menu = [entry(f"{i}-{k}",i,i,cost,capacity) for i in range(1,m+1)
                for k,(cost,capacity) in enumerate(((1,2),(price,1)))]
        problem = scenario(m,1,[],menu)
        if m <= 3:
            check(problem)
        result = recommend(problem)
        fixed, adaptive = result["fixed_batch_cost"], result["worst_case_cost"]
        assert (fixed, adaptive) == (m*(2+price), 2*m+price)
        gap_examples.append({"coordinates":m, "extra_price":price, "fixed":fixed, "adaptive":adaptive})
    # Large error budget and sparse menu: the production path must never expand copies or missing prices.
    big = 10**16
    one = recommend(scenario(1,big,[],[entry("first",1,1,2,big),entry("rest",1,1,7,big+1)]))
    assert one["worst_case_cost"] == 9*big+7
    sparse = recommend(scenario(big,1,[],[]))
    assert sparse["status"] == "menu_insufficient"
    return {"seed":929503, "price_history_grid":grid, "random_cases":150, "targeted_oracle_cases":9,
            "first_move_costs":costs, "swapped_repeat_price_first_move_costs":swapped_costs,
            "oracle":dict(sorted(totals.items())),
            "gap_examples":gap_examples,
            "large_capacity_check":big, "large_domain_check":big}


if __name__ == "__main__":
    print(json.dumps(run(),indent=2))
