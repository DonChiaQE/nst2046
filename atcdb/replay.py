"""Replay: fold one recording's transmissions through a parser and the engine, one step per transmission.

`get_events` is the single cache path (cached rows from `events`, or parse-and-store on a miss); the
precompute script and the web API both go through it. `build_timeline` folds the cached/parsed events so
"state after transmission k" is available for every k, which is what the replay UI scrubs through.
Window-mode parses depend on engine state, so after changing engine rules run `scripts/parse_events.py
--refresh` (see `clear_events`).
"""
import sqlite3
from dataclasses import dataclass

from atcdb import parse_rules
from atcdb.engine import Conflict, Event, NoOp, State, apply
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
                    transcript_kind: str = "gold") -> list[dict]:
    """Recordings worth replaying: the given facility, enough transmissions, at least one runway mention."""
    rows = conn.execute(
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
    return [dict(r) for r in rows]


def get_recording(conn: sqlite3.Connection, recording_id: int) -> dict | None:
    """One recording's identity (id, source, external_id, airport_icao, facility), or None if the id is unknown.
    Distinguishes "no such recording" from "a recording with no transcripts of the requested kind"."""
    row = conn.execute(
        """SELECT r.id, s.name AS source, r.external_id, r.airport_icao, r.facility
           FROM recordings r JOIN sources s ON s.id = r.source_id
           WHERE r.id = ?""", (recording_id,)).fetchone()
    return dict(row) if row else None


def transcript_models(conn: sqlite3.Connection) -> dict[str, list[str]]:
    """Transcript kinds present in the DB, each with its models in alphabetical order."""
    out: dict[str, list[str]] = {}
    for r in conn.execute("SELECT DISTINCT kind, model FROM transcripts ORDER BY kind, model"):
        out.setdefault(r["kind"], []).append(r["model"])
    return out


def default_transcript_model(conn: sqlite3.Connection, transcript_kind: str) -> str | None:
    """The transcript model a replay pins when none is given, so cache keys do not drift between runs: `human` for
    gold (some transmissions also carry an `atco2-xml` gold transcript), otherwise the alphabetically first model.
    None when the DB has no transcripts of that kind."""
    models = transcript_models(conn).get(transcript_kind, [])
    if transcript_kind == "gold" and "human" in models:
        return "human"
    return models[0] if models else None


def _cached_events(conn: sqlite3.Connection, tx: Transmission, parser: str, model: str, model_version: str,
                   mode: str) -> list[Event]:
    rows = conn.execute(
        """SELECT kind, callsign, runway, extra_json FROM events
           WHERE transcript_id = ? AND parser = ? AND model = ? AND model_version = ? AND context = ?
           ORDER BY seq""", (tx.transcript_id, parser, model, model_version, mode)).fetchall()
    return [row_to_event(r["kind"], r["callsign"], r["runway"], r["extra_json"], t=tx.start_s, text=tx.text) for r in rows]


def get_events(conn: sqlite3.Connection, tx: Transmission, parser: str, ctx: Context,
               model: str | None = None, model_version: str | None = None) -> list[Event]:
    """Events for one transcript under (parser, model, version, context mode): from the `events` cache, or parsed
    and stored. A parser exception propagates and nothing is stored, so the next call retries. An empty parse is
    stored as one NOOP row, so the transcript is not a cache miss forever. If another request cached the same
    transcript while this one was parsing, the first writer's parse wins: it is what stays cached and what is returned,
    so the cache never mixes rows from two different parses."""
    if model is None:
        model, model_version = PARSER_MODELS[parser]
    model_version = model_version or ""
    cached = _cached_events(conn, tx, parser, model, model_version, ctx.mode)
    if cached:
        return cached
    events = PARSERS[parser](tx, ctx) or [NoOp(t=tx.start_s, text=tx.text)]
    try:
        conn.executemany(
            """INSERT INTO events (transcript_id, parser, model, model_version, context, seq, kind, callsign, runway, extra_json)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            [(tx.transcript_id, parser, model, model_version, ctx.mode, i, *event_to_row(e)) for i, e in enumerate(events)])
        conn.commit()
    except sqlite3.IntegrityError:
        conn.rollback()   # lost the race: nothing of ours is kept
        return _cached_events(conn, tx, parser, model, model_version, ctx.mode)
    except Exception:
        conn.rollback()   # a partial insert must never be committed later by someone else's commit
        raise
    return events


def clear_events(conn: sqlite3.Connection, parser: str, model: str | None = None, model_version: str | None = None,
                 context: str | None = None) -> int:
    """Delete cached events for a parser (optionally narrowed to model / version / context mode). Returns rows deleted.
    Needed because `window`-mode parses depend on engine state: after tuning engine rules, refresh the cache."""
    sql, params = "DELETE FROM events WHERE parser = ?", [parser]
    for col, val in (("model", model), ("model_version", model_version), ("context", context)):
        if val is not None:
            sql += f" AND {col} = ?"
            params.append(val)
    n = conn.execute(sql, params).rowcount
    conn.commit()
    return n


def build_timeline(conn: sqlite3.Connection, recording_id: int, parser: str = "rule", transcript_kind: str = "gold",
                   context: str = "window", model: str | None = None, model_version: str | None = None,
                   transcript_model: str | None = None) -> Timeline:
    """Fold a whole recording: one Step per transmission with its events, the conflicts they raised and the state after."""
    if model is None:
        model, model_version = PARSER_MODELS[parser]
    txs = load_recording(conn, recording_id, transcript_kind, transcript_model)
    state = State()
    steps: list[Step] = []
    for k, tx in enumerate(txs):
        ctx = build_context(context, tx, txs[:k], state)
        error = None
        try:
            events = get_events(conn, tx, parser, ctx, model, model_version)
        except Exception as e:   # a flaky parser (API error) must not break the replay; nothing was cached
            events, error = [], f"{type(e).__name__}: {e}"
        conflicts: list[Conflict] = []
        for e in events:
            state, new = apply(state, e)
            conflicts.extend(new)
        steps.append(Step(tx=tx, events=tuple(events), conflicts=tuple(conflicts), state=state, error=error))
    return Timeline(recording_id, parser, model, model_version or "", context, transcript_kind, tuple(steps))
