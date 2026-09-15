"""Replay: fold one recording's transmissions through a parser and the engine, one step per transmission.

`get_events` is the single cache path (cached rows from `events`, or parse-and-store on a miss); the
precompute script and the web API both go through it. `build_timeline` folds the cached/parsed events so
"state after transmission k" is available for every k, which is what the replay UI scrubs through.
"""
import sqlite3
from dataclasses import dataclass

from atcdb import parse_rules
from atcdb.engine import Conflict, Event, State, apply
from atcdb.parsing import CONTEXT_MODES, WINDOW, Context, Parser, Transmission, event_to_row, row_to_event

PARSERS: dict[str, Parser] = {"rule": parse_rules.parse}
PARSER_MODELS: dict[str, tuple[str, str]] = {"rule": ("rules", parse_rules.VERSION)}   # parser -> (model, model_version)


@dataclass(frozen=True)
class Step:
    tx: Transmission
    events: tuple[Event, ...]
    conflicts: tuple[Conflict, ...]   # raised by this transmission's events
    state: State                      # after this transmission
    error: str | None = None          # parser failure: events are empty and the fold simply continued


@dataclass(frozen=True)
class Timeline:
    recording_id: int
    parser: str
    model: str
    model_version: str
    context: str
    transcript_kind: str
    steps: tuple[Step, ...]


def load_recording(conn: sqlite3.Connection, recording_id: int, transcript_kind: str = "gold",
                   transcript_model: str | None = None) -> list[Transmission]:
    """Transmissions of a recording in time order, each with one transcript of the given kind (and model, if given).
    Transmissions without such a transcript are skipped."""
    rows = conn.execute(
        """SELECT x.id, x.start_s, x.speaker_role, t.id AS transcript_id, t.normalized_text
           FROM transmissions x
           JOIN transcripts t ON t.id = (SELECT id FROM transcripts WHERE transmission_id = x.id AND kind = ?
                                         AND (? IS NULL OR model = ?) ORDER BY id LIMIT 1)
           WHERE x.recording_id = ?
           ORDER BY x.start_s, x.id""", (transcript_kind, transcript_model, transcript_model, recording_id)).fetchall()
    return [Transmission(id=r["id"], transcript_id=r["transcript_id"], text=r["normalized_text"], role=r["speaker_role"],
                         start_s=r["start_s"] or 0.0) for r in rows]


def build_context(mode: str, tx: Transmission, history: list[Transmission], state: State) -> Context:
    """The parser's view for one transmission. `none` = text only; `role` = + speaker role; `window` = + the last
    WINDOW transmissions and what the engine is currently tracking."""
    if mode not in CONTEXT_MODES:
        raise ValueError(f"unknown context mode {mode!r}; expected one of {CONTEXT_MODES}")
    if mode == "none":
        return Context(mode="none")
    if mode == "role":
        return Context(mode="role", role=tx.role)
    active = tuple(cs for cs, a in state.aircraft.items() if cs and (a.runway or a.holding_short or a.pending))
    return Context(mode="window", role=tx.role, history=tuple((h.role, h.text) for h in history[-WINDOW:]),
                   active_callsigns=active, active_runways=tuple(sorted(state.runways)))


def list_recordings(conn: sqlite3.Connection, facility: str = "Tower", min_transmissions: int = 4,
                    transcript_kind: str = "gold") -> list[sqlite3.Row]:
    """Recordings worth replaying: the given facility, enough transmissions, at least one runway mention."""
    return conn.execute(
        """SELECT r.id, s.name AS source, r.external_id, r.airport_icao, r.facility,
                  COUNT(DISTINCT x.id) AS n_transmissions,
                  COUNT(DISTINCT CASE WHEN t.normalized_text LIKE '%runway%' THEN x.id END) AS n_runway_mentions
           FROM recordings r
           JOIN sources s ON s.id = r.source_id
           JOIN transmissions x ON x.recording_id = r.id
           JOIN transcripts t ON t.transmission_id = x.id AND t.kind = ?
           WHERE r.facility = ?
           GROUP BY r.id
           HAVING n_transmissions >= ? AND n_runway_mentions >= 1
           ORDER BY n_transmissions DESC, r.id""", (transcript_kind, facility, min_transmissions)).fetchall()


def get_events(*args, **kwargs):
    raise NotImplementedError   # Task 10


def build_timeline(*args, **kwargs):
    raise NotImplementedError   # Task 10
