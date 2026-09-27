#!/usr/bin/env python3
"""Parse every replayable recording once and cache the events (table `events`), reporting what was found.

Usage:
    python scripts/parse_events.py [--parser rule|llm] [--model MODEL] [--context window] [--transcript gold]
                                   [--facility Tower] [--min-transmissions 4] [--limit N] [--recording ID ...]
                                   [--db data/atc.sqlite] [--refresh | --dry-run]

Idempotent per (parser, model, version, context): re-running only parses what is missing. `--dry-run` prints how many
transmissions still need parsing and a rough cost, then stops without calling the API or writing anything. A cold
`window` run with the Claude parser is sequential, since each parse sees the engine state the previous ones built.
"""
import argparse
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from atcdb.parse_llm import estimate_cost, render_prompt  # noqa: E402
from atcdb.parsing import CONTEXT_MODES  # noqa: E402
from atcdb.replay import (PARSER_MODELS, PARSER_VERSIONS, PARSERS, build_timeline, cache_version,  # noqa: E402
                          clear_events, default_transcript_model, list_recordings, uncached_parses)
from atcdb.schema import init_db  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", type=Path, default=ROOT / "data/atc.sqlite")
    ap.add_argument("--parser", choices=sorted(PARSERS), default="rule")
    ap.add_argument("--model", help="one of the parser's models (default: its first); llm: " + ", ".join(PARSER_MODELS["llm"]))
    ap.add_argument("--context", choices=CONTEXT_MODES, default="window")
    ap.add_argument("--transcript", choices=["gold", "asr"], default="gold")
    ap.add_argument("--facility", default="Tower")
    ap.add_argument("--min-transmissions", type=int, default=4)
    ap.add_argument("--limit", type=int)
    ap.add_argument("--recording", type=int, action="append", help="only this recordings.id (repeatable)")
    ap.add_argument("--refresh", action="store_true", help="delete this parser/model/context's cached events first")
    ap.add_argument("--dry-run", action="store_true", help="count the parses still missing and estimate their cost, then stop")
    args = ap.parse_args()
    model = args.model or PARSER_MODELS[args.parser][0]
    if model not in PARSER_MODELS[args.parser]:
        ap.error(f"--model {model!r} is not a model of --parser {args.parser}; expected one of {PARSER_MODELS[args.parser]}")
    if args.refresh and args.dry_run:
        ap.error("--dry-run writes nothing, so it cannot --refresh")

    conn = init_db(args.db)
    if args.recording:
        recordings = [{"id": r} for r in args.recording]
    else:
        recordings = list_recordings(conn, facility=args.facility, min_transmissions=args.min_transmissions,
                                     transcript_kind=args.transcript)
    if args.limit:
        recordings = recordings[:args.limit]
    run = f"{args.parser}/{model}/{args.context}/{args.transcript}"
    if args.dry_run:
        misses = [m for rec in recordings for m in uncached_parses(
            conn, rec["id"], parser=args.parser, model=model, transcript_kind=args.transcript, context=args.context,
            transcript_model=default_transcript_model(conn, args.transcript, rec["id"]))]
        cost = estimate_cost(model, [render_prompt(tx, ctx) for tx, ctx in misses]) if args.parser == "llm" else 0.0
        print(f"dry run: {len(misses)} transmissions to parse in {len(recordings)} recordings ({run}); "
              f"estimated cost ${cost:.2f}")
        return
    if args.refresh:
        n = clear_events(conn, args.parser, model, cache_version(PARSER_VERSIONS[args.parser], args.context), args.context)
        print(f"cleared {n} cached events")
    kinds, conflicts, errors, n_steps = Counter(), Counter(), 0, 0
    for i, rec in enumerate(recordings, 1):
        tl = build_timeline(conn, rec["id"], parser=args.parser, model=model, transcript_kind=args.transcript,
                            context=args.context, transcript_model=default_transcript_model(conn, args.transcript, rec["id"]))
        for step in tl.steps:
            n_steps += 1
            errors += step.error is not None
            kinds.update(type(e).__name__ for e in step.events)
            conflicts.update(f"{c.type}/{c.severity}" for c in step.conflicts)
        if i % 25 == 0:
            print(f"  {i}/{len(recordings)} recordings", flush=True)
    print(f"{len(recordings)} recordings, {n_steps} transmissions, {errors} parse errors ({run})")
    print("  events:   ", dict(kinds.most_common()))
    print("  conflicts:", dict(conflicts.most_common()) or "none")


if __name__ == "__main__":
    main()
