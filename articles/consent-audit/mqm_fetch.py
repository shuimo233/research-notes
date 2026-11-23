"""Fetch and verify the four immutable WMT source files without bundling them in the article."""

import argparse
from pathlib import Path
from shutil import copyfileobj,which
import subprocess
import sys
from tempfile import NamedTemporaryFile
from urllib.error import URLError
from urllib.request import urlopen

sys.path.insert(0,str(Path(__file__).resolve().parent))
from mqm_wmt import BLOBS,UPSTREAM,check_blob


def fetch(folder,lang):
    folder.mkdir(parents=True,exist_ok=True)
    for infix,blob in zip(("",".avg_seg_scores"),BLOBS[lang]):
        name=f"mqm_newstest2020_{lang}{infix}.tsv"
        path=folder/name
        if path.exists():
            check_blob(path,blob)
            continue
        url=f"https://raw.githubusercontent.com/google/wmt-mqm-human-evaluation/{UPSTREAM}/newstest2020/{lang}/{name}"
        with NamedTemporaryFile(dir=folder,delete=False) as output:
            temp=Path(output.name)
        try:
            try:
                with urlopen(url,timeout=60) as source,temp.open("wb") as dest:
                    copyfileobj(source,dest)
            except (OSError,URLError):
                if not which("gh"):
                    raise
                with temp.open("wb") as dest:
                    subprocess.run(["gh","api","-H","Accept: application/vnd.github.raw+json",
                                    "repos/google/wmt-mqm-human-evaluation/git/blobs/"+blob],stdout=dest,check=True)
            check_blob(temp,blob)
            temp.replace(path)
        finally:
            temp.unlink(missing_ok=True)


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("folder",type=Path)
    parser.add_argument("--direction",choices=BLOBS)
    args=parser.parse_args()
    for lang in ([args.direction] if args.direction else BLOBS):
        fetch(args.folder,lang)
        print(f"verified {lang}")
