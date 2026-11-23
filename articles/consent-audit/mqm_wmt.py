"""Audit WMT20 using only public score, category, severity, and grouping columns."""

import argparse
from collections import Counter, defaultdict
from decimal import Decimal
from hashlib import sha1
from itertools import combinations
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory

sys.path.insert(0,str(Path(__file__).resolve().parent))
from mqm_receipt import Receipt, atom, ballot_rows, exclusive, partition, silent
import mqm_archive


BLOBS = {"ende":("c02de5a8516e74754897845da29161056476df08","44e8a39165800f6c6bf2ac09d95b8724021fb7dc"),
         "zhen":("f39c4a12a79b1e2cdd2a395eb8a2d45d74796fdd","74be7b9a6cdfbf76202b982556bdd3e516035852")}
UPSTREAM = "29acd6999aaea3586378c9dcb58d8cc4820cede3"


def check_blob(path,known):
    h = sha1(b"blob "+str(path.stat().st_size).encode()+b"\0")
    with path.open("rb") as raw:
        for chunk in iter(lambda:raw.read(1<<20),b""):
            h.update(chunk)
    if h.hexdigest()!=known:
        raise ValueError(f"unexpected version of {path.name}")


def load(folder,lang):
    base = f"mqm_newstest2020_{lang}"
    votes,stats,atoms,docs = {},Counter(),{},{}
    source = folder/(base+".tsv")
    score_file = folder/(base+".avg_seg_scores.tsv")
    for path,blob in zip((source,score_file),BLOBS[lang]):
        check_blob(path,blob)
    with source.open("rb") as fh:
        if fh.readline().rstrip(b"\r\n").split(b"\t")!=b"system doc doc_id seg_id rater source target category severity".split():
            raise ValueError("unexpected main header")
        for line in fh:
            cells = line.rstrip(b"\r\n").split(b"\t")
            if len(cells)!=9:
                raise ValueError("unexpected TSV row width")
            system,doc,doc_id,seg,rater = cells[:5]
            key = system.decode(),int(seg)
            if docs.setdefault(key,(doc,doc_id))!=(doc,doc_id):
                raise ValueError("system/segment does not identify one document location")
            ballot = votes.setdefault(key,{}).setdefault(rater,[])
            pair = (cells[8],cells[7])
            if pair not in atoms:
                atoms[pair] = atom([x.decode() for x in pair])
            t = atoms[pair]
            if t[1].casefold().replace("-"," ").startswith("source error"):
                stats["source_rows_excluded"]+=1
            else:
                ballot.append(t)
            stats["main_rows"]+=1
    scores = {}
    with score_file.open(encoding="utf8") as fh:
        if fh.readline().split()!=["system","mqm_avg_score","seg_id"]:
            raise ValueError("unexpected average-score header")
        for line in fh:
            system,score,seg = line.split()
            key=system,int(seg)
            if key in scores:
                raise ValueError("duplicate public average")
            scores[key]=Decimal(score)
    if scores.keys()!=votes.keys():
        raise ValueError("different segment keys in the two published tables")
    return votes,scores,stats


def official_tenths(t):
    severity,category = t
    if silent(t):
        return 0
    if exclusive(t):
        return 250
    if severity=="major":
        return 50
    if severity=="minor":
        return 1 if category=="Fluency/Punctuation" else 10
    if severity=="neutral":
        return 0
    raise ValueError(f"unrecognized severity {severity}")


def positive(t):
    return t[0]=="major" and not silent(t)


