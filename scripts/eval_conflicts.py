#!/usr/bin/env python3
"""Level 2 conflict evaluation (spec 2026-09-29-evaluation-3b1-design.md, sections 5 to 10).

Usage:
    python scripts/eval_conflicts.py run [--parser rule|llm] [--model M] [--context C] [--transcript gold|asr]
                                         [--set negatives|positives] [--workers N] [--dry-run]

`run` replays every recording of the evaluation sets under each selected arm (all 18 by default) and writes one JSONL
per arm to data/eval/conflicts/. Parses come from the events cache, so a re-run is free; always `--dry-run` first, which
prints the uncached calls and a rough cost per arm and spends nothing.
"""
import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from atcdb.evaluate import ARMS, evaluation_sets, run_arm, uncached, write_rows  # noqa: E402
from atcdb.schema import init_db  # noqa: E402

OUT = ROOT / "data/eval/conflicts"


def selected_arms(args: argparse.Namespace) -> list:
    return [a for a in ARMS if all(getattr(args, f) in (None, getattr(a, f)) for f in ("parser", "model", "context", "transcript"))]


def cmd_run(args: argparse.Namespace) -> None:
    conn = init_db(args.db)
    items = [it for it in evaluation_sets(conn) if args.set in (None, it[1])]
    arms = selected_arms(args)
    if not arms:
        sys.exit("no arm matches the filters")
    if args.dry_run:
        total = 0.0
        for arm in arms:
            n, cost = uncached(conn, arm, [rid for rid, _, _ in items])
            total += cost
            print(f"  {arm.name:<40} {n:>5} uncached calls  ${cost:.2f}")
        print(f"dry run: {len(items)} recordings, {len(arms)} arms, estimated ${total:.2f}")
        return
    for arm in arms:
        rows = run_arm(args.db, arm, items, workers=args.workers)
        write_rows(args.out / f"{arm.name}.jsonl", rows)
        incomplete = sum(r["incomplete"] for r in rows)
        print(f"  {arm.name:<40} {len(rows)} recordings, {incomplete} incomplete", flush=True)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", type=Path, default=ROOT / "data/atc.sqlite")
    ap.add_argument("--out", type=Path, default=OUT)
    sub = ap.add_subparsers(dest="command", required=True)
    run = sub.add_parser("run", help="replay the evaluation sets under each arm")
    run.add_argument("--parser", choices=["rule", "llm"])
    run.add_argument("--model")
    run.add_argument("--context", choices=["none", "role", "window"])
    run.add_argument("--transcript", choices=["gold", "asr"])
    run.add_argument("--set", choices=["negatives", "positives"])
    run.add_argument("--workers", type=int, default=4)
    run.add_argument("--dry-run", action="store_true")
    run.set_defaults(func=cmd_run)
    args = ap.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
