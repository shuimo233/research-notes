"""Ask about one noun sense at a time until a WordNet relation is determined."""

import argparse
import json
from pathlib import Path
import sys
from zipfile import ZipFile

sys.path.insert(0, str(Path(__file__).resolve().parent))
from go_model_fetch import verify
from sense_inquiry import SenseInquiry
from wordnet_paths import NounPaths


def query(archive, words, observed, policy):
    verify(archive, "3c68cd207844f071a5206f7fbed23e5c607ec02f")
    graph = NounPaths(archive)
    inquiry = SenseInquiry(*(graph.senses(w) for w in words), graph.relation)
    action, value = inquiry.advance(observed, policy)
    if action == "answer":
        return {"left": words[0], "right": words[1], "relation": value}
    senses = set(inquiry.senses[value])
    choices = {}
    with ZipFile(archive) as z, z.open("wordnet/data.noun") as stream:
        for line in stream:
            if line[:8].isdigit() and int(line[:8]) in senses:
                choices[line[:8].decode()] = line.partition(b"|")[2].decode().strip()
    return {"ask": "left" if value == 0 else "right", "word": words[value], "choices": choices}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path)
    parser.add_argument("left")
    parser.add_argument("right")
    parser.add_argument("--left-sense", type=int)
    parser.add_argument("--right-sense", type=int)
    parser.add_argument("--policy", choices=("table", "more", "fewer", "left", "right"), default="table")
    a = parser.parse_args()
    observed = {side: n for side, n in enumerate((a.left_sense, a.right_sense)) if n is not None}
    try:
        print(json.dumps(query(a.archive, (a.left, a.right), observed, a.policy), indent=2))
    except ValueError as error:
        parser.error(str(error))
