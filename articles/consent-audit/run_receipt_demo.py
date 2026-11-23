"""Register real file identities before capturing SQLite actions; replay packed sidecars offline."""

from collections import Counter
from itertools import combinations
import json
from pathlib import Path
from random import Random
import sqlite3
import sys
from tempfile import TemporaryDirectory

sys.path.insert(0, str(Path(__file__).resolve().parent))
import sklearn
from learned_demo import fit_models
from source_demo import capture
from run_receipt import RunReceipt, ceil_log2
from receipt_design import design


def pack(path, values, width):
    packed = 0
    for i, value in enumerate(values):
        if not 0 <= value < (1 << width):
            raise ValueError("field overflows packed width")
        packed |= value << (i*width)
    path.write_bytes(packed.to_bytes((len(values)*width+7)//8, "little"))
    raw = path.read_bytes()
    stored = int.from_bytes(raw, "little")
    fields = [(stored >> (i*width)) & ((1 << width)-1) for i in range(len(values))]
    assert fields == values
    return fields, len(raw)


class Online:
    """Strong control: after the first paid answer, cache the role of one cut forever."""
    def __init__(self):
        self.anchor = None
        self.role = None
        self.calls = 0

    def decide(self, word, paths):
        cuts = [i for i in range(1,len(word)) if word[i-1] != word[i]]
        if not cuts:
            return word[0]
        if len(cuts) == 2:
            self.anchor, self.role = cuts[0], 0
            return word[0]
        t = cuts[0]
        if self.anchor is None:
            self.anchor = t
            if t in (1, len(word)-1):
                self.role = int(t != 1)
            else:
                self.role = int(not paths[0].samefile(paths[t-1]))
                self.calls += 1
        role = self.role if self.anchor == t else 1-self.role
        return word[0] if role else word[-1]


def run():
    n = 31
    layouts = list(combinations(range(1,n+1),2))
    selected = Random(31871).sample(layouts,32)
    codec = RunReceipt(n, [(1,15)])
    plain = RunReceipt(n)
    bins = [(i,min(i+1,n)) for i in range(1,n+1,2)]
    native = RunReceipt(n, bins)
    one_bit = RunReceipt(n, design(n,1)["intervals"])
    _, _, models = fit_models()
    names = ("app","gateway","authorizer")
    totals = Counter(row_vote_ties=0, row_vote_wrong=0)
    shared = {}
    collision = None
    with TemporaryDirectory() as temp:
        folder = Path(temp)
        staged, legacy, supplements, cut_ids, plain_tags, native_answers = [], [], [], [], [], []
        one_bit_fields, one_bit_tags = [], []
        for k, (a,b) in enumerate(selected):
            path = folder/str(k)
            path.mkdir()
            roots = [path/key for key in names]
            for p in roots:
                p.touch()
            rows = [path/f"row-{i}" for i in range(n+1)]
            for i, row in enumerate(rows):
                row.hardlink_to(roots[int(i>=a)+int(i>=b)])
            cuts = [i for i in range(1,len(rows)) if not rows[i-1].samefile(rows[i])]
            assert cuts == [a,b]
            reg = codec.issue(*cuts)
            observed = int(not rows[0].samefile(rows[15]))
            assert observed == reg["existing"]
            native_observed = sum(int(not rows[lo-1].samefile(rows[hi])) << j for j,(lo,hi) in enumerate(bins))
            assert native_observed == native.issue(*cuts)["existing"]
            measured = sum(int(not rows[lo-1].samefile(rows[hi])) << j
                           for j,(lo,hi) in enumerate(one_bit.intervals))
            plan = one_bit.issue(*cuts)
            assert measured == plan["existing"]
            one_bit_fields.append(measured)
            one_bit_tags.append(plan["tag"])
            staged.append((roots, rows, path))
            legacy.append(observed)
            supplements.append(reg["tag"])
            native_answers.append(native_observed)
            cut_ids.append(layouts.index(tuple(cuts)))
            plain_tags.append(plain.issue(*cuts)["tag"])
        # These fields exist on disk before the first model takes an action.
        old, nold = pack(folder/"existing.bin", legacy, 1)
        tags, ntags = pack(folder/"extra.bin", supplements, codec.bits)
        complete, nfull = pack(folder/"layout.bin", cut_ids, ceil_log2(len(layouts)))
        stand, nstand = pack(folder/"standalone.bin", plain_tags, plain.bits)
        pair_checks, npairs = pack(folder/"all-checks.bin", native_answers, len(bins))
        planned_checks, nplanned = pack(folder/"designed-checks.bin", one_bit_fields, len(one_bit.intervals))
        planned_tag, nonebit = pack(folder/"one-bit.bin", one_bit_tags, one_bit.bits)
        for k,(roots,rows,path) in enumerate(staged):
            events = {key:[] for key in names}
            for key, model in models.items():
                readings, changed = capture(model, path/(key+".db"))
                totals["committed_rows"] += changed
                for name in names:
                    events[name].extend(readings[name])
            truth = events["gateway"]
            for i, (p,name) in enumerate(zip(roots,names)):
                p.write_bytes(bytes(bit ^ int(i==k%3) for bit in events[name]))
            # The offline decoder only gets these row contents and the registered fields.
            archive = [p.read_bytes() for p in rows]
            a,b = layouts[complete[k]]
            online = Online()
            for event, ground in enumerate(truth):
                word = bytes(row[event] for row in archive)
                decision = codec.decide({"existing":old[k], "tag":tags[k]}, word)
                assert decision == ground
                fingerprint = (old[k], word)
                example = {"cuts":[a,b], "tag":tags[k], "truth":ground, "flipped":names[k%3],
                           "model":list(models)[event//2], "payoff":(8,20)[event%2]}
                if fingerprint in shared and shared[fingerprint]["truth"] != ground and collision is None:
                    collision = {"existing":old[k], "word":"".join(map(str,word)),
                                 "cases":[shared[fingerprint], example]}
                shared.setdefault(fingerprint, example)
                assert plain.decide({"existing":0, "tag":stand[k]}, word) == ground
                assert native.decide({"existing":pair_checks[k], "tag":0}, word) == ground
                assert one_bit.decide({"existing":planned_checks[k], "tag":planned_tag[k]}, word) == ground
                full_vote = int(word[0] + word[a] + word[b] >= 2)
                assert full_vote == ground
                assert online.decide(word, rows) == ground
                totals["events"] += 1
                totals["requested"] += ground
                sign = 2*sum(word)-len(word)
                if sign == 0:
                    totals["row_vote_ties"] += 1
                elif int(sign>0) != ground:
                    totals["row_vote_wrong"] += 1
            assert online.calls <= 1
            totals["adaptive_calls"] += online.calls
        return {"sqlite":sqlite3.sqlite_version, "sklearn":sklearn.__version__, "seed":31871,
                "layouts":len(selected), "candidate_cuts":n, "archived_rows_per_event":n+1, **totals,
                "correct_offline":totals["events"], "same_archive_opposite_truth":collision,
                "packed_bytes":{"existing":nold, "supplement":ntags, "complete_layout":nfull,
                                "standalone":nstand, "native_only":npairs,
                                "one_bit_plan_checks":nplanned, "one_bit_plan_tags":nonebit}}


if __name__ == "__main__":
    print(json.dumps(run(), indent=2))
