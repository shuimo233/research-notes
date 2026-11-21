"""Observe which revision a workflow actually publishes after editing and saving."""

from functools import partial

from .. import Domain, traces


ACTIONS = ("edit:A", "edit:B", "save", "publish")
POLICIES = ("draft", "saved", "first_saved")


def predict(policy, actions):
    draft = saved = first = published = None
    has_saved = False
    for action in actions:
        if action.startswith("edit:") and action in ACTIONS:
            draft = action[5:]
        elif action == "save":
            saved = draft
            if not has_saved:
                first, has_saved = draft, True
        elif action == "publish":
            published = {"draft": draft, "saved": saved, "first_saved": first}[policy]
        else:
            raise ValueError(f"unknown action {action!r}")
    return published


def adapter(policy):
    """Local fixture. Reconstruct the publication from an event log on each call."""
    if policy not in POLICIES:
        raise ValueError(f"unknown publication policy {policy!r}")

    def observe(actions):
        if any(a not in ACTIONS for a in actions):
            raise ValueError("unknown publication action")
        publications = [i for i, a in enumerate(actions) if a == "publish"]
        if not publications:
            return None
        cutoff = publications[-1]
        if policy in ("saved", "first_saved"):
            saves = [i for i in range(cutoff) if actions[i] == "save"]
            if not saves:
                return None
            cutoff = saves[-1] if policy == "saved" else saves[0]
        return next((a[5:] for a in reversed(actions[:cutoff]) if a.startswith("edit:")), None)

    return observe


def domain():
    probes = (prefix + ("publish",) for prefix in [(), *traces(ACTIONS[:3], 4)])
    checks = (
        ("edit:A", "save", "edit:B", "save", "edit:A", "publish"),
        ("save", "edit:B", "save", "publish", "edit:A", "publish"),
    )
    return Domain("publication/revisions-v1", {k: partial(predict, k) for k in POLICIES},
                  probes, checks=checks)
