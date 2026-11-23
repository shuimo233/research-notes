"""Choose the fewest fixed SAME queries for a given supplemental field width."""

import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from run_receipt import RunReceipt, ceil_log2


def capacity(checks, symbols):
    if type(checks) is not int or checks < 0 or type(symbols) is not int or symbols < 1:
        raise ValueError("checks >= 0 and symbols >= 1 must be integers")
    limit = 1 << symbols
    if checks == 0:
        return limit
    uncovered = 2*checks*limit - 3*checks + 2
    covered = (2*checks-1)*limit - 2*checks + 2
    return max(uncovered, covered)


def design(n, extra_bits):
    if type(n) is not int or n < 2 or type(extra_bits) is not int or extra_bits < 0:
        raise ValueError("need n >= 2 and a nonnegative integer field width")
    free_symbols = ceil_log2(n)
    if extra_bits >= ceil_log2(free_symbols):
        return {"n":n, "intervals":[]}
    symbols = 1 << extra_bits
    limit = 1 << symbols
    low, high = 1, (n+1)//2
    while low < high:
        mid = (low+high)//2
        if capacity(mid, symbols) >= n:
            high = mid
        else:
            low = mid+1
    q = low
    empty_first = q < limit
    # Cell order: optional uncovered prefix, single 0, overlap 0/1, single 1, etc.
    # Overlaps have length zero in the no-extra-label degeneration.
    offset = limit if empty_first else 0
    single = limit - int(empty_first)
    overlap = limit - 2
    intervals = []
    for i in range(q):
        start = offset + 1 - (overlap if i else 0)
        end = offset + single + (overlap if i < q-1 else 0)
        if start <= n:
            intervals.append([start, min(end,n)])
        offset += single + (overlap if i < q-1 else 0)
    return {"n":n, "intervals":intervals}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("cuts", type=int)
    parser.add_argument("--bits", required=True, type=int)
    args = parser.parse_args()
    try:
        plan = design(args.cuts, args.bits)
        compiled = RunReceipt(plan["n"], plan["intervals"])
        print(json.dumps({**plan,"minimum_checks":len(plan["intervals"]),
                          "extra_bits_used":compiled.bits}, indent=2))
    except ValueError as error:
        parser.exit(2, f"{error}\n")
