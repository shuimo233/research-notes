"""Read/write the variable-width anonymous consensus fields; query a locally built archive."""

import argparse
from hashlib import sha256
import json
from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).resolve().parent))
from mqm_receipt import Receipt


def digest(path):
    h = sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda:f.read(1<<20),b""):
            h.update(chunk)
    return h.hexdigest()


def write(folder,records):
    folder.mkdir(parents=True,exist_ok=False)
    pending = used = total = count = 0
    with (folder/"margins.jsonl").open("w",encoding="utf8",newline="\n") as metas, (folder/"owners.bin").open("wb") as ranks:
        for key,margins,rank,relaxed in records:
            codec = Receipt(margins,relaxed=relaxed)
            if type(rank) is not int or not 0<=rank<codec.states:
                raise ValueError("illegal rank")
            row = [*key,margins]
            if relaxed:
                row.append(1)
            metas.write(json.dumps(row,separators=(",",":"),ensure_ascii=False)+"\n")
            pending |= rank<<used
            used += codec.bits
            total += codec.bits
            count += 1
            while used>=8:
                ranks.write(bytes([pending&255]))
                pending >>= 8
                used -= 8
        if used:
            ranks.write(bytes([pending]))
    manifest = {"format":"mqm-two-of-three-v1","cap":5,"segments":count,"rank_bits":total,
                "sha256":{f:digest(folder/f) for f in ("margins.jsonl","owners.bin")}}
    (folder/"manifest.json").write_text(json.dumps(manifest,indent=2)+"\n",encoding="utf8")
    return manifest


def read(folder):
    manifest = json.loads((folder/"manifest.json").read_bytes())
    if manifest["format"]!="mqm-two-of-three-v1" or manifest["cap"]!=5:
        raise ValueError("unknown archive format")
    for f in ("margins.jsonl","owners.bin"):
        if digest(folder/f)!=manifest["sha256"][f]:
            raise ValueError(f"{f}: digest mismatch")
    raw = (folder/"owners.bin").read_bytes()
    start = count = 0
    with (folder/"margins.jsonl").open(encoding="utf8") as stream:
        for line in stream:
            row = json.loads(line)
            system,seg,margins = row[:3]
            if row[3:] not in ([],[1]):
                raise ValueError("invalid archive mode")
            codec = Receipt(margins,relaxed=len(row)==4)
            stop = start+codec.bits
            if stop>len(raw)*8:
                raise ValueError("truncated rank stream")
            data = int.from_bytes(raw[start//8:(stop+7)//8],"little")
            rank = (data>>(start%8)) & ((1<<codec.bits)-1)
            if rank>=codec.states:
                raise ValueError("unassigned rank")
            start,count = stop,count+1
            yield (system,seg),codec,rank
    if (count!=manifest["segments"] or start!=manifest["rank_bits"] or len(raw)!=(start+7)//8
            or (start%8 and raw[-1]>>(start%8))):
        raise ValueError("archive length or padding mismatch")


if __name__=="__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("folder",type=Path)
    parser.add_argument("system")
    parser.add_argument("segment",type=int)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--severity")
    group.add_argument("--types",type=Path,help="JSON list of [severity, category] pairs")
    args=parser.parse_args()
    try:
        out=None
        for key,codec,rank in read(args.folder):
            if key==(args.system,args.segment):
                if out is not None:
                    raise ValueError("duplicate segment key")
                query=([t for t in codec.margins if t[0]==args.severity.casefold()]
                       if args.severity is not None else json.loads(args.types.read_bytes()))
                out={"system":key[0],"segment":key[1],"majority":codec.answer(query,rank),
                     "possible_from_margins":codec.possible(query)}
        if out is None:
            raise ValueError("segment not present")
        print(json.dumps(out,indent=2))
    except (ValueError,TypeError,KeyError,OSError) as exc:
        parser.exit(2,f"{exc}\n")
