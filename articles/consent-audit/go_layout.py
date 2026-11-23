"""Export a changed-output patch for a second inference layout and replay its fixed predictions."""
import argparse
import csv
from fractions import Fraction
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from go_model_score import audit
from go_model_bounds import Baseline, Item, sharp
from goemotions_fetch import verify

PRED = ("fp32", "int8", "top1", "fine_fp32", "fine_int8", "fine_top1")
HEADER = ("id", "released", "people", *PRED)


def table(path, header):
    result = {}
    with path.open(encoding="utf8", newline="") as stream:
        reader = csv.DictReader(stream, delimiter="\t")
        if tuple(reader.fieldnames or ()) != header:
            raise ValueError("unexpected table columns")
        for row in reader:
            k = row["id"]
            if not k or k in result:
                raise ValueError("empty or duplicate key")
            result[k] = {column: int(row[column]) for column in header if column != "id"}
    return result


def write(path, header, values):
    with path.open("x", encoding="utf8", newline="") as stream:
        writer = csv.writer(stream, delimiter="\t", lineterminator="\n")
        writer.writerow(header)
        for key, row in sorted(values.items()):
            writer.writerow([key, *(row[k] for k in header if k != "id")])


def export(base, candidate, dest):
    old, new = table(base, HEADER), table(candidate, HEADER)
    if old.keys() != new.keys() or any((v["released"], v["people"]) !=
            (new[k]["released"], new[k]["people"]) for k, v in old.items()):
        raise ValueError("batch layouts must share IDs and both references")
    changed = {k: v for k, v in new.items() if v != old[k]}
    write(dest, ("id", *PRED), changed)


def fine_metrics(predicted, gold):
    total = sum(p == g for p, g in zip(predicted, gold))
    f1 = Fraction(0)
    for i in range(28):
        mask = 1 << i
        p = sum(bool(v & mask) for v in predicted)
        g = sum(bool(v & mask) for v in gold)
        t = sum(bool(a & b & mask) for a, b in zip(predicted, gold))
        f1 += Fraction(2 * t, max(1, p + g))
    return {"exact_matches": total, "macro_f1": str(f1 / 28)}


def shared_gold_gain(old, new):
    """INT8 eight minus INT8 single under the same reference for each comment."""
    p8 = p1 = g = t8 = t1 = 0
    choices = []
    for key, row in old.items():
        a, b = new[key]["int8"], row["int8"]
        original = row["released"]
        p8 += a.bit_count()
        p1 += b.bit_count()
        g += original.bit_count()
        t8 += (a & original).bit_count()
        t1 += (b & original).bit_count()
        extra = row["people"] ^ original
        if extra:
            choices.append(Item(key, extra.bit_count(), (extra & a).bit_count(), (extra & b).bit_count()))
    return sharp(Baseline(g, p8, p1, t8, t1), choices)


def replay(base, delta, data, restored):
    old = table(base, HEADER)
    patch = table(delta, ("id", *PRED))
    if not patch.keys() <= old.keys():
        raise ValueError("patch references extra keys")
    new = {k: {**v, **patch.get(k, {})} for k, v in old.items()}
    if any(new[k] == old[k] for k in patch):
        raise ValueError("unchanged row in output patch")
    verify(data / "test.tsv", "test.tsv")
    with (data / "test.tsv").open(encoding="utf8", newline="") as stream:
        fine = {k: sum(1 << int(x) for x in ids.split(",")) for _, ids, k in
                csv.reader(stream, delimiter="\t", quoting=csv.QUOTE_NONE)}
    if old.keys() != fine.keys():
        raise ValueError("official test IDs differ")
    ids = sorted(fine)
    report = audit(list(new.items()))
    if restored is not None:
        write(restored, HEADER, new)
    changes = {col: sum(v[col] != new[k][col] for k, v in old.items()) for col in PRED}
    return {"items": len(ids), "patch_rows": len(patch), "changed_decisions_by_column": changes,
            "fine": {name: {rule: fine_metrics([rows[k]["fine_" + rule] for k in ids],
                                               [fine[k] for k in ids]) for rule in ("fp32", "int8")}
                     for name, rows in (("single", old), ("eight", new))},
            "batch8_primary": {k: report["scores"][k] for k in ("fp32", "int8")},
            "batch8_comparison": report["pairs"]["fp32_versus_int8"],
            "posthoc_int8_eight_minus_single_shared_reference": shared_gold_gain(old, new)}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    create = commands.add_parser("diff")
    for field in ("single", "eight", "output"):
        create.add_argument(field, type=Path)
    review = commands.add_parser("audit")
    for field in ("single", "patch", "data"):
        review.add_argument(field, type=Path)
    review.add_argument("--restore", type=Path)
    args = parser.parse_args()
    if args.command == "diff":
        export(args.single, args.eight, args.output)
    else:
        print(json.dumps(replay(args.single, args.patch, args.data, args.restore), sort_keys=True, indent=2))
