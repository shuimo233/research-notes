"""Run the registered matched-width comparison in a single CPU session."""

import argparse
import gzip
from hashlib import sha256
import json
from pathlib import Path
import platform
from random import Random
from time import perf_counter_ns

import numpy as np
import onnxruntime as ort
from tokenizers import Tokenizer

from audit_runtime_latency_check import (
    ARMS,
    CASES,
    GRAPH,
    MODES,
    RESULTS,
    TRACE,
    expected,
    load_records,
    process_cost,
    semantic_order,
    summarize,
)
from audit_runtime_pack import routed_batch
from go_model_fetch import verify
from point_runtime import make_session
from rte_context_fetch import FILES


def encoded_rows(input_file, model, rows):
    path = model / "tokenizer.json"
    verify(path, FILES["tokenizer.json"])
    tok = Tokenizer.from_file(str(path))
    tok.enable_truncation(512)
    tok.no_padding()
    if tok.token_to_id("[PAD]") != 0:
        raise ValueError("unexpected pad token")
    encoded = {}
    for c, slot, w, ref, p, h, truth in json.loads(input_file.read_bytes()):
        row = rows[c, w][slot]
        assert (
            int(row["source"]),
            row["premise"],
            row["hypothesis"],
            int(row["gold"]),
        ) == (
            ref,
            sha256(p.encode()).hexdigest(),
            sha256(h.encode()).hexdigest(),
            truth,
        )
        ids = tok.encode(p, h).ids
        assert len(ids) == int(row["length"])
        group = encoded.setdefault((c, w), [])
        assert len(group) == slot
        group.append(ids)
    assert set(encoded) == set(rows) and all(
        len(value) == 8 for value in encoded.values()
    )
    return encoded


def balanced(grouping, rng):
    route = []
    for b in grouping:
        option = rng.sample(range(8), 8)
        route.extend((j, option) for j in b)
    return list(map(list, zip(*(opt for _, opt in sorted(route)), strict=True)))


def timings(by_case):
    rng = Random(7340826)
    individual = [[i] for i in range(8)]
    for repetition in range(2):
        for c in CASES:
            for w in range(3):
                first = balanced(individual, rng)
                alt = first + balanced(by_case[c], rng)
                control = first + balanced(individual, rng)
                for k, (a, b) in enumerate(zip(control, alt, strict=True)):
                    yield [repetition, c, w, k], {"independent": a, "partition": b}


def scores_as_bytes(z):
    assert z.shape == (8, 3) and z.dtype == np.float32 and np.isfinite(z).all()
    return z.astype("<f4", copy=False).tobytes()


def run(encoded, ledger, plans, model, graph, folder, semantic_only=False):
    verify(graph, GRAPH)
    rows, by_case = load_records(ledger, plans)
    tokens = encoded_rows(encoded, model, rows)
    session = make_session(graph)
    digest = sha256()
    scores = 0
    for c, w, route in semantic_order():
        outputs = routed_batch(session, tokens[c, w], [MODES[x] for x in route])
        actual = scores_as_bytes(outputs)
        assert actual == expected(rows[c, w], route), (c, w, route)
        digest.update(actual)
        scores += outputs.size
    exact = {"scores": scores, "graph": GRAPH, "score_sha256": digest.hexdigest()}
    print(json.dumps({"verified_semantics": exact}), flush=True)
    if semantic_only:
        return
    metadata = {
        "os": platform.system(),
        "os_release": platform.release(),
        "processor": platform.processor(),
        "machine": platform.machine(),
        "python": platform.python_version(),
        "onnxruntime": ort.__version__,
        "numpy": np.__version__,
        "threads": 4,
        "provider": session.get_providers(),
    }
    warm = [MODES[x] for x in range(8)]
    for arm in ARMS:
        routed_batch(
            session, tokens[CASES[0], 0], warm, bucketed=arm.startswith("bucket")
        )
    batches = []
    for key, routes in timings(by_case):
        r, c, w, k = key
        order = list(ARMS)
        shift = (r + c + w + k) % 4
        order = order[shift:] + order[:shift]
        observed = {}
        times = {}
        for arm in order:
            engine, schedule = arm.split("_")
            args = [MODES[x] for x in routes[schedule]]
            start = perf_counter_ns()
            result = routed_batch(
                session, tokens[c, w], args, bucketed=engine == "bucket"
            )
            times[arm] = perf_counter_ns() - start
            actual = scores_as_bytes(result)
            assert actual == expected(rows[c, w], routes[schedule]), (key, arm)
            observed[schedule] = sha256(actual).hexdigest()
        batches.append(
            {
                "key": key,
                "routes": routes,
                "order": order,
                "timing": times,
                "digest": observed,
                "work": {s: process_cost(rows[c, w], v) for s, v in routes.items()},
            }
        )
        if k == 15 and w == 2:
            print(
                json.dumps(
                    {"timed_round": r + 1, "catalog": c, "samples": len(batches) * 4}
                ),
                flush=True,
            )

    data = {"semantic": exact, "platform": metadata, "batches": batches}
    answer = summarize(ledger, plans, data)
    folder.mkdir(parents=True, exist_ok=True)
    (folder / TRACE).write_bytes(
        gzip.compress(json.dumps(data, separators=(",", ":")).encode(), mtime=0)
    )
    (folder / RESULTS).write_text(
        json.dumps(answer, indent=2) + "\n", encoding="utf-8", newline="\n"
    )
    print(
        json.dumps(
            {
                "measurements": answer["measurements"],
                "passes_latency_gate": answer["passes_latency_gate"],
            }
        )
    )


if __name__ == "__main__":
    cli = argparse.ArgumentParser(description=__doc__)
    for name in ("selected", "ledger", "plans", "model", "graph", "folder"):
        cli.add_argument(name, type=Path)
    cli.add_argument("--semantic-only", action="store_true")
    a = cli.parse_args()
    run(a.selected, a.ledger, a.plans, a.model, a.graph, a.folder, a.semantic_only)
