#!/usr/bin/env python3
"""Print one recording's replay: each transmission, the events parsed from it, the conflicts raised, and the runway
board after it. The phase-1 demo, before the web UI exists.

Usage:
    python scripts/show_replay.py RECORDING [--parser rule] [--context window] [--transcript gold] [--db data/atc.sqlite]

RECORDING is a recordings.id or a recordings.external_id (e.g. uwb-atcc_TWR-DM7AI0).
"""
import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from atcdb.engine import RunwayInstruction  # noqa: E402
from atcdb.parsing import CONTEXT_MODES  # noqa: E402
from atcdb.replay import PARSERS, build_timeline, default_transcript_model  # noqa: E402
from atcdb.schema import init_db  # noqa: E402

ROLE = {"controller": "CTL", "pilot": "PLT", "mixed": "MIX", "unknown": "???"}


def _event(e) -> str:
    if isinstance(e, RunwayInstruction):
        return f"{type(e).__name__}({e.callsign!r}, {e.runway})"
    extra = f", to={e.to}" if hasattr(e, "to") else ""
    return f"{type(e).__name__}({e.callsign!r}{extra})"


def _board(state) -> str:
    cells = [f"{rwy}: " + ", ".join(f"{r.callsign or '?'} {r.kind}" for r in res) for rwy, res in sorted(state.runways.items())]
    return " | ".join(cells) if cells else "(all runways clear)"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("recording")
    ap.add_argument("--db", type=Path, default=ROOT / "data/atc.sqlite")
    ap.add_argument("--parser", choices=sorted(PARSERS), default="rule")
    ap.add_argument("--context", choices=CONTEXT_MODES, default="window")
    ap.add_argument("--transcript", choices=["gold", "asr"], default="gold")
    args = ap.parse_args()

    conn = init_db(args.db)
    row = conn.execute("SELECT id, external_id FROM recordings WHERE id = ? OR external_id = ?",
                       (args.recording if args.recording.isdigit() else -1, args.recording)).fetchone()
    if row is None:
        sys.exit(f"no recording {args.recording!r}")
    tl = build_timeline(conn, row["id"], parser=args.parser, transcript_kind=args.transcript, context=args.context,
                       transcript_model=default_transcript_model(conn, args.transcript, row["id"]))
    print(f"recording {row['id']} ({row['external_id']}) — {len(tl.steps)} transmissions — {tl.parser}/{tl.context}/{tl.transcript_kind}\n")
    for k, s in enumerate(tl.steps):
        m, sec = divmod(int(s.tx.start_s), 60)
        print(f"[{k:2d}] {m:02d}:{sec:02d} {ROLE.get(s.tx.role, '???')}  {s.tx.text}")
        for e in s.events:
            print(f"        -> {_event(e)}")
        if s.error:
            print(f"        !! parse error: {s.error}")
        for c in s.conflicts:
            print(f"        !! {c.severity.upper()} {c.type}: {c.explanation}")
        print(f"        board: {_board(s.state)}")
    n = sum(len(s.conflicts) for s in tl.steps)
    print(f"\n{n} conflict(s)")


if __name__ == "__main__":
    main()
