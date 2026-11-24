"""Solve the preregistered fixed-marginal release targets using exact transport cuts."""

import argparse
from fractions import Fraction
import gzip
from hashlib import sha1
import json
from pathlib import Path

from denial_odds import distribution, ratio_of
from denial_odds_run import solve as denial
from joint_odds import (
    bounded_transport,
    check_negative,
    check_rows,
    cut,
    diagnose,
    focus,
    project,
    semantics,
    simple,
)
from selection_odds_run import rational

PIN = "6a2816703f9a7569cce1c98f061fa5bc5fb5321b"
SERVICE = Fraction(1, 2)


def read(path):
    data = path.read_bytes()
    if sha1(f"blob {len(data)}\0".encode() + data).hexdigest() != PIN:
        raise ValueError("not the preregistered policy bundle")
    return json.loads(gzip.decompress(data))


def enough(weights, ratio, worlds):
    rows, violations = [], []
    for k, (left, right) in enumerate(worlds):
        row, separated = bounded_transport(left, right, weights, ratio)
        if separated is not None:
            violations.append((k, *separated))
        rows.append(row)
    return rows, violations


def vertex(guess, equations):
    """Recover a basic solution by elimination over its nonzero columns."""
    columns = [j for j, x in enumerate(guess) if x > 1e-10]
    size = len(columns)
    pivots = {}
    for lhs, rhs in equations:
        row = [Fraction(lhs[j]) for j in columns] + [Fraction(rhs)]
        for i in sorted(pivots):
            if row[i]:
                row = [a - row[i] * b for a, b in zip(row, pivots[i], strict=True)]
        index = next((i for i in range(size) if row[i]), None)
        if index is None:
            continue
        pivots[index] = [a / row[index] for a in row]
        if len(pivots) == size:
            break
    if len(pivots) != size:
        raise ArithmeticError("numeric basis does not determine a rational vertex")
    answer = [Fraction(0)] * len(guess)
    for i in reversed(range(size)):
        row = pivots[i]
        answer[columns[i]] = row[-1] - sum(
            row[j] * answer[columns[j]] for j in range(i + 1, size)
        )
    return answer


def master(worlds, floor, ratio, cuts):
    from scipy import __version__
    from scipy.optimize import linprog

    if __version__ != "1.16.3":
        raise RuntimeError("this replay pins scipy 1.16.3")
    rows = []
    limits = []
    cells = list(floor)
    for k, I, J in cuts:
        coeff, demand = cut(*worlds[k], I, J, ratio)
        rows.append([-1, *(-coeff.get(cell, 0) for cell in cells)])
        limits.append(
            sum(value * floor[cell] for cell, value in coeff.items()) - demand
        )
    objective = [1, *([0] * len(cells))]
    result = linprog(
        objective,
        A_ub=[list(map(float, row)) for row in rows],
        b_ub=list(map(float, limits)),
        method="highs",
    )
    if not result.success:
        raise ArithmeticError(result.message)
    point = list(map(rational, result.x))

    def admissible(x):
        return min(x) >= 0 and all(
            sum(a * b for a, b in zip(row, x, strict=True)) <= limit
            for row, limit in zip(rows, limits, strict=True)
        )

    if not admissible(point):
        point = vertex(
            result.x,
            (
                (row, limit)
                for row, limit, slack in zip(
                    rows, limits, result.ineqlin.residual, strict=True
                )
                if abs(slack) <= 1e-8
            ),
        )
        if not admissible(point):
            raise ArithmeticError("reconstructed master optimum is infeasible")
    if not point[0]:
        return {
            cell: floor[cell] + v for cell, v in zip(cells, point[1:], strict=True)
        }, None

    guess = -result.ineqlin.marginals

    def certificate(solution):
        return [(*key, p) for key, p in zip(cuts, solution, strict=True) if p > 0]

    prices = certificate(list(map(rational, guess)))
    try:
        check_negative(worlds, floor, ratio, prices)
    except ValueError:
        column_rows = zip(*rows, strict=True)
        prices = certificate(
            vertex(
                guess,
                (
                    ([-a for a in column], c)
                    for column, c, slack in zip(
                        column_rows, objective, result.lower.marginals, strict=True
                    )
                    if abs(slack) <= 1e-8
                ),
            )
        )
        check_negative(worlds, floor, ratio, prices)
    return None, prices


