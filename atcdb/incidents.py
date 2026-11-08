"""Real incidents outside the corpus DB, read from NTSB transcripts (spec addendum A.3.9).

Austin (NTSB DCA23FA149) is public record and lives in tests/fixtures/austin_dca23fa149.txt, one `time|ident|text` line
per transmission. The tests pin the rules parser's result on it; scripts/pilot_cases.py replays it under each parser,
and the live demo app offers it as a replay scenario (atcdb/live_hub.py). `fold_window` is the reference fold both use:
`window` context, no events cache.
"""
import re
from pathlib import Path

from atcdb.engine import Conflict, Event, State, apply
from atcdb.parsing import Parser, Transmission
from atcdb.replay import build_context

ROOT = Path(__file__).resolve().parents[1]
AUSTIN_FIXTURE = ROOT / "tests/fixtures/austin_dca23fa149.txt"
AUSTIN_FROM = "0628:26"   # Spirit 1145's 18R departure; every earlier 18L departure has already been sent to departure


def load_ntsb_transcript(path: Path) -> list[tuple[str, Transmission]]:
    """(time, transmission) for every on-frequency line. Intrafacility lines are controller-to-controller, not radio,
    and are dropped; bracketed annotations ([indiscernible], [break in transmission]) are removed."""
    out, last = [], ""
    for line in path.read_text().splitlines():
        if not line.strip() or line.startswith("#"):
            continue
        hhmm, ident, text = line.split("|", 2)
        last = hhmm or last
        if "[intrafacility]" in text:
            continue
        t = int(last[:2]) * 3600 + int(last[2:4]) * 60 + int(last[5:7])
        role = "controller" if ident.startswith("AUS-") else "unknown" if ident == "UNK" else "pilot"
        clean = re.sub(r"\s+", " ", re.sub(r"\[[^\]]*\]", " ", text)).strip().lower()
        out.append((last, Transmission(id=len(out), transcript_id=len(out), text=clean, role=role, start_s=float(t))))
    return out


def austin_lines(start: str = AUSTIN_FROM) -> list[tuple[str, Transmission]]:
    """The Austin transcript from `start` on, as (time, transmission)."""
    rows = load_ntsb_transcript(AUSTIN_FIXTURE)
    k = next(i for i, (hhmm, _) in enumerate(rows) if hhmm == start)
    return rows[k:]


def fold_window(txs: list[Transmission], parse: Parser, single_digit_runways: bool = False
                ) -> list[tuple[Transmission, list[Event], list[Conflict]]]:
    """(transmission, events, conflicts) per transmission, folding as `replay.build_timeline` does in `window` context
    but without the events cache.

    `single_digit_runways` is the replayed airport's phraseology convention, forwarded to the parser: pass True only
    for an airport where a lone digit-word is a real designator (a US tower). See atcdb/parse_rules.py, `_patterns`.
    """
    state, out = State(), []
    for k, tx in enumerate(txs):
        events = list(parse(tx, build_context("window", tx, txs[:k], state, single_digit_runways)))
        conflicts: list[Conflict] = []
        for e in events:
            state, new = apply(state, e)
            conflicts.extend(new)
        out.append((tx, events, conflicts))
    return out
