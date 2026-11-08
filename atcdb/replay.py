"""Replay: fold one recording's transmissions through a parser and the engine, one step per transmission.

`get_events` is the single cache path (cached rows from `events`, or parse-and-store on a miss); the
precompute script and the web API both go through it. `build_timeline` folds the cached/parsed events so
"state after transmission k" is available for every k, which is what the replay UI scrubs through.
Window-mode parses depend on engine state, so their cache key carries `engine.ENGINE_VERSION` (see `cache_version`):
bump it after changing engine rules and the old window parses are simply never read again.
"""
import sqlite3
from dataclasses import dataclass
from typing import Callable

from atcdb import engine, parse_llm, parse_rules
from atcdb.engine import Conflict, Event, NoOp, State, apply
from atcdb.parsing import CONTEXT_MODES, WINDOW, Context, Parser, Transmission, event_to_row, row_to_event

# parser -> factory taking a model id. `get_events` calls it only on a cache miss, so the Claude client is created the
# first time a transmission needs parsing, and a replay served from the cache needs no SDK and no key (spec addendum A.4).
PARSERS: dict[str, Callable[[str], Parser]] = {"rule": lambda model: parse_rules.parse, "llm": parse_llm.make_parser}
PARSER_MODELS: dict[str, list[str]] = {"rule": ["rules"], "llm": list(parse_llm.MODELS)}   # the first is the default
PARSER_VERSIONS: dict[str, str] = {"rule": parse_rules.VERSION, "llm": parse_llm.VERSION}   # bumped by hand, cache key
# parser -> (can a cold parse run here, and if not why); served by the capabilities route
PARSER_AVAILABILITY: dict[str, Callable[[], tuple[bool, str | None]]] = {"rule": lambda: (True, None),
                                                                          "llm": parse_llm.availability}
# the source atcdb/inject.py stores synthetic-conflict recordings under; they replay like any other recording
SYNTHETIC_SOURCE = "synthetic-conflicts"
# parser -> instructions it recognised but could not place on a runway, for one transmission (spec addendum A.3.5)
DROP_COUNTERS: dict[str, Callable[[Transmission, Context], int]] = {"rule": parse_rules.count_unresolved}


@dataclass(frozen=True)
class Step:
    tx: Transmission
    events: tuple[Event, ...]
    conflicts: tuple[Conflict, ...]   # raised by this transmission's events
    state: State                      # after this transmission
    error: str | None = None          # parser failure: events are empty and the fold simply continued
    dropped: int = 0                  # instructions lost at this step: unplaceable runway, or ignored by the engine


@dataclass(frozen=True)
class Timeline:
    recording_id: int
    parser: str
    model: str
    model_version: str
    context: str
    transcript_kind: str
    steps: tuple[Step, ...]

    @property
    def dropped(self) -> int:
        return sum(s.dropped for s in self.steps)


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


