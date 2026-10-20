"""Real incidents outside the corpus DB, read from NTSB transcripts (spec addendum A.3.9).

Austin (NTSB DCA23FA149) is public record and lives in tests/fixtures/austin_dca23fa149.txt, one `time|ident|text` line
per transmission. The tests pin the rules parser's result on it; scripts/pilot_cases.py replays it under each parser.
"""
import re
from pathlib import Path

from atcdb.parsing import Transmission


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
