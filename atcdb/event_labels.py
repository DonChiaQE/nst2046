"""The Level 1 event labelling sheet (spec 2026-09-29-evaluation-3b1-design.md, section 8).

`sample_event_sheet` draws transmissions uniformly from the `test`-split transmissions of the replayable real tower
recordings, independent of every parser, so the sheet can find what no parser finds and its ASR factor is clean (the
Whisper model was fine-tuned on the `train` split). `parse_event_cell` reads the `events` cell a labeller wrote back into
engine events, so a malformed cell is caught when the sheet is read rather than at scoring time.

Cell syntax, one event per line:
    land|takeoff|luaw|cross|hold_short <runway> [callsign words]   e.g. "land 31 csa one two three"
    handoff <ground|departure|tower|approach> [callsign words]
    vacated|go_around|readback [callsign words]
    noop                                                            (alone: the transmission has no runway event)
The runway goes in digits with an optional L/R/C (31, 04L) and is checked with `normalize_runway`.
"""
import random
import sqlite3

from atcdb.engine import (HANDOFF_TARGETS, ClearTakeoff, ClearToCross, ClearToLand, Event, GoAround, Handoff, HoldShort,
                          LineUpAndWait, ReadbackObserved, RunwayVacated, normalize_runway)
from atcdb.replay import default_transcript_model, load_recording, real_recordings

COLUMNS = ["row_id", "transmission_id", "recording_id", "role", "context", "text", "clip_path", "events", "notes"]
CONTEXT_LINES = 4   # previous transmissions shown on the sheet, as the `window` context mode sees them

_RUNWAY_KINDS = {"land": ClearToLand, "takeoff": ClearTakeoff, "luaw": LineUpAndWait, "cross": ClearToCross,
                 "hold_short": HoldShort}
_PLAIN_KINDS = {"vacated": RunwayVacated, "go_around": GoAround}


def sample_event_sheet(conn: sqlite3.Connection, n: int = 200, seed: int = 0) -> list[dict]:
    """`n` rows for the sheet, sampled uniformly (seeded) from the `test`-split transmissions of the replayable tower
    recordings, in random order. Each row carries the human gold text and the previous CONTEXT_LINES lines with roles.
    No parser output is included."""
    candidates = []
    for rec in real_recordings(conn):
        txs = load_recording(conn, rec["id"], "gold", default_transcript_model(conn, "gold", rec["id"]))
        meta = {r["id"]: r for r in conn.execute(
            "SELECT id, split, clip_path FROM transmissions WHERE recording_id = ?", (rec["id"],))}
        for k, tx in enumerate(txs):
            if meta[tx.id]["split"] == "test":
                context = "\n".join(f"[{h.role}] {h.text}" for h in txs[max(0, k - CONTEXT_LINES):k])
                candidates.append({"transmission_id": tx.id, "recording_id": rec["id"], "role": tx.role,
                                   "context": context, "text": tx.text, "clip_path": meta[tx.id]["clip_path"] or ""})
    candidates.sort(key=lambda c: c["transmission_id"])
    chosen = random.Random(seed).sample(candidates, min(n, len(candidates)))
    return [{"row_id": i + 1, **c, "events": "", "notes": ""} for i, c in enumerate(chosen)]


def parse_event_cell(cell: str) -> list[Event]:
    """A labeller's `events` cell as engine events, in order. `noop` (alone) is an empty list. Raises ValueError naming
    the offending line on anything else that does not follow the syntax in the module docstring, including an empty
    cell (an unlabelled row is not a transmission without events)."""
    lines = [ln.split() for ln in (cell or "").strip().lower().splitlines() if ln.strip()]
    if not lines:
        raise ValueError("empty cell: write `noop` for a transmission with no runway event")
    if lines == [["noop"]]:
        return []
    events: list[Event] = []
    for words in lines:
        kind, rest = words[0], words[1:]
        line = " ".join(words)
        if kind in _RUNWAY_KINDS:
            runway = normalize_runway(rest[0]) if rest else None
            if runway is None:
                raise ValueError(f"{line!r}: {kind} needs a runway in digits, e.g. `{kind} 31 csa one two three`")
            events.append(_RUNWAY_KINDS[kind](runway=runway, callsign=" ".join(rest[1:])))
        elif kind == "handoff":
            if not rest or rest[0] not in HANDOFF_TARGETS:
                raise ValueError(f"{line!r}: handoff needs a target, one of {', '.join(HANDOFF_TARGETS)}")
            events.append(Handoff(to=rest[0], callsign=" ".join(rest[1:])))
        elif kind in _PLAIN_KINDS:
            events.append(_PLAIN_KINDS[kind](callsign=" ".join(rest)))
        elif kind == "readback":
            events.append(ReadbackObserved(callsign=" ".join(rest), text=""))
        elif kind == "noop":
            raise ValueError(f"{line!r}: `noop` must be the only line in the cell")
        else:
            raise ValueError(f"{line!r}: unknown kind {kind!r}")
    return events
