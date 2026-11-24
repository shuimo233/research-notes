"""Check the exact public proof and a single rational lag-protection certificate."""

import argparse
import gzip
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from attested_optimality import Exhausted
from attested_optimality_inquiry import inspect
from lag_protection import verify_rational
from public_optimality_check import raw
from slack_certificate_check import attach


def verify(entry, budget):
    packet = entry["packet"]
    n, original, _ = raw(packet)
    original = attach(original, packet["certificate"]["disclosed"])
    result = inspect(entry, budget)
    r = verify_rational(n, original, entry["attested"], entry["rational"])
    return dict(
        **result,
        rigid_classes_preserved=r,
        affine_dimension=r - 1,
        hypothetical_integer_tables=r,
    )


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("packet", type=Path)
    p.add_argument("--index", type=int, default=0)
    p.add_argument("--budget", type=int, default=100_000)
    a = p.parse_args()
    if a.index < 0 or a.budget < 0:
        p.error("index and budget must be non-negative")
    try:
        data = a.packet.read_bytes()
        packet = json.loads(gzip.decompress(data) if a.packet.suffix == ".gz" else data)
        result = verify(
            packet[a.index] if isinstance(packet, list) else packet, a.budget
        )
    except (IndexError, KeyError, TypeError, ValueError, AssertionError) as err:
        p.exit(2, f"{err}\n")
    except Exhausted as err:
        result = dict(proved=None, status="unresolved", reason=str(err))
    print(json.dumps(result, indent=2))
