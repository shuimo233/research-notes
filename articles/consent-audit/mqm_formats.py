"""Post-holdout byte comparison of four explicit formats on the same keys and vocabulary."""

import argparse
from itertools import combinations
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import zlib

sys.path.insert(0,str(Path(__file__).resolve().parent))
from mqm_receipt import Receipt,ballot_rows,exclusive,partition,silent
from mqm_wmt import load,positive


def put(buf,value):
    while value>=128:
        buf.append((value&127)|128)
        value>>=7
    buf.append(value)


def sequence(buf,values):
    put(buf,len(values))
    for v in values:
        put(buf,v)


class Reader:
    def __init__(self,raw):
        self.raw=raw
        self.pos=0

    def number(self):
        v=shift=0
        while True:
            c=self.raw[self.pos]
            self.pos+=1
            v|=(c&127)<<shift
            if c<128:
                return v
            shift+=7

    def sequence(self):
        return tuple(self.number() for _ in range(self.number()))


def bits_append(stream,start,width,rank):
    stop=start+width
    while len(stream)<(stop+7)//8:
        stream.append(0)
    for i in range(width):
        if (rank>>i)&1:
            stream[(start+i)//8]|=1<<((start+i)%8)
    return stop


def bits_read(stream,start,width):
    return (int.from_bytes(stream[start//8:(start+width+7)//8],"little")>>(start%8)) & ((1<<width)-1)


def run(data,lang):
    ratings,_,_=load(data,lang)
    keys=sorted(k for k,people in ratings.items() if len(people)==3)
    vocab=sorted({t for k in keys for b in ratings[k].values() for t in b})
    ids={t:i for i,t in enumerate(vocab)}
    files={name:bytearray() for name in ("local","function","margins","ranks","one_decision")}
    common=json.dumps({"keys":keys,"types":vocab},separators=(",",":"),ensure_ascii=False).encode()
    files["keys_and_types"]=common
    start=0
    for j,key in enumerate(keys):
        ballots=list(ratings[key].values())
        sets=[set(ids[t] for t in b if not silent(t)) for b in ballots]
        for s in sorted(tuple(sorted(s)) for s in sets):
            sequence(files["local"],s)
        shared=sorted(i for i in set.union(*sets) if sum(i in s for s in sets)>=2)
        sequence(files["function"],shared)
        blocks=sorted(tuple(sorted(g-set(shared))) for g in sets if g-set(shared))
        blocks=blocks if len(blocks)>=2 else []
        put(files["function"],len(blocks))
        for block in blocks:
            sequence(files["function"],block)
        margin=ballot_rows(ballots)
        relaxed=any(len(b)>5 or (len(b)>1 and any(exclusive(t) for t in b)) for b in ballots)
        codec=Receipt(margin,relaxed=relaxed)
        put(files["margins"],len(margin)*2+relaxed)
        for sev,cat,k,d in margin:
            for value in (ids[sev,cat],k,d):
                put(files["margins"],value)
        rank=codec.space.rank(partition(ballots,codec.single))
        start=bits_append(files["ranks"],start,codec.bits,rank)
        bits_append(files["one_decision"],j,1,int(sum(any(positive(t) for t in b) for b in ballots)>=2))
    with TemporaryDirectory() as tmp:
        folder=Path(tmp)
        for name,payload in files.items():
            (folder/name).write_bytes(payload)
            (folder/(name+".deflate")).write_bytes(zlib.compress(payload,9))
        measured={name:{"bytes":(folder/name).stat().st_size,"deflate_bytes":(folder/(name+".deflate")).stat().st_size}
                  for name in files}
        read={name:zlib.decompress((folder/(name+".deflate")).read_bytes()) for name in files}
        assert all(read[n]==(folder/n).read_bytes() for n in files)
        catalog=json.loads(read["keys_and_types"])
        assert [tuple(t) for t in catalog["types"]]==vocab and [tuple(k) for k in catalog["keys"]]==keys
        local,func,marg=[Reader(read[n]) for n in ("local","function","margins")]
        offset=tests=0
        for j,key in enumerate(keys):
            sets=[set(local.sequence()) for _ in range(3)]
            shared=set(func.sequence())
            groups=[set(func.sequence()) for _ in range(func.number())]
            head=marg.number()
            rows=[[*vocab[marg.number()],marg.number(),marg.number()] for _ in range(head//2)]
            assert rows==ballot_rows(list(ratings[key].values()))
            codec=Receipt(rows,relaxed=bool(head&1))
            rank=bits_read(read["ranks"],offset,codec.bits)
            offset+=codec.bits
            owners=codec.space.unrank(rank)
            direct=[{ids[t] for t in b if not silent(t)} for b in ratings[key].values()]
            assert sorted(map(sorted,direct))==sorted(map(sorted,sets))
            active=set.union(*direct)
            main={i for i in active if positive(vocab[i])}
            assert bits_read(read["one_decision"],j,1)==int(sum(bool(s&main) for s in direct)>=2)
            for size in (1,2):
                for q in combinations(active,size):
                    selection=set(q)
                    truth=sum(bool(s&selection) for s in direct)>=2
                    assert truth==(bool(shared&selection) or sum(bool(g&selection) for g in groups)>=2)
                    assert truth==codec.with_partition({vocab[i] for i in q},owners)
                    tests+=1
        assert all(r.pos==len(r.raw) for r in (local,func,marg)) and offset==start
    return {"direction":lang,"record_count":len(keys),"shared_types":len(vocab),"streams":measured,
            "singleton_pair_checks":tests,"deflate_library":zlib.ZLIB_RUNTIME_VERSION}


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("data",type=Path)
    args=parser.parse_args()
    print(json.dumps([run(args.data,lang) for lang in ("ende","zhen")],indent=2))
