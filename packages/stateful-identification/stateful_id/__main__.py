"""Command line examples and offline evidence replay."""

import argparse
from dataclasses import asdict
import json
from pathlib import Path
import sys

from . import Budget, Journal, identify, replay
from .examples import publish, sqlite_policy


DOMAINS = {"publish": publish, "sqlite": sqlite_policy}


def main(argv=None):
    parser = argparse.ArgumentParser(description="Identify a deterministic rule or replay its observations.")
    commands = parser.add_subparsers(dest="command", required=True)
    demo = commands.add_parser("demo", help="observe a resettable example")
    offline = commands.add_parser("replay", help="read a journal without running its adapter")
    for cmd in (demo, offline):
        cmd.add_argument("domain", choices=tuple(DOMAINS))
        cmd.add_argument("--predict", nargs="*", metavar="ACTION", help="predict a new cold-start trace")
    demo.add_argument("--truth", required=True, help="example adapter configuration")
    demo.add_argument("--queries", type=int)
    demo.add_argument("--cost", type=int)
    demo.add_argument("--strategy", choices=("active", "fixed"))
    demo.add_argument("--save", type=Path, metavar="JOURNAL")
    demo.add_argument("--resume", type=Path, metavar="JOURNAL",
                      help="continue a prior run against the same adapter configuration")
    offline.add_argument("journal", type=Path)
    args = parser.parse_args(argv)
    module = DOMAINS[args.domain]
    domain = module.domain()
    try:
        if args.command == "demo":
            if args.truth not in module.POLICIES:
                parser.error("expected --truth from " + ", ".join(module.POLICIES))
            journal = Journal.load(args.resume) if args.resume else None
            limits = journal.budget if journal is not None and journal.budget is not None else Budget(200, 1000)
            budget = Budget(limits.queries if args.queries is None else args.queries,
                            limits.cost if args.cost is None else args.cost)
            result = identify(domain, module.adapter(args.truth), budget, strategy=args.strategy,
                              journal=journal, checkpoint=args.save or args.resume,
                              source_id=f"demo/{args.domain}/{args.truth}")
        else:
            result = replay(domain, Journal.load(args.journal))
        output = {
            "domain": domain.id, "status": result.status, "reason": result.reason,
            "candidates": result.candidates, "spent": asdict(result.spent),
            "steps": [dict(s.entry.record(), phase=s.phase, before=s.before, after=s.after)
                      for s in result.steps],
            "next_probe": asdict(result.next_probe) if result.next_probe is not None else None,
        }
        if result.status == "conflict":
            output["conflict_predictions"] = result.conflict_predictions
        if args.predict is not None and result.model is not None:
            if any(a not in module.ACTIONS for a in args.predict):
                parser.error("unknown prediction action; expected one of " + ", ".join(module.ACTIONS))
            output["prediction"] = result.model(tuple(args.predict))
        print(json.dumps(output, ensure_ascii=False, indent=2))
    except (ValueError, OSError) as exc:
        parser.exit(2, f"{parser.prog}: {exc}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
