"""A separate size-count oracle and direct scoring of the serving-layout outputs."""
import argparse
from collections import Counter
import csv
from fractions import Fraction
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from go_model_bounds import Baseline
from go_model_check import enumerate_sizes, endpoints


def load_rows(path):
    with path.open(encoding="utf8", newline="") as f:
        return {r["id"]: {k: int(v) for k, v in r.items() if k != "id"}
                for r in csv.DictReader(f, delimiter="\t")}


def verify(base_path, patch_path, data, report):
    single, patch = load_rows(base_path), load_rows(patch_path)
    full = {k: {**v, **patch.get(k, {})} for k, v in single.items()}
    pairs = {k: {"eight": full[k]["int8"], "one": single[k]["int8"], **full[k]} for k in single}
    with (data / "test.tsv").open(encoding="utf8", newline="") as f:
        truth = {k: set(map(int, ids.split(","))) for _, ids, k in csv.reader(f, delimiter="\t", quoting=csv.QUOTE_NONE)}
    assert truth.keys() == pairs.keys() and len(pairs) == report["items"]
    for name, records in (("single", single), ("eight", full)):
        for rule in ("fp32", "int8"):
            actual, predicted, exact = Counter(), Counter(), 0
            true_positives = Counter()
            for k, r in records.items():
                chosen = {i for i in range(28) if r["fine_" + rule] & (1 << i)}
                actual.update(truth[k])
                predicted.update(chosen)
                true_positives.update(truth[k] & chosen)
                exact += truth[k] == chosen
            macro = sum(Fraction(2 * true_positives[i], max(1, actual[i] + predicted[i])) for i in range(28)) / 28
            assert report["fine"][name][rule] == {"macro_f1": str(macro), "exact_matches": exact}
    assert all(sum(r[c] != full[k][c] for k, r in single.items()) == v
               for c, v in report["changed_decisions_by_column"].items())
    assert len(patch) == report["patch_rows"]
    assert all(endpoints(list(full.values()), rule, ref) == report["batch8_primary"][rule][ref]
               for rule in ("fp32", "int8") for ref in ("released", "people"))
    checks = [(report["batch8_comparison"]["whole_items"], "fp32", "int8"),
              (report["posthoc_int8_eight_minus_single_shared_reference"], "eight", "one")]
    num_witness = 0
    for target, a, b in checks:
        x, y = (endpoints(list(pairs.values()), key, "released") for key in (a, b))
        initial = Baseline(x["gold"], x["predicted"], y["predicted"], x["true_positive"], y["true_positive"])
        choices = []
        for r in pairs.values():
            extra = r["people"] ^ r["released"]
            if extra:
                choices.append((extra.bit_count(), (extra & r[a]).bit_count(), (extra & r[b]).bit_count()))
        lo, hi, cost = enumerate_sizes(initial, choices)
        rev = target["nearest_strict_reverse"]
        assert (lo, hi, cost) == (Fraction(target["minimum"]["difference"]), Fraction(target["maximum"]["difference"]),
                                   None if rev is None else rev["switches"])
        for witness in (target["minimum"], target["maximum"], rev):
            if witness is None:
                continue
            chosen = set(witness["ids"])
            assert len(chosen) == witness["switches"] and chosen <= {k for k, r in pairs.items() if r["released"] != r["people"]}
            rset = [{**r, "selected": r["people"] if k in chosen else r["released"]} for k, r in pairs.items()]
            delta = Fraction(endpoints(rset, a, "selected")["micro_f1"]) - Fraction(endpoints(rset, b, "selected")["micro_f1"])
            assert delta == Fraction(witness["difference"])
            num_witness += 1
    return {"test_records": len(pairs), "fine_macro_scores": 4, "coarse_endpoint_checks": 4,
            "whole_item_hulls": len(checks), "replayed_witnesses": num_witness}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for arg in ("base", "patch", "data", "report"):
        parser.add_argument(arg, type=Path)
    args = parser.parse_args()
    print(json.dumps(verify(args.base, args.patch, args.data, json.loads(args.report.read_bytes())), indent=2))
