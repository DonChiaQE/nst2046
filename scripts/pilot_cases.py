#!/usr/bin/env python3
"""Replay the two Milestone 1 pilot cases under the rules parser and Claude (`window` context, gold transcripts).

Austin (NTSB DCA23FA149, tests/fixtures/austin_dca23fa149.txt) is not in the corpus DB, so it is folded in memory from
AUSTIN_FROM on and its Claude parses are not cached: every run without --dry-run is billed. Recording 528 (Prague)
replays through atcdb.replay.build_timeline, so its Claude parses are cached and shared with the evaluation's negatives.
Prints, per case and arm, every transmission that produced a runway event, a release or a conflict.

Usage:
    python scripts/pilot_cases.py --dry-run
    python scripts/pilot_cases.py [--model claude-sonnet-5]
"""
import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from atcdb import parse_llm, parse_rules  # noqa: E402
from atcdb.engine import Handoff, NoOp, State  # noqa: E402
from atcdb.incidents import austin_lines, fold_window as fold  # noqa: E402
from atcdb.parsing import KINDS  # noqa: E402
from atcdb.replay import build_context, build_timeline, uncached_parses  # noqa: E402
from atcdb.schema import connect  # noqa: E402

PRAGUE = 528              # Air France 198R crossing 13, then CSA 38W cleared to land 13 (spec addendum A.3.9)


def austin() -> tuple[list[str], list]:
    rows = austin_lines()
    return [hhmm for hhmm, _ in rows], [tx for _, tx in rows]


def describe(e) -> str:
    arg = getattr(e, "runway", None) or (e.to if isinstance(e, Handoff) else "")
    return " ".join(p for p in (KINDS[type(e)], arg, f"[{e.callsign}]") if p)


def show(title: str, times: list[str], steps: list[tuple]) -> None:
    print(f"\n== {title} ==")
    for when, (tx, events, conflicts) in zip(times, steps):
        shown = [describe(e) for e in events if not isinstance(e, NoOp) and KINDS[type(e)] != "READBACK"]
        if not shown and not conflicts:
            continue
        print(f"{when:>8} [{tx.role}] {tx.text}")
        print(f"{'':>9}events: {'; '.join(shown) or '-'}")
        for c in conflicts:
            print(f"{'':>9}CONFLICT {c.type} {c.severity} runway {c.runway} {' vs '.join(cs or '?' for cs in c.callsigns)}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", type=Path, default=ROOT / "data/atc.sqlite")
    ap.add_argument("--model", action="append", choices=parse_llm.MODELS)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    models = args.model or ["claude-sonnet-5"]   # the pre-registered primary arm

    conn = connect(args.db)
    times, txs = austin()
    if args.dry_run:
        state = State()
        prompts = [parse_llm.render_prompt(tx, build_context("window", tx, txs[:k], state)) for k, tx in enumerate(txs)]
        for m in models:
            missing = uncached_parses(conn, PRAGUE, "llm", "gold", "window", m, transcript_model="human")
            prague = [parse_llm.render_prompt(tx, ctx) for tx, ctx in missing]
            print(f"{m}: Austin {len(prompts)} parses, Prague {len(prague)} uncached; "
                  f"about ${parse_llm.estimate_cost(m, prompts + prague):.2f}")
        return

    show("Austin, rules", times, fold(txs, parse_rules.make_parser(single_digit_runways=True)))   # KAUS
    for m in models:
        show(f"Austin, {m}", times, fold(txs, parse_llm.make_parser(m)))
    for parser, m in [("rule", "rules"), *(("llm", m) for m in models)]:
        tl = build_timeline(conn, PRAGUE, parser, "gold", "window", m, transcript_model="human")
        errors = [s.error for s in tl.steps if s.error]
        if errors:
            print(f"\n{m} on recording {PRAGUE}: {len(errors)} parse errors, first: {errors[0]}")
        show(f"Prague (recording {PRAGUE}), {m}", [f"{s.tx.start_s:.0f}s" for s in tl.steps],
             [(s.tx, s.events, s.conflicts) for s in tl.steps])


if __name__ == "__main__":
    main()
