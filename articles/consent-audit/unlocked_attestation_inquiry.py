"""Check a protected attestation from a public packet and two hypothetical records."""

import argparse
import gzip
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from attested_optimality import Exhausted
from attested_optimality_inquiry import inspect
from conclusion_replay_inquiry import parse
from public_optimality import PublicAudit


def check(entry, budget):
    packet = entry["packet"]
    audit = PublicAudit(*parse(packet["archive"]), packet["certificate"])
    result = inspect(entry, budget)
    records = entry["worlds"]
    n = len(audit.fibre)
    if len(records) != 2:
        raise ValueError("two hypothetical records are required")
    for x in records:
        if len(x) != n or any(type(t) is not int for t in x) or x[0] != 0:
            raise ValueError("invalid hypothetical record")
        if any(
            x[j] - x[i] > b
            for i, row in enumerate(audit.fibre)
            for j, b in enumerate(row)
        ):
            raise ValueError("hypothetical record contradicts the public archive")
        if any(x[v] - x[u] < b for u, v, b in entry["attested"]):
            raise ValueError("hypothetical record contradicts a comparison")
    protected = [i for i in range(1, n) if audit.fibre[0][i] > -audit.fibre[i][0]]
    if any(records[0][i] == records[1][i] for i in protected):
        raise ValueError(
            "the two records do not witness all previously unknown positions"
        )
    if result["newly_exact_positions"]:
        raise ValueError("a previously uncertain position is fixed")
    result["non_exact_positions_verified"] = len(protected)
    return result


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("packet", type=Path)
    p.add_argument("--index", type=int, default=0)
    p.add_argument("--budget", type=int, default=100_000)
    args = p.parse_args()
    if args.index < 0 or args.budget < 0:
        p.error("index and budget must be non-negative")
    try:
        raw = args.packet.read_bytes()
        data = json.loads(gzip.decompress(raw) if args.packet.suffix == ".gz" else raw)
        result = check(
            data[args.index] if isinstance(data, list) else data, args.budget
        )
    except (IndexError, KeyError, TypeError, ValueError) as err:
        p.exit(2, f"{err}\n")
    except Exhausted as err:
        result = dict(proved=None, status="unresolved", reason=str(err))
    print(json.dumps(result, indent=2))
