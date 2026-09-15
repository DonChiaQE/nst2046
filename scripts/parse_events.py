#!/usr/bin/env python3
"""Parse every replayable recording once and cache the events (table `events`), reporting what was found.

Usage:
    python scripts/parse_events.py [--parser rule] [--context window] [--transcript gold]
                                   [--facility Tower] [--min-transmissions 4] [--limit N] [--db data/atc.sqlite]

Idempotent per (parser, model, version, context): re-running only parses what is missing.
"""
import argparse
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from atcdb.parsing import CONTEXT_MODES  # noqa: E402
from atcdb.replay import PARSERS, build_timeline, list_recordings  # noqa: E402
from atcdb.schema import init_db  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", type=Path, default=ROOT / "data/atc.sqlite")
    ap.add_argument("--parser", choices=sorted(PARSERS), default="rule")
    ap.add_argument("--context", choices=CONTEXT_MODES, default="window")
    ap.add_argument("--transcript", choices=["gold", "asr"], default="gold")
    ap.add_argument("--facility", default="Tower")
    ap.add_argument("--min-transmissions", type=int, default=4)
    ap.add_argument("--limit", type=int)
    args = ap.parse_args()

    conn = init_db(args.db)
    recordings = list_recordings(conn, facility=args.facility, min_transmissions=args.min_transmissions, transcript_kind=args.transcript)
    if args.limit:
        recordings = recordings[:args.limit]
    kinds, conflicts, errors, n_steps = Counter(), Counter(), 0, 0
    for i, rec in enumerate(recordings, 1):
        tl = build_timeline(conn, rec["id"], parser=args.parser, transcript_kind=args.transcript, context=args.context)
        for step in tl.steps:
            n_steps += 1
            errors += step.error is not None
            kinds.update(type(e).__name__ for e in step.events)
            conflicts.update(f"{c.type}/{c.severity}" for c in step.conflicts)
        if i % 25 == 0:
            print(f"  {i}/{len(recordings)} recordings", flush=True)
    print(f"{len(recordings)} recordings, {n_steps} transmissions, {errors} parse errors "
          f"({args.parser}/{args.context}/{args.transcript})")
    print("  events:   ", dict(kinds.most_common()))
    print("  conflicts:", dict(conflicts.most_common()) or "none")


if __name__ == "__main__":
    main()
