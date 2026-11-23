"""Audit the order of label aggregation using the original GoEmotions splits and raw votes."""

import argparse
from collections import Counter, defaultdict
import csv
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from goemotions_fetch import GCS, GIT, REVISION, verify


def enough(ballots):
    counts = Counter(label for labels in ballots for label in labels)
    return frozenset(label for label, count in counts.items() if count >= 2)


def read_data(folder):
    for name in (*GIT, *GCS):
        verify(folder / name, name)
    labels = (folder / "emotions.txt").read_text(encoding="utf8").splitlines()
    groups = json.loads((folder / "ekman_mapping.json").read_bytes())
    if len(set(labels)) != len(labels) or "neutral" not in labels:
        raise ValueError("unexpected label vocabulary")
    parent = {"neutral": "neutral"}
    for group, children in groups.items():
        for child in children:
            if child in parent:
                raise ValueError("ambiguous fine-to-coarse mapping")
            parent[child] = group
    if set(parent) != set(labels):
        raise ValueError("fine-to-coarse mapping coverage mismatch")
    split = {}
    for name in ("train", "dev", "test"):
        with (folder / (name + ".tsv")).open(encoding="utf8", newline="") as stream:
            for fields in csv.reader(stream, delimiter="\t", quoting=csv.QUOTE_NONE):
                _, indices, key = fields
                if key in split:
                    raise ValueError(f"duplicate or overlapping split id {key}")
                indexes = [int(i) for i in indices.split(",")]
                if any(not 0 <= i < len(labels) for i in indexes):
                    raise ValueError("unknown split label")
                split[key] = (name, frozenset(labels[i] for i in indexes))
    rows = defaultdict(dict)
    conflicts = set()
    diagnostics = dict.fromkeys(("raw_rows", "duplicate_rows", "unclear_with_labels",
                                 "clear_with_zero_labels", "unclear_rows"), 0)
    for name in GCS:
        with (folder / name).open(encoding="utf8", newline="") as stream:
            for record in csv.DictReader(stream):
                diagnostics["raw_rows"] += 1
                key, rater = record["id"], record["rater_id"]
                if not key or not rater or record["example_very_unclear"] not in {"True", "False"}:
                    raise ValueError("missing key, rater, or unclear flag")
                if any(record[t] not in {"0", "1"} for t in labels):
                    raise ValueError("non-binary label")
                marks = frozenset(t for t in labels if record[t] == "1")
                unclear = record["example_very_unclear"] == "True"
                diagnostics["unclear_rows"] += unclear
                diagnostics["unclear_with_labels"] += unclear and bool(marks)
                diagnostics["clear_with_zero_labels"] += not unclear and not marks
                if rater in rows[key]:
                    diagnostics["duplicate_rows"] += 1
                    if rows[key][rater] != (marks, unclear):
                        conflicts.add(key)
                else:
                    rows[key][rater] = marks, unclear
    diagnostics.update(raw_ids=len(rows), conflict_ids=len(conflicts),
                       split_ids_absent_from_raw=len(split.keys() - rows.keys()),
                       repeated_or_overlapping_split_ids=0)
    return parent, split, rows, conflicts, diagnostics


def summary():
    return {"eligible": 0, "raw_vote_count_histogram": Counter(), "split_rows": 0,
            "fine_equal_release": 0, "raw_fine_empty_coarse_present": 0,
            "order_changed": 0, "order_added": Counter(), "release_changed": 0,
            "release_added": Counter(), "release_removed": Counter(),
            "release_changed_among_fine_matches": 0, "matched_release_added": Counter(),
            "matched_release_removed": Counter()}


def audit(folder, export=None):
    parent, split, raw, conflicts, diagnostics = read_data(folder)
    subsets = {name: summary() for name in ("test", "dev", "train", "unreleased")}
    examples = []
    ordered_test = []
    for key in sorted(raw.keys() | split.keys()):
        name, published = split.get(key, ("unreleased", None))
        s = subsets[name]
        s["split_rows"] += published is not None
        status = "ok" if key in raw and key not in conflicts else "unresolved"
        if status != "ok":
            if name == "test":
                ordered_test.append({"id": key, "status": status})
            continue
        ballots = [b for b, _ in raw[key].values()]
        s["eligible"] += 1
        s["raw_vote_count_histogram"][str(len(ballots))] += 1
        fine = enough(ballots)
        coarse_ballots = [{parent[t] for t in b} for b in ballots]
        before = enough(coarse_ballots)
        after = {parent[t] for t in fine}
        if not after <= before:
            raise AssertionError("support is not monotone under coarsening")
        s["order_changed"] += before != after
        s["order_added"].update(before - after)
        s["raw_fine_empty_coarse_present"] += not fine and bool(before)
        if published is None:
            continue
        baseline = {parent[t] for t in published}
        s["fine_equal_release"] += fine == published
        s["release_changed"] += before != baseline
        s["release_added"].update(before - baseline)
        s["release_removed"].update(baseline - before)
        if fine == published:
            s["release_changed_among_fine_matches"] += before != baseline
            s["matched_release_added"].update(before - baseline)
            s["matched_release_removed"].update(baseline - before)
        if name == "test":
            ordered_test.append({"id": key, "status": status, "published_ekman": sorted(baseline),
                                 "two_reporters_ekman": sorted(before), "fine_matches": fine == published})
            if len(ballots) == 3 and before != baseline and fine == published and not examples:
                examples.append({"id": key, "published_fine": sorted(published),
                                 "published_ekman": sorted(baseline), "two_reporters_ekman": sorted(before),
                                 "anonymous_three_ballots": sorted(sorted(b) for b in ballots)})
    if export is not None:
        with export.open("x", encoding="utf8", newline="\n") as stream:
            for record in ordered_test:
                stream.write(json.dumps(record, sort_keys=True) + "\n")
    return {"upstream": REVISION, "threshold": 2, "diagnostics": diagnostics,
            "subsets": subsets, "first_three_person_test_example": examples}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("folder", type=Path)
    parser.add_argument("--write-test-comparison", type=Path, help="write a new JSONL with one record per official test ID")
    args = parser.parse_args()
    print(json.dumps(audit(args.folder, args.write_test_comparison), sort_keys=True, indent=2))
