"""Sharp paired micro-F1 contrasts with one indivisible reference choice per item."""
from dataclasses import dataclass
from fractions import Fraction
from itertools import accumulate


@dataclass(frozen=True)
class Item:
    key: str
    size: int
    hits_a: int
    hits_b: int


@dataclass(frozen=True)
class Baseline:
    gold: int
    predicted_a: int
    predicted_b: int
    true_a: int
    true_b: int

    def delta(self, k=0, a=0, b=0):
        return (Fraction(2 * (self.true_a + a), max(1, self.gold + self.predicted_a + k)) -
                Fraction(2 * (self.true_b + b), max(1, self.gold + self.predicted_b + k)))


def sharp(base, items):
    """Return extrema and the minimum number of item switches for a strict reversal."""
    if len({s.key for s in items}) != len(items) or any(
        s.size <= 0 or not (0 <= s.hits_a <= s.size and 0 <= s.hits_b <= s.size) for s in items
    ):
        raise ValueError("invalid or duplicate choice")
    single = sorted((v for v in items if v.size == 1), key=lambda v: v.key)
    multi = sorted((v for v in items if v.size > 1), key=lambda v: v.key)
    start = base.delta()
    low = high = start
    low_ids = high_ids = ()
    nearest = None
    weights = sum(i.size for i in items)

    for k in range(weights + 1):
        da = max(1, base.gold + base.predicted_a + k)
        db = max(1, base.gold + base.predicted_b + k)
        constant = db * base.true_a - da * base.true_b

        def gain(item):
            return db * item.hits_a - da * item.hits_b

        for direction in (-1, 1):
            ordered = sorted(single, key=lambda i: -direction * gain(i))
            prefix = list(accumulate((gain(i) for i in ordered), initial=0))
            # For each (number of new gold labels, number of changed items),
            # retain one extremizer among multi-label items. Singletons use a prefix.
            best = {(0, 0): (0, ())}
            for item in multi:
                after = best.copy()
                value = gain(item)
                for (weight, count), (reward, chosen) in best.items():
                    if weight + item.size > k:
                        continue
                    key = (weight + item.size, count + 1)
                    total = reward + value
                    if key not in after or direction * total > direction * after[key][0]:
                        after[key] = (total, chosen + (item.key,))
                best = after

            for (weight, count), (reward, chosen) in best.items():
                singles = k - weight
                if singles > len(ordered):
                    continue
                delta = Fraction(2 * (constant + reward + prefix[singles]), da * db)
                n = count + singles
                better_reverse = (delta * start < 0 and
                                  (nearest is None or n < nearest[0] or
                                   (n == nearest[0] and abs(delta) > abs(nearest[1]))))
                if delta < low or delta > high or better_reverse:
                    ids = tuple(sorted(chosen + tuple(i.key for i in ordered[:singles])))
                    if delta < low:
                        low, low_ids = delta, ids
                    if delta > high:
                        high, high_ids = delta, ids
                    if better_reverse:
                        nearest = (n, delta, ids)

    def outcome(delta, keys):
        chosen = set(keys)
        part = [i for i in items if i.key in chosen]
        replay = base.delta(sum(i.size for i in part), sum(i.hits_a for i in part),
                            sum(i.hits_b for i in part))
        if delta != replay or len(keys) != len(part):
            raise AssertionError("witness failed direct recomputation")
        return {"difference": str(delta), "switches": len(keys), "ids": list(keys)}

    return {"baseline": str(start), "minimum": outcome(low, low_ids), "maximum": outcome(high, high_ids),
            "nearest_strict_reverse": None if nearest is None else outcome(nearest[1], nearest[2])}


def audit_jsonl(stream):
    """Accept arbitrary label names. All four fields are sets of positive labels."""
    import json

    gold = pa = pb = ta = tb = 0
    keys, choices = set(), []
    for number, line in enumerate(stream, 1):
        row = json.loads(line)
        key = row["id"]
        if not isinstance(key, str) or not key or key in keys:
            raise ValueError(f"invalid or duplicate item id on line {number}")
        keys.add(key)
        bags = []
        for field in ("released", "alternative", "prediction_a", "prediction_b"):
            labels = row[field]
            if (not isinstance(labels, list) or
                    any(not isinstance(tag, str) or not tag for tag in labels) or len(set(labels)) != len(labels)):
                raise ValueError(f"{field} must contain unique label names on line {number}")
            bags.append(set(labels))
        old, new, a, b = bags
        if not old <= new:
            raise ValueError(f"reference is not additive on line {number}")
        gold += len(old)
        pa += len(a)
        pb += len(b)
        ta += len(a & old)
        tb += len(b & old)
        added = new - old
        if added:
            choices.append(Item(key, len(added), len(a & added), len(b & added)))
    if not keys:
        raise ValueError("empty input")
    base = Baseline(gold, pa, pb, ta, tb)
    all_switched = base.delta(sum(i.size for i in choices), sum(i.hits_a for i in choices),
                              sum(i.hits_b for i in choices))
    return {"items": len(keys), "switchable": len(choices), "all_switched": str(all_switched),
            **sharp(base, choices)}


if __name__ == "__main__":
    import argparse
    import json
    from pathlib import Path

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("jsonl", type=Path)
    args = parser.parse_args()
    try:
        with args.jsonl.open(encoding="utf8") as stream:
            print(json.dumps(audit_jsonl(stream), indent=2))
    except (ValueError, KeyError, OSError, TypeError) as exc:
        parser.exit(2, f"{exc}\n")