def feasible(worlds, floor, ratio):
    cuts = {}
    weights = floor
    for _ in range(1000):
        rows, violations = enough(weights, ratio, worlds)
        if not violations:
            check_rows(worlds, floor, ratio, rows)
            return dict(
                status="feasible",
                actual_ratio=str(ratio_of(rows)),
                weights=[str(weights[cell]) for cell in floor],
                rows=[[str(row[cell]) for cell in sorted(row)] for row in rows],
                cuts=len(cuts),
            )
        if all(key in cuts for key in violations):
            raise ArithmeticError(
                "numeric weights failed exact reconstruction of the master LP"
            )
        cuts.update(dict.fromkeys(violations))
        weights, negative = master(worlds, floor, ratio, cuts)
        if negative is not None:
            check_negative(worlds, floor, ratio, negative)
            return dict(
                status="infeasible",
                certificate=[
                    [k, list(I), list(J), str(price)] for k, I, J, price in negative
                ],
                cuts=len(cuts),
            )
    raise ArithmeticError("cut iteration limit")


def worlds_for(views, modes):
    return [
        tuple(
            distribution(weights, mask, SERVICE)
            for weights, mask in zip(views, m, strict=True)
        )
        for m in modes
    ]


def make(packet):
    catalogue = packet["catalogue"]
    selected = focus(catalogue["entries"])
    if not selected:
        return dict(job=catalogue["job"], status="only_one_view")
    modes = sorted(
        {
            tuple(project(mask, ids) for _, ids in selected)
            for mask in [0, *packet["patterns"]]
        }
    )
    views = []
    for column, (event, ids) in enumerate(selected):
        possible = sorted({mode[column] for mode in modes} - {0})
        views.append(
            dict(
                event=event, labels=ids, certificate=denial(len(ids), possible, SERVICE)
            )
        )
    weights = [list(map(Fraction, row["certificate"]["weights"])) for row in views]
    worlds = worlds_for(weights, modes)
    floor, marginal, independent = semantics(worlds)
    bounds = [marginal, (marginal + independent) / 2]
    targets = {str(r): feasible(worlds, floor, r) for r in sorted(set(bounds))}
    diagnostics = {r: diagnose(worlds, floor, Fraction(r)) for r in targets}
    assert all(
        d is None or targets[r]["status"] == "infeasible"
        for r, d in diagnostics.items()
    )
    simple_seeds = [
        ratio_of([simple(l, r, same) for l, r in worlds]) for same in (True, False)
    ]
    return dict(
        job=catalogue["job"],
        status="scored",
        views=views,
        modes=modes,
        floor=[[i, j, str(p)] for (i, j), p in floor.items()],
        marginal=str(marginal),
        independent=str(independent),
        midpoint=str(bounds[1]),
        simple=dict(zip(("shared", "opposed"), map(str, simple_seeds), strict=True)),
        targets=targets,
        post_hoc_diagnostics=diagnostics,
    )


def summarize(packets):
    scored = [p for p in packets if p["status"] == "scored"]
    main = [
        p
        for p in scored
        if Fraction(p["independent"]) > Fraction(p["marginal"])
        and p["targets"][p["midpoint"]]["status"] == "feasible"
    ]
    return dict(
        catalogues=len(packets),
        scored=len(scored),
        skipped=len(packets) - len(scored),
        modes=sum(len(p["modes"]) for p in scored),
        certified_targets=sum(len(p["targets"]) for p in scored),
        rejected_by_cell_check=sum(
            d is not None and d["kind"] == "cell"
            for p in scored
            for d in p["post_hoc_diagnostics"].values()
        ),
        rejected_by_marginal_check=sum(
            d is not None and d["kind"] != "cell"
            for p in scored
            for d in p["post_hoc_diagnostics"].values()
        ),
        baseline_gap=sum(
            Fraction(p["independent"]) > Fraction(p["marginal"]) for p in scored
        ),
        improved=len(main),
        reach_marginal=sum(
            p["targets"][p["marginal"]]["status"] == "feasible" for p in scored
        ),
        simpler_reaches_improvement=sum(
            min(map(Fraction, p["simple"].values())) <= Fraction(p["midpoint"])
            for p in main
        ),
        best_tested_worst_ratio=str(
            max(
                min(
                    [max(Fraction(p["marginal"]), Fraction(p["independent"]))]
                    + [
                        max(Fraction(p["marginal"]), Fraction(t["actual_ratio"]))
                        for t in p["targets"].values()
                        if t["status"] == "feasible"
                    ]
                )
                for p in scored
            )
        ),
        independent_worst_ratio=str(
            max(
                max(Fraction(p["marginal"]), Fraction(p["independent"])) for p in scored
            )
        ),
        gate=len(packets) == 25 and len(main) >= 5,
    )


def run(path, output):
    packets = [make(x) for x in read(path)]
    report = summarize(packets)
    output.mkdir(parents=True, exist_ok=True)
    (output / "joint-odds-policies.json.gz").write_bytes(
        gzip.compress(
            json.dumps(packets, separators=(",", ":"), ensure_ascii=True).encode(),
            mtime=0,
        )
    )
    (output / "joint-odds-results.json").write_text(
        json.dumps(report, indent=2) + "\n", encoding="utf-8", newline="\n"
    )
    print(json.dumps(report))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    run(args.source, args.output)