def bag_bounds(margins,cap):
    fixed_yes = fixed_no = yes = no = 0
    for severity,category,k,_ in margins:
        t=severity,category
        if exclusive(t):
            if positive(t): fixed_yes+=k
            else: fixed_no+=k
        elif positive(t):
            yes+=k
        else:
            no+=k
    open_seats = 3-fixed_yes-fixed_no
    return (fixed_yes+max((yes+cap-1)//cap,open_seats-no),
            fixed_yes+min(open_seats,yes))


def describe_mixed(counts):
    mixed = [c for c in counts.values() if min(c)>0]
    return {"observed_summaries":len(counts),"mixed_summaries":len(mixed),
            "segments_with_mixed_summary":sum(sum(c) for c in mixed),
            "minimum_errors_on_observed_corpus":sum(min(c) for c in mixed)}


class Collisions:
    def __init__(self):
        self.first = {}
        self.example = None

    def find(self, signature, key, target):
        if self.example and self.example["same_system"]:
            return None
        for observation in ((key[0],signature),(None,signature)):
            old_key,old_target = self.first.setdefault(observation,(key,target))
            if old_target!=target:
                same = old_key[0]==key[0]
                if self.example is None or same:
                    self.example = {"same_system":same, "keys":[old_key,key]}
                    return old_target
        return None


def audit(folder,lang,out):
    votes,scores,stats = load(folder,lang)
    hypothesis = ("public_average","rows_by_type","average_and_rows","average_rows_and_people")
    hist = {h:defaultdict(lambda:[0,0]) for h in hypothesis}
    archive, earned, fallback = [], Counter(), Counter()
    bag_pairs,margin_pairs,future_pairs = Collisions(),Collisions(),Collisions()
    examples={}
    reasons,seat_counts,bit_hist = Counter(),Counter(),Counter()
    futures = defaultdict(set)
    tag_max = 0
    for key,people in sorted(votes.items()):
        ballots = list(people.values())
        seat_counts[len(ballots)]+=1
        score = scores[key]
        units=sum(official_tenths(t) for b in ballots for t in b)
        discrepancy=abs(score + Decimal(units)/(10*len(ballots)))
        stats["official_score_matches_6_decimals"] += discrepancy<=Decimal("0.00000051")
        if len(ballots)!=3:
            continue
        matches = sum(any(positive(t) for t in b) for b in ballots)
        gold = matches>=2
        stats["three_people"]+=1
        stats["major_consensus"]+=gold
        margin = ballot_rows(ballots)
        bag = tuple(tuple(row[:3]) for row in margin)
        detailed = tuple(map(tuple,margin))
        for which,observation in zip(hypothesis,(score,bag,(score,bag),(score,detailed))):
            hist[which][observation][int(gold)]+=1
        rows=sum(len(b) for b in ballots)
        flagged=sum(positive(t) for b in ballots for t in b)
        if 2*flagged==rows:
            stats["row_vote_tie"]+=1
        elif (2*flagged>rows)!=gold:
            stats["row_vote_wrong_without_ties"]+=1
        else:
            stats["row_vote_correct_without_ties"]+=1
        failures = []
        if any(not b for b in ballots): failures.append("empty_ballot")
        if any(len(b)>5 for b in ballots): failures.append("above_five")
        if any(len(b)>1 and any(exclusive(t) for t in b) for b in ballots): failures.append("nonexclusive_sentinel")
        if failures:
            reasons.update(failures)
            codec=Receipt(margin,relaxed=True)
            rank=codec.space.rank(partition(ballots,codec.single))
            archive.append((key,margin,rank,True))
            fallback["segments"]+=1
            fallback["rank_bits"]+=codec.bits
            fallback["major_uncertain_from_margins"]+=len(codec.possible({t for t in codec.margins if positive(t)}))==2
            for t in {t for b in ballots if len(b)>1 for t in b if exclusive(t)}:
                reasons["mixed_marker_"+t[1]]+=1
            continue
        earned["eligible"]+=1
        codec = Receipt(margin)
        owners = partition(ballots,codec.single)
        rank = codec.space.rank(owners)
        assert codec.space.unrank(rank)==owners
        query={t for t in codec.margins if positive(t)}
        actual = codec.with_partition(query,owners)
        choices = codec.possible(query)
        assert actual==gold and gold in choices
        lo,hi = bag_bounds(margin,5)
        assert lo<=matches<=hi
        earned["major_uncertain_from_bag"]+=lo<2<=hi
        earned["major_uncertain_from_margins"]+=len(choices)==2
        earned["major_from_margins_yes"]+=choices==[True]
        earned["major_from_margins_no"]+=choices==[False]
        m = len(codec.single)
        free_states = (3**m+3)//6 if m else 1
        assert 1<=codec.states<=free_states
        earned["two_bits_per_single_type"]+=2*m
        earned["unconstrained_partition_bits"]+=(free_states-1).bit_length()
        earned["exact_conditional_bits"]+=codec.bits
        earned["no_extra_field"]+=codec.bits==0
        earned["cap_reduces_states"]+=codec.states<free_states
        earned["local_incidence_bits"]+=2*sum(1<=d<=2 for t,(k,d) in codec.margins.items())
        bit_hist[codec.bits]+=1
        tag_max=max(tag_max,codec.states)
        futures[detailed].add(rank)
        for label,bank,summary,detail in (("bag_major",bag_pairs,(score,bag),bag),
                                          ("margins_major",margin_pairs,(score,detailed),margin)):
            if bank.find(summary,key,gold) is not None:
                examples[label]={**bank.example,"score":str(score),"summary":detail,
                                 "major_reporters":[sum(any(positive(t) for t in b) for b in votes[k].values())
                                                    for k in bank.example["keys"]]}
        old_rank=future_pairs.find((score,detailed),key,rank)
        if old_rank is not None:
            query=next(q for q in combinations(codec.single,2) if codec.answer(q,old_rank)!=codec.answer(q,rank))
            examples["margins_future_pair"]={**future_pairs.example,"score":str(score),"margins":margin,
                "query":query,"ranks":[old_rank,rank],"answers":[codec.answer(query,r) for r in (old_rank,rank)]}
        archive.append((key,margin,rank,False))
    manifest = mqm_archive.write(out,archive)
    checked = pair_checks = 0
    for key,codec,rank in mqm_archive.read(out):
        ballots=[set(b) for b in votes[key].values()]
        qtypes = [t for t in codec.margins if not silent(t)]
        owners = codec.space.unrank(rank)
        assert codec.with_partition({t for t in qtypes if positive(t)},owners)==(sum(any(positive(t) for t in b) for b in ballots)>=2)
        for size in (1,2):
            for sub in combinations(qtypes,size):
                sel=set(sub)
                assert codec.with_partition(sel,owners)==(sum(bool(b&sel) for b in ballots)>=2)
                pair_checks+=1
        checked+=1
    assert checked==manifest["segments"]==stats["three_people"]
    assert manifest["rank_bits"]==earned["exact_conditional_bits"]+fallback["rank_bits"]
    return {"upstream":UPSTREAM,"direction":lang,"segments":len(votes),"systems":len({s for s,_ in votes}),
            "rater_count_per_segment":dict(sorted(seat_counts.items())),**stats,
            "same_summary_opposite_majority":{k:describe_mixed(v) for k,v in hist.items()},
            "ineligible_flags":dict(reasons),"eligible_analysis":dict(earned),
            "conditional_bits_histogram":dict(sorted(bit_hist.items())),"largest_feasible_state_count":tag_max,
            "observed_margins_with_multiple_query_functions":sum(len(rs)>1 for rs in futures.values()),
            "natural_collisions":examples,"fallback":dict(fallback),"archive_rank_bits":manifest["rank_bits"],
            "only_major_conditional_bits":earned["major_uncertain_from_margins"]+fallback["major_uncertain_from_margins"],
            "archive_margins_bytes":(out/"margins.jsonl").stat().st_size,
            "archive_owners_bytes":(out/"owners.bin").stat().st_size,"archive_sha256":manifest["sha256"],
            "readback_segments":checked,"singleton_and_pair_queries_checked":pair_checks}


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("data",type=Path)
    parser.add_argument("direction",choices=BLOBS)
    parser.add_argument("--keep-archive",type=Path,help="create a new directory for public margins and anonymous ranks")
    args=parser.parse_args()
    try:
        if args.keep_archive:
            result=audit(args.data,args.direction,args.keep_archive)
        else:
            with TemporaryDirectory() as temp:
                result=audit(args.data,args.direction,Path(temp)/"archive")
        print(json.dumps(result,sort_keys=True,indent=2))
    except (ValueError,KeyError,TypeError,OSError) as exc:
        parser.exit(2,f"{exc}\n")
