"""Independent raw gloss-corpus census, outside-source frequency counts, costs and policy verification."""

import argparse
from collections import Counter, defaultdict
from fractions import Fraction as Q
from functools import lru_cache
from itertools import combinations, product
from math import prod
from pathlib import Path
import hashlib
import json
import shutil
import sys
from tempfile import TemporaryDirectory
from xml.etree import ElementTree as ET
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
from frontier_rate_check import all_actions, verify_completions
from frontier_theory_check import raw_optimum
from go_model_fetch import verify


def check(wordnet, semcor, gloss, folder):
    if not __debug__:
        raise RuntimeError("enable assertions")
    import nltk
    from nltk.corpus import wordnet as wn
    from nltk.corpus.reader.wordnet import WordNetError

    verify(wordnet, "3c68cd207844f071a5206f7fbed23e5c607ec02f")
    verify(semcor, "19cdf8d8b1377016e9a0c3ec2a3147df1a778727")
    with gloss.open("rb") as f:
        assert (
            hashlib.file_digest(f, "sha256").hexdigest()
            == "a9233e1d0e1f4d11c5959c36fbe4d021aa4cb4e0bae0a348af118f4df6d558b6"
        )
    rows = [
        json.loads(l)
        for l in (folder / "gloss-frontier-ledger.jsonl").read_bytes().splitlines()
    ]
    lookup = {(r["stratum"], r["definition"]): r for r in rows}
    assert len(rows) == len(lookup)
    expected = json.loads((folder / "gloss-frontier-results.json").read_bytes())
    counts = defaultdict(Counter)
    used_words = {p[2] for r in rows for p in r["positions"]}
    train = Counter()
    raw_cases = 0
    with TemporaryDirectory() as temp:
        corp = Path(temp) / "corpora"
        corp.mkdir()
        shutil.copyfile(wordnet, corp / "wordnet.zip")
        nltk.data.path.insert(0, temp)
        try:

            @lru_cache(None)
            def mapped(key):
                if key.count(":") != 4 or "%1:" not in key:
                    return None
                try:
                    s = wn.lemma_from_key(key)
                except (WordNetError, KeyError, ValueError):
                    return None
                return s.synset().offset() if s.key() == key else None

            @lru_cache(None)
            def senses(w):
                return {s.offset(): s for s in wn.synsets(w, pos="n")}

            @lru_cache(None)
            def parents(s):
                return {v for path in s.hypernym_paths() for v in path[:-1]}

            def label(x, y):
                if x == y:
                    return "same"
                if y in parents(x):
                    return "left_narrower"
                if x in parents(y):
                    return "right_narrower"
                return "neither"

            @lru_cache(40000)
            def table(a, b):
                return {
                    (x, y): label(s, t)
                    for x, s in senses(a).items()
                    for y, t in senses(b).items()
                }

            with ZipFile(semcor) as z:
                for n in z.namelist():
                    if n.endswith("/") or "/tagfiles/" not in n:
                        continue
                    with z.open(n) as f:
                        root = ET.parse(f)
                    for s in root.iter("s"):
                        for node in s:
                            w = node.get("lemma", "")
                            if w in used_words:
                                x = mapped(w + "%" + node.get("lexsn", ""))
                                if x in senses(w):
                                    train[w, x] += 1
            with ZipFile(gloss) as z:
                for source in ("noun", "verb", "adj", "adv"):
                    with z.open(f"WordNet-3.0/glosstag/merged/{source}.xml") as f:
                        for _, s in ET.iterparse(f):
                            if s.tag != "synset":
                                continue
                            defs = [
                                d
                                for g in s
                                if g.tag == "gloss" and g.get("desc") == "wsd"
                                for d in g
                                if d.tag == "def"
                            ]
                            for d in defs:
                                ag = counts[source]
                                ag["definitions"] += 1
                                parent = {
                                    child: node for node in d.iter() for child in node
                                }
                                pos = {}
                                seq = 0
                                for node in d.iter("wf"):
                                    ancestor = parent[node]
                                    blocked = False
                                    while ancestor is not d:
                                        if ancestor.tag in {"cf", "glob", "mwf", "ex"}:
                                            blocked = True
                                            break
                                        ancestor = parent[ancestor]
                                    if blocked:
                                        continue
                                    ident = f"{seq:05d}"
                                    seq += 1
                                    if node.get("tag") != "man" or not node.get(
                                        "pos", ""
                                    ).startswith("NN"):
                                        continue
                                    variants = {
                                        item.rsplit("%", 1)[0]
                                        for item in node.get("lemma", "").split("|")
                                        if item.rsplit("%", 1)[-1] == "1"
                                    }
                                    annotations = [
                                        child.get("sk", "")
                                        for child in node
                                        if child.tag == "id"
                                    ]
                                    if len(variants) != 1 or not annotations:
                                        continue
                                    w = variants.pop()
                                    if any(a.split("%")[0] != w for a in annotations):
                                        continue
                                    offsets = {mapped(a) for a in annotations}
                                    if (
                                        len(offsets) != 1
                                        or len(senses(w)) < 2
                                        or not offsets <= senses(w).keys()
                                    ):
                                        continue
                                    pos[ident] = [
                                        ident,
                                        node.get("id"),
                                        w,
                                        offsets.pop(),
                                    ]
                                ag["eligible_positions"] += len(pos)
                                groups = defaultdict(list)
                                for i, (_, _, w, _) in pos.items():
                                    groups[w].append(i)
                                adj = defaultdict(set)
                                for a, b in combinations(sorted(groups), 2):
                                    if len(set(table(a, b).values())) > 1:
                                        adj[a].add(b)
                                        adj[b].add(a)
                                tris = set()
                                for a, b, c in combinations(sorted(groups), 3):
                                    ag["distinct_lemma_triples"] += (
                                        len(groups[a]) * len(groups[b]) * len(groups[c])
                                    )
                                    if b in adj[a] and c in adj[a] and c in adj[b]:
                                        tris.update(
                                            tuple(sorted(t))
                                            for t in product(
                                                groups[a], groups[b], groups[c]
                                            )
                                        )
                                if not tris:
                                    continue
                                row = lookup.pop((source, d.get("id")))
                                ids = sorted({u for tri in tris for u in tri})
                                assert row["positions"] == [
                                    pos[u] for u in ids
                                ] and row["triangles"] == list(map(list, sorted(tris)))
                                edges = sorted(
                                    {e for tri in tris for e in combinations(tri, 2)}
                                )
                                assert row["edges"] == list(map(list, edges))
                                words = {i: pos[i][2] for i in ids}
                                truth = {i: pos[i][3] for i in ids}

                                def candidates(edge, known):
                                    u, v = edge
                                    grid = table(words[u], words[v])
                                    return {
                                        grid[x, y]
                                        for x in (
                                            [truth[u]]
                                            if u in known
                                            else senses(words[u])
                                        )
                                        for y in (
                                            [truth[v]]
                                            if v in known
                                            else senses(words[v])
                                        )
                                    }

                                gold = [
                                    next(iter(candidates(e, set(ids)))) for e in edges
                                ]
                                assert gold == row["labels"]
                                for m in (
                                    "cached",
                                    "optimal",
                                    "fixed",
                                    "oracle",
                                    "greedy",
                                ):
                                    paid = set(row[m])
                                    assert len(paid) == len(row[m]) and paid <= set(ids)
                                    assert all(
                                        candidates(e, paid) == {l}
                                        for e, l in zip(edges, gold)
                                    )
                                allsets = [
                                    set(c)
                                    for k in range(len(ids) + 1)
                                    for c in combinations(ids, k)
                                ]
                                assert len(row["oracle"]) == next(
                                    len(c)
                                    for c in allsets
                                    if all(len(candidates(e, c)) == 1 for e in edges)
                                )
                                ps = {
                                    w: {
                                        x: Q(
                                            train[w, x] + 1,
                                            sum(train[w, y] + 1 for y in senses(w)),
                                        )
                                        for x in senses(w)
                                    }
                                    for w in set(words.values())
                                }
                                names = sorted(set(words.values()))
                                members = [
                                    sorted(i for i in ids if words[i] == w)
                                    for w in names
                                ]
                                mult = tuple(map(len, members))
                                ix = {i: names.index(words[i]) for i in ids}
                                neighbor = [
                                    {
                                        ix[v]
                                        for u, v in (
                                            *edges,
                                            *[(b, a) for a, b in edges],
                                        )
                                        if ix[u] == j
                                    }
                                    for j in range(len(names))
                                ]
                                options = []
                                masks = []
                                for i, w in enumerate(names):
                                    masks.append(
                                        {
                                            x: sum(
                                                1 << j
                                                for j in neighbor[i]
                                                if len(
                                                    {
                                                        table(w, names[j])[x, y]
                                                        for y in senses(names[j])
                                                    }
                                                )
                                                > 1
                                            )
                                            for x in senses(w)
                                        }
                                    )
                                    freq = Counter()
                                    for x, h in masks[-1].items():
                                        freq[h] += ps[w][x]
                                    options.append(list(freq.items()))
                                rates = [
                                    {
                                        j: sum(p for mask, p in opt if mask >> j & 1)
                                        for j in neighbor[i]
                                    }
                                    for i, opt in enumerate(options)
                                ]
                                cache = set()
                                chron = []
                                for tri in sorted(tris):
                                    risk = {
                                        u: 2
                                        + min(
                                            1,
                                            sum(
                                                rates[ix[v]][ix[u]]
                                                for v in tri
                                                if v != u
                                            ),
                                        )
                                        for u in tri
                                    }
                                    later = min(tri, key=lambda u: (risk[u], words[u]))
                                    unresolved = [
                                        e
                                        for e in combinations(tri, 2)
                                        if len(candidates(e, cache)) > 1
                                    ]
                                    first = sorted(
                                        (
                                            set().union(*(set(e) for e in unresolved))
                                            - {later}
                                        )
                                        - cache,
                                        key=words.get,
                                    )
                                    chron.extend(first)
                                    cache.update(first)
                                    if any(
                                        len(candidates(e, cache)) > 1
                                        for e in unresolved
                                    ):
                                        assert later not in cache
                                        cache.add(later)
                                        chron.append(later)
                                assert chron == row["cached"]

                                def fixed_cost(c):
                                    return len(c) + sum(
                                        1
                                        - prod(
                                            1 - rates[ix[v]][ix[u]]
                                            for v in c
                                            if ix[u] in neighbor[ix[v]]
                                        )
                                        for u in ids
                                        if u not in c
                                    )

                                valid = [
                                    c
                                    for c in allsets
                                    if all(c.intersection(e) for e in edges)
                                ]
                                assert min(map(fixed_cost, valid)) == Q(
                                    row["expected_fixed"]
                                )
                                typed = [
                                    c
                                    for c in valid
                                    if all(
                                        set(ms) <= c or not set(ms) & c
                                        for ms in members
                                    )
                                ]
                                first = min(
                                    typed,
                                    key=lambda c: (
                                        fixed_cost(c),
                                        len(c),
                                        tuple(
                                            i
                                            for i, ms in enumerate(members)
                                            if ms[0] not in c
                                        ),
                                    ),
                                )
                                ordered_ids = [u for ms in members for u in ms]
                                fixed_trace = [u for u in ordered_ids if u in first]
                                missing = {
                                    u
                                    for e in edges
                                    if len(candidates(e, first)) > 1
                                    for u in e
                                    if u not in first
                                }
                                fixed_trace.extend(
                                    u for u in ordered_ids if u in missing
                                )
                                assert row["fixed"] == fixed_trace
                                value, after = all_actions(options, neighbor)
                                val = value(mult, 0)
                                assert (
                                    val == Q(row["expected_optimal"])
                                    and row["fallback_decisions"] == 0
                                )
                                rem = mult
                                forced = 0
                                seen = set()
                                for u in row["optimal"]:
                                    i = ix[u]
                                    assert value(rem, forced) == after(i, rem, forced)
                                    seen.add(u)
                                    rem = tuple(
                                        n - int(k == i) for k, n in enumerate(rem)
                                    )
                                    forced = (forced | masks[i][truth[u]]) & sum(
                                        1 << k for k, n in enumerate(rem) if n
                                    )
                                assert value(rem, forced) == 0
                                value.cache_clear()
                                after.cache_clear()
                                # Derive greedy choices by inspecting all remaining raw relation tables.
                                rem = mult
                                forced = 0
                                for u in row["greedy"]:
                                    live = {i for i, n in enumerate(rem) if n}
                                    mandatory = {
                                        j
                                        for i in live
                                        for j in neighbor[i] & live
                                        if rates[i][j] == 1 or forced >> j & 1
                                    } | {i for i in live if forced >> i & 1}
                                    if mandatory:
                                        pick = min(mandatory)
                                    else:
                                        comp = {
                                            min(i for i in live if neighbor[i] & live)
                                        }
                                        while True:
                                            reach = comp | (
                                                set().union(
                                                    *(neighbor[i] for i in comp)
                                                )
                                                & live
                                            )
                                            if reach == comp:
                                                break
                                            comp = reach
                                        pick = min(
                                            comp,
                                            key=lambda i: (
                                                -sum(
                                                    rem[j] * (1 - rates[i][j])
                                                    for j in neighbor[i] & live
                                                ),
                                                -sum(
                                                    rem[j] for j in neighbor[i] & live
                                                ),
                                                i,
                                            ),
                                        )
                                    assert (
                                        ix[u] == pick
                                        and u == members[pick][mult[pick] - rem[pick]]
                                    )
                                    rem = tuple(
                                        n - int(k == pick) for k, n in enumerate(rem)
                                    )
                                    forced |= masks[pick][truth[u]]
                                verify_completions(
                                    row["information"],
                                    val,
                                    options,
                                    neighbor,
                                    mult,
                                    members,
                                    {u: masks[ix[u]][truth[u]] for u in ids},
                                )
                                if prod(len(senses(words[u])) + 1 for u in ids) <= 3000:
                                    ds = [list(senses(words[u])) for u in ids]
                                    ts = {
                                        (ids.index(u), ids.index(v)): [
                                            [
                                                table(words[u], words[v])[x, y]
                                                for y in ds[ids.index(v)]
                                            ]
                                            for x in ds[ids.index(u)]
                                        ]
                                        for u, v in edges
                                    }
                                    assert (
                                        raw_optimum(
                                            [
                                                [ps[words[u]][x] for x in xs]
                                                for u, xs in zip(ids, ds)
                                            ],
                                            ts,
                                            [1] * len(ds),
                                        )
                                        == val
                                    )
                                    raw_cases += 1
                            s.clear()
        finally:
            nltk.data.path.remove(temp)
    assert not lookup
    for source, result in expected.items():
        selected = [r for r in rows if source == "all" or r["stratum"] == source]
        c = sum(counts.values(), Counter()) if source == "all" else counts[source]
        calc = {
            f: c[f]
            for f in ("definitions", "eligible_positions", "distinct_lemma_triples")
        }
        calc.update(
            qualifying_definitions=len(selected),
            triangles=sum(len(r["triangles"]) for r in selected),
            shared_position_definitions=sum(
                len(r["positions"]) < 3 * len(r["triangles"]) for r in selected
            ),
            exact_roots=len(selected),
            fallback_definitions=0,
        )
        for m in ("cached", "fixed", "greedy", "optimal", "oracle"):
            calc[m] = sum(len(r[m]) for r in selected)
        calc.update(
            expected_fixed_on_exact=str(sum(Q(r["expected_fixed"]) for r in selected)),
            expected_optimal_on_exact=str(
                sum(Q(r["expected_optimal"]) for r in selected)
            ),
            fewer_than_cached=sum(
                len(r["optimal"]) < len(r["cached"]) for r in selected
            ),
            more_than_cached=sum(
                len(r["optimal"]) > len(r["cached"]) for r in selected
            ),
            primary_gate=bool(selected)
            and 100 * calc["optimal"] <= 99 * calc["cached"]
            and calc["optimal"] < calc["greedy"],
        )
        calc["information"] = {}
        for mode in ("block", "independent", "nested"):
            ds = [
                Q(r["information"][mode]["actual_expected"]) - Q(r["expected_optimal"])
                for r in selected
            ]
            calc["information"][mode] = {
                "strict_expected_regret": sum(x > 0 for x in ds),
                "total_expected_regret": str(sum(ds)),
                "incorrect_forecast": sum(
                    Q(r["information"][mode]["forecast"]) != Q(r["expected_optimal"])
                    for r in selected
                ),
                "gold_queries": sum(
                    r["information"][mode]["queries"] for r in selected
                ),
            }
        calc["mechanism_gate"] = (
            max(
                calc["information"][m]["strict_expected_regret"]
                for m in ("independent", "nested")
            )
            >= 2
        )
        assert calc == result, (
            source,
            [(k, calc.get(k), v) for k, v in result.items() if calc.get(k) != v],
        )
    return {
        "definitions_scanned": expected["all"]["definitions"],
        "verified_roots": len(rows),
        "literal_raw_history_roots": raw_cases,
        "verified_scalar_completions": 2 * len(rows),
    }


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    for n in ("wordnet", "semcor", "gloss", "folder"):
        p.add_argument(n, type=Path)
    a = p.parse_args()
    print(json.dumps(check(a.wordnet, a.semcor, a.gloss, a.folder), indent=2))
