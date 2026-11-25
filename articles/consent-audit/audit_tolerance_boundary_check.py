"""Cross-check complete audits, on-boundary examples, and closed-form reductions."""

from fractions import Fraction as F
from itertools import product
import json
from pathlib import Path
import subprocess
import sys

from audit_depth import avoidance, worst_full_ratio
from audit_depth_boundary_check import direct
from audit_tolerance import (
    determining_caps,
    needed_caps,
    uniform_closed_form,
    worst_profile,
)
from audit_tolerance_check import verify_laws


def uniform():
    tried = simple = 0
    for w, k, p, gamma, cap in (
        (w, k, p, g, B)
        for w in (3, 4, 6)
        for k in range(2, w + 1)
        for (p, g), B in product(
            (
                (F(1, 20), F(1, 2)),
                (F(1, 4), F(1, 4)),
                (F(1, 2), F(1, 2)),
                (F(4, 5), F(3, 4)),
            ),
            (F(1), F(11, 10), F(3)),
        )
    ):
        caps = dict.fromkeys(range(2, k + 1), cap)
        r, witness = worst_profile(w, p, gamma, caps)
        assert r == worst_profile(w, p, gamma, {k: cap})[0]
        if cap == 1:
            assert r == worst_full_ratio(w, k, p, gamma)[0]
        answer = uniform_closed_form(w, k, p, gamma, cap)
        if answer is not None:
            assert r == answer
            simple += 1
        verify_laws(w, p, gamma, caps, r, witness)
        assert direct(w, k, p, gamma, r, caps=caps)
        tried += 1
    return tried, simple


def different():
    tried = 0
    for w, (p, gamma), (B, C) in product(
        (4, 6),
        ((F(1, 4), F(1, 4)), (F(1, 2), F(1, 2)), (F(4, 5), F(1, 3))),
        ((F(1), F(11, 10)), (F(3), F(1)), (F(1), F(3)), (F(7, 6), F(3, 2))),
    ):
        caps = {2: B, 3: C}
        r, rows = worst_profile(w, p, gamma, caps)
        verify_laws(w, p, gamma, caps, r, rows)
        assert direct(w, 3, p, gamma, r, caps=caps)
        if p >= F(1, 2):
            assert r == min(
                uniform_closed_form(w, k, p, gamma, h) for k, h in caps.items()
            )
        tried += 1
    p, gamma = F(1, 4), F(1, 4)
    r, rows = worst_profile(4, p, gamma, {2: 1, 3: F(11, 10)})
    assert r == F(68, 43)
    assert worst_profile(4, p, gamma, {2: 1})[0] == F(155, 91)
    assert worst_profile(4, p, gamma, {3: F(11, 10)})[0] == F(47, 27)
    assert avoidance(rows[0], 2) == avoidance(rows[1], 2)
    assert avoidance(rows[0], 3) == F(11, 10) * avoidance(rows[1], 3)
    assert needed_caps({2: F(11, 10), 3: F(6, 5)}) == {3: F(6, 5)}
    tool = str(Path(__file__).with_name("audit_tolerance.py"))
    raw = subprocess.check_output(
        [sys.executable, "-B", tool, "4", "1/4", "1/4", "2=1", "3=11/10", "--explain"]
    )
    assert json.loads(raw)["ratio"] == "68/43"
    assert json.loads(raw)["determining_caps"] == {"2": "1", "3": "11/10"}
    return tried


if __name__ == "__main__":
    if not __debug__:
        raise RuntimeError("enable assertions")
    n, s = uniform()
    profiles = (
        {2: F(11, 10), 3: F(5, 4), 4: F(7, 6), 5: F(2), 6: F(3)},
        {2: F(1), 3: F(11, 10), 4: F(3, 2), 5: F(7, 2)},
    )
    for caps, p in product(profiles, (F(1, 5), F(1, 2), F(4, 5))):
        core = determining_caps(6, p, F(1, 2), caps)
        assert len(core) <= (1 if p >= F(1, 2) else 2)
        assert (
            worst_profile(6, p, F(1, 2), core)[0]
            == worst_profile(6, p, F(1, 2), caps)[0]
        )
    print(
        json.dumps(
            dict(
                uniform_lp=n,
                uniform_simple_threshold=s,
                mixed_lp=different(),
                junction=True,
                reduced_profiles=6,
            )
        )
    )
