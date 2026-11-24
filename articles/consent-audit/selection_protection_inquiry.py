"""Verify a public selection policy or publish a single cached attestation."""

import argparse
import gzip
from hashlib import sha256
import json
import os
from pathlib import Path
from secrets import choice
import sys
from tempfile import NamedTemporaryFile

sys.path.insert(0, str(Path(__file__).resolve().parent))
from attested_optimality_check import DirectOracle
from lag_protection import verify_rational
from selection_protection import selected_by_bases, true_indices
from selection_protection_check import compile_independently, verify_bases, verify_order


def checked(entry):
    p = entry["packet"]
    authority = DirectOracle(p, entry["groups"])
    labels = [r["comparison"] for r in entry["entries"]]
    if labels != compile_independently(authority, entry["grid"]):
        raise ValueError(
            "the public catalogue is incomplete or contains an invalid comparison"
        )
    for r in entry["entries"]:
        verify_rational(
            authority.n, authority.original, [r["comparison"]], r["rational"]
        )
    verify_bases(authority, labels, entry["basis_plan"])
    verify_order(authority, labels, entry["priority"])
    return authority, labels


def once(record, entry, authority, comparisons, method, destination, weights=None):
    if (
        len(record) != authority.n
        or any(type(x) is not int for x in record)
        or record[0] != 0
        or any(record[v] - record[u] > c for u, v, c in authority.original)
    ):
        raise ValueError("record is inconsistent with the public archive")
    ids = true_indices(record, comparisons)
    if not ids:
        raise ValueError("the catalogue has no compatible release")
    scope = entry
    if method == "weighted":
        if (
            weights is None
            or len(weights) != len(comparisons)
            or any(w <= 0 for w in weights)
        ):
            raise ValueError("weighted release needs positive weights for every label")
        scope = dict(catalogue=entry, weights=list(map(str, weights)))
    context = sha256(
        json.dumps(scope, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    if not destination.exists():
        if method == "random":
            label = choice(ids)
        elif method == "weighted":
            from selection_odds import choose_weighted

            label = choose_weighted(ids, weights)
        elif method == "priority":
            if entry["priority"]["status"] != "proved":
                raise ValueError("this catalogue has no verified priority order")
            label = next(i for i in entry["priority"]["order"] if i in ids)
        else:
            label = selected_by_bases(record, comparisons, entry["basis_plan"]["bases"])
        public = dict(
            catalogue=context, method=method, label=label, **entry["entries"][label]
        )
        with NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=destination.parent, delete=False
        ) as f:
            path = Path(f.name)
            f.write(json.dumps(public, indent=2) + "\n")
            f.flush()
        try:
            try:
                os.link(path, destination)
            except FileExistsError:
                pass
        finally:
            path.unlink()
    prior = json.loads(destination.read_bytes())
    selected = prior["label"]
    if (
        prior["catalogue"] != context
        or prior["method"] != method
        or type(selected) is not int
        or selected not in ids
        or prior
        != dict(
            catalogue=context,
            method=method,
            label=selected,
            **entry["entries"][selected],
        )
    ):
        raise ValueError("cached release does not match this request")
    if method not in ("random", "weighted"):
        expected = (
            next(i for i in entry["priority"]["order"] if i in ids)
            if method == "priority"
            else selected_by_bases(record, comparisons, entry["basis_plan"]["bases"])
        )
        if selected != expected:
            raise ValueError("cached release does not follow the prescribed rule")
    return prior


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("action", choices=("check", "publish"))
    p.add_argument("packets", type=Path)
    p.add_argument("--index", type=int, default=0)
    p.add_argument("--record", type=Path)
    p.add_argument("--release-file", type=Path)
    p.add_argument("--method", choices=("bases", "priority", "random"), default="bases")
    args = p.parse_args()
    if args.index < 0:
        p.error("packet index must be nonnegative")
    if args.action == "publish" and (args.record is None or args.release_file is None):
        p.error("publish requires a local record and a release file")
    try:
        raw = args.packets.read_bytes()
        data = json.loads(gzip.decompress(raw) if args.packets.suffix == ".gz" else raw)
        entry = data[args.index] if isinstance(data, list) else data
        authority, atoms = checked(entry)
        if args.action == "check":
            result = dict(
                job=entry.get("job"), labels=len(atoms), protects_affine_hull=True
            )
        else:
            record = json.loads(args.record.read_bytes())
            result = once(
                record, entry, authority, atoms, args.method, args.release_file
            )
    except (OSError, TypeError, ValueError, KeyError, IndexError, AssertionError) as e:
        p.exit(2, f"{e}\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    if not __debug__:
        raise RuntimeError("enable assertions")
    main()