def build_context(mode: str, tx: Transmission, history: list[Transmission], state: State,
                  single_digit_runways: bool = False) -> Context:
    """The parser's view for one transmission. `none` = text only; `role` = + speaker role; `window` = + the last
    WINDOW transmissions and what the engine is currently tracking."""
    if mode not in CONTEXT_MODES:
        raise ValueError(f"unknown context mode {mode!r}; expected one of {CONTEXT_MODES}")
    if mode == "none":
        return Context(mode="none", single_digit_runways=single_digit_runways)
    if mode == "role":
        return Context(mode="role", role=tx.role, single_digit_runways=single_digit_runways)
    active = tuple(cs for cs, a in state.aircraft.items() if cs and (a.runway or a.holding_short or a.pending))
    return Context(mode="window", role=tx.role, single_digit_runways=single_digit_runways, history=tuple((h.role, h.text) for h in history[-WINDOW:]),
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


def real_recordings(conn: sqlite3.Connection, **kwargs) -> list[dict]:
    """`list_recordings` without the recordings conflict injection wrote (atcdb/inject.py): the real corpus, which the
    evaluation's negatives, the labelling sheet and the injector itself draw from."""
    return [r for r in list_recordings(conn, **kwargs) if r["source"] != SYNTHETIC_SOURCE]


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


def default_transcript_model(conn: sqlite3.Connection, transcript_kind: str, recording_id: int | None = None) -> str | None:
    """The transcript model a replay pins when none is given, so cache keys do not drift between runs: `human` for
    gold (some transmissions also carry an `atco2-xml` gold transcript), otherwise the alphabetically first model.
    With `recording_id`, only that recording's transcripts count, so a recording whose gold transcripts all come from
    another model (the `synthetic` recordings conflict injection writes) still replays. None when there are no
    transcripts of that kind."""
    if recording_id is None:
        models = transcript_models(conn).get(transcript_kind, [])
    else:
        models = [r[0] for r in conn.execute(
            """SELECT DISTINCT t.model FROM transcripts t JOIN transmissions x ON x.id = t.transmission_id
               WHERE x.recording_id = ? AND t.kind = ? ORDER BY t.model""", (recording_id, transcript_kind))]
    if transcript_kind == "gold" and "human" in models:
        return "human"
    return models[0] if models else None


def _resolve_model(parser: str, model: str | None) -> str:
    """The model to use: `model`, or the parser's default when none is given, checked against `PARSER_MODELS[parser]`
    so a rules parse can never be cached under a Claude model id or vice versa."""
    model = model or PARSER_MODELS[parser][0]
    if model not in PARSER_MODELS[parser]:
        raise ValueError(f"unknown model {model!r} for parser {parser!r}; expected one of {PARSER_MODELS[parser]}")
    return model


def cache_version(model_version: str, mode: str) -> str:
    """The `model_version` a cache row is stored under. A `window` parse saw the engine's state, so it is also keyed by
    ENGINE_VERSION (spec addendum A.7.2); `none` and `role` parses never see it and keep the plain version."""
    return f"{model_version}+engine{engine.ENGINE_VERSION}" if mode == "window" else model_version


def _cached_events(conn: sqlite3.Connection, tx: Transmission, parser: str, model: str, model_version: str,
                   mode: str) -> list[Event]:
    rows = conn.execute(
        """SELECT kind, callsign, runway, extra_json FROM events
           WHERE transcript_id = ? AND parser = ? AND model = ? AND model_version = ? AND context = ?
           ORDER BY seq""", (tx.transcript_id, parser, model, cache_version(model_version, mode), mode)).fetchall()
    return [row_to_event(r["kind"], r["callsign"], r["runway"], r["extra_json"], t=tx.start_s, text=tx.text) for r in rows]


def get_events(conn: sqlite3.Connection, tx: Transmission, parser: str, ctx: Context,
               model: str | None = None, model_version: str | None = None) -> list[Event]:
    """Events for one transcript under (parser, model, version, context mode): from the `events` cache, or parsed
    and stored. A parser exception propagates and nothing is stored, so the next call retries. An empty parse is
    stored as one NOOP row, so the transcript is not a cache miss forever. If another request cached the same
    transcript while this one was parsing, the first writer's parse wins: it is what stays cached and what is returned,
    so the cache never mixes rows from two different parses. An `IntegrityError` that leaves no rows behind was not a
    race (a foreign-key failure, say) and is re-raised rather than returned as an empty parse."""
    model = _resolve_model(parser, model)
    model_version = PARSER_VERSIONS[parser] if model_version is None else model_version
    cached = _cached_events(conn, tx, parser, model, model_version, ctx.mode)
    if cached:
        return cached
    events = PARSERS[parser](model)(tx, ctx) or [NoOp(t=tx.start_s, text=tx.text)]
    try:
        conn.executemany(
            """INSERT INTO events (transcript_id, parser, model, model_version, context, seq, kind, callsign, runway, extra_json)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            [(tx.transcript_id, parser, model, cache_version(model_version, ctx.mode), ctx.mode, i, *event_to_row(e))
             for i, e in enumerate(events)])
        conn.commit()
    except sqlite3.IntegrityError:
        conn.rollback()   # lost the race: nothing of ours is kept
        winner = _cached_events(conn, tx, parser, model, model_version, ctx.mode)
        if not winner:
            raise
        return winner
    except Exception:
        conn.rollback()   # a partial insert must never be committed later by someone else's commit
        raise
    return events


def clear_events(conn: sqlite3.Connection, parser: str, model: str | None = None, model_version: str | None = None,
                 context: str | None = None) -> int:
    """Delete cached events for a parser (optionally narrowed to model / version / context mode). Returns rows deleted.
    `window`-mode parses are already invalidated automatically when engine rules change, via ENGINE_VERSION in the
    cache key (see `cache_version`); a manual clear is for discarding parses you no longer want, e.g. a bad prompt
    run. `model_version`, when given, must be the stored key, i.e. `cache_version(version, context)`."""
    sql, params = "DELETE FROM events WHERE parser = ?", [parser]
    for col, val in (("model", model), ("model_version", model_version), ("context", context)):
        if val is not None:
            sql += f" AND {col} = ?"
            params.append(val)
    n = conn.execute(sql, params).rowcount
    conn.commit()
    return n


def uncached_parses(conn: sqlite3.Connection, recording_id: int, parser: str = "rule", transcript_kind: str = "gold",
                    context: str = "window", model: str | None = None, model_version: str | None = None,
                    transcript_model: str | None = None) -> list[tuple[Transmission, Context]]:
    """The transmissions `build_timeline` would have to parse, each with the context it would be parsed in as far as the
    cache knows (cached events are folded; a missing parse contributes nothing to later context). Parses nothing and
    stores nothing: this is what `parse_events.py --dry-run` counts."""
    model = _resolve_model(parser, model)
    model_version = PARSER_VERSIONS[parser] if model_version is None else model_version
    txs = load_recording(conn, recording_id, transcript_kind, transcript_model)
    state, out = State(), []
    for k, tx in enumerate(txs):
        ctx = build_context(context, tx, txs[:k], state)
        cached = _cached_events(conn, tx, parser, model, model_version, context)
        if not cached:
            out.append((tx, ctx))
        for e in cached:
            state, _ = apply(state, e)
    return out


def build_timeline(conn: sqlite3.Connection, recording_id: int, parser: str = "rule", transcript_kind: str = "gold",
                   context: str = "window", model: str | None = None, model_version: str | None = None,
                   transcript_model: str | None = None) -> Timeline:
    """Fold a whole recording: one Step per transmission with its events, the conflicts they raised and the state after."""
    model = _resolve_model(parser, model)
    model_version = PARSER_VERSIONS[parser] if model_version is None else model_version
    txs = load_recording(conn, recording_id, transcript_kind, transcript_model)
    state = State()
    steps: list[Step] = []
    window_broken = False   # a `window` parse failed earlier: later context would be built on incomplete state
    for k, tx in enumerate(txs):
        ctx = build_context(context, tx, txs[:k], state)
        error = None
        if window_broken:
            # do not parse against context missing an earlier transmission's events; a cache hit is still fine
            events = _cached_events(conn, tx, parser, model, model_version, ctx.mode)
            if not events:
                error = "skipped: an earlier transmission failed to parse, so the window context is incomplete"
        else:
            try:
                events = get_events(conn, tx, parser, ctx, model, model_version)
            except Exception as e:   # a flaky parser (API error) must not break the replay; nothing was cached
                events, error = [], f"{type(e).__name__}: {e}"
                window_broken = context == "window"
        conflicts: list[Conflict] = []
        ignored_before = state.ignored
        for e in events:
            state, new = apply(state, e)
            conflicts.extend(new)
        dropped = DROP_COUNTERS.get(parser, lambda tx, ctx: 0)(tx, ctx) + state.ignored - ignored_before
        steps.append(Step(tx=tx, events=tuple(events), conflicts=tuple(conflicts), state=state, error=error, dropped=dropped))
    return Timeline(recording_id, parser, model, model_version, context, transcript_kind, tuple(steps))
