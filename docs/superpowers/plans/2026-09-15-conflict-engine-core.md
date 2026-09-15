# Conflict Engine Core (Phase 1) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A pure event-sourced runway-reservation engine, a rules parser that turns ATC transcripts into typed events, an `events` cache table, and a replay builder that folds a whole recording into per-transmission state snapshots and conflicts — runnable from the CLI against `data/atc.sqlite`.

**Architecture:** `atcdb/engine.py` is pure: event dataclasses, a frozen `State`, and `apply(state, event) -> (state, conflicts)` with the runway compatibility matrix, releases, staleness and readback checking. `atcdb/parse_rules.py` is regex extraction from normalized transcript text into events, gated by speaker role and given an ablatable `Context`. `atcdb/replay.py` reads a recording from SQLite, calls a parser through one `get_events` cache path, and folds the events into a `Timeline` of `Step`s. Scripts are thin argparse wrappers.

**Tech Stack:** Python 3.14, dataclasses (`frozen=True, kw_only=True`), `re`, sqlite3, pytest. No new dependencies in this phase.

**Spec:** `docs/superpowers/specs/2026-09-12-conflict-engine-design.md` (Sections 1, 2, build-order phase 1). This plan covers **phase 1 only**. Phases 2 (FastAPI + UI), 3 (Claude parser + evaluation) and 4 (stretch) get their own plans once this one lands, so each plan produces working, testable software on its own.

## Global Constraints

- Engine module `atcdb/engine.py` does **no I/O** and imports nothing from `atcdb` except `atcdb.readback` (for `extract_items`, `check_readback`).
- Runway designators are normalized at event creation: `"three one"` → `"31"`, `"one six right"` → `"16R"`, `left|right|centre|center` → `L|R|C`.
- Compatibility matrix initial values (spec Section 1) — copy verbatim, do not "improve":

  | new ↓ / active → | LAND | TAKEOFF | LUAW | CROSS |
  |---|---|---|---|---|
  | LAND | ok | alert | alert | alert |
  | TAKEOFF | alert | warning | alert (ok if same callsign) | alert |
  | LUAW | alert | warning | warning | warning |
  | CROSS | alert | alert | warning | ok |

- Staleness timeout initial value: **300 s** of transmission time (`start_s`), module constant `STALE_S`.
- Readback mismatch severity: `warning`, or `alert` when a missing item kind is `runway`.
- `events` table keyed by `(transcript_id, parser, model, model_version, context, seq)`; failed parses are **never** written to it.
- Context modes are exactly `none`, `role`, `window`; `window` = role + last 4 transmissions + active callsigns/runways.
- Rules parser identity: `parser="rule"`, `model="rules"`, `model_version=parse_rules.VERSION` (bump `VERSION` whenever a regex changes, so the cache invalidates).
- Tests use the repo's existing style: plain pytest functions, `init_db(tmp_path / "t.sqlite")`, no mocks framework. Run with `.venv/bin/python -m pytest`.
- Commit after every task; commit messages `feat:`/`test:`/`docs:` prefixed, ending with the attribution lines the session provides.

## File structure

| File | Responsibility |
|---|---|
| `atcdb/schema.py` (modify) | add `events` table + `"events"` in `TABLES` |
| `atcdb/engine.py` (create) | event types, `normalize_runway`, `State`/`Reservation`/`Aircraft`/`Conflict`, `MATRIX`, `STALE_S`, `apply`, `fold` |
| `atcdb/parsing.py` (create) | parser-facing types shared by all parsers: `Transmission`, `Context`, `CONTEXT_MODES`; `event_to_row` / `row_to_event` serialization for the `events` table |
| `atcdb/parse_rules.py` (create) | `VERSION`, `parse(tx, ctx) -> list[Event]`, callsign/runway helpers |
| `atcdb/replay.py` (create) | `PARSERS` registry, `load_recording`, `build_context`, `get_events` (cache), `build_timeline`, `Step`, `Timeline` |
| `scripts/parse_events.py` (create) | precompute events for all tower recordings |
| `scripts/show_replay.py` (create) | print one recording's timeline (phase-1 demo) |
| `tests/test_schema.py` (modify), `tests/test_engine.py`, `tests/test_parsing.py`, `tests/test_parse_rules.py`, `tests/test_replay.py` (create) | tests |
| `README.md` (modify) | engine section + test count |

Domain vocabulary for the engineer: **LAND** = "cleared to land", **TAKEOFF** = "cleared for takeoff", **LUAW** = "line up (and wait)" — aircraft enters the runway and waits, **CROSS** = "cross runway X" — taxiing aircraft crosses an active runway, **HOLD SHORT** = stop before the runway (the safe instruction). A **readback** is the pilot repeating the instruction; ICAO requires runway, frequency, level, heading, squawk to be read back. Transcript text is already normalized: lowercase, digits spelled out ("three one"), no punctuation.

---

### Task 1: `events` table

**Files:**
- Modify: `atcdb/schema.py` (add table to `SCHEMA_SQL`, add `"events"` to `TABLES`)
- Modify: `tests/test_schema.py`

**Interfaces:**
- Produces: table `events(id, transcript_id, parser, model, model_version, context, seq, kind, callsign, runway, extra_json, created_at_utc)` with `UNIQUE (transcript_id, parser, model, model_version, context, seq)`.

- [ ] **Step 1: Write the failing tests**

Replace the first test in `tests/test_schema.py` and add two more:

```python
def test_init_db_creates_all_tables(tmp_path):
    conn = init_db(tmp_path / "t.sqlite")
    assert set(TABLES) <= table_names(conn)
    assert {"sources", "recordings", "transmissions", "transcripts", "annotations", "phraseology_rules",
            "readback_pairs", "events"} == set(TABLES)


def _seed_transcript(conn) -> int:
    conn.execute("INSERT INTO sources (id, name, kind) VALUES (1, 's', 'corpus')")
    conn.execute("INSERT INTO recordings (id, source_id, external_id) VALUES (1, 1, 'r1')")
    conn.execute("INSERT INTO transmissions (id, recording_id, external_id) VALUES (1, 1, 'x1')")
    conn.execute("INSERT INTO transcripts (id, transmission_id, kind, model, raw_text, normalized_text) "
                 "VALUES (1, 1, 'gold', 'human', 'a', 'a')")
    conn.commit()
    return 1


def test_events_rows_are_unique_per_transcript_parser_model_context_seq(tmp_path):
    conn = init_db(tmp_path / "t.sqlite")
    tid = _seed_transcript(conn)
    row = (tid, "rule", "rules", "v1", "window", 0, "LAND", "csa one two three", "31", None)
    conn.execute("INSERT INTO events (transcript_id, parser, model, model_version, context, seq, kind, callsign, runway, extra_json) "
                 "VALUES (?,?,?,?,?,?,?,?,?,?)", row)
    conn.commit()
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("INSERT INTO events (transcript_id, parser, model, model_version, context, seq, kind, callsign, runway, extra_json) "
                     "VALUES (?,?,?,?,?,?,?,?,?,?)", row)


def test_events_reject_unknown_parser_or_context(tmp_path):
    conn = init_db(tmp_path / "t.sqlite")
    tid = _seed_transcript(conn)
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("INSERT INTO events (transcript_id, parser, model, model_version, context, seq, kind) "
                     "VALUES (?, 'magic', 'm', '', 'window', 0, 'NOOP')", (tid,))
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("INSERT INTO events (transcript_id, parser, model, model_version, context, seq, kind) "
                     "VALUES (?, 'rule', 'm', '', 'everything', 0, 'NOOP')", (tid,))
```

Add `import pytest` at the top of the file (it already imports `sqlite3`).

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_schema.py -v`
Expected: `test_init_db_creates_all_tables` FAILS on the set equality; the two new tests FAIL with `sqlite3.OperationalError: no such table: events`.

- [ ] **Step 3: Add the table**

In `atcdb/schema.py`, change `TABLES` to:

```python
TABLES = ["sources", "recordings", "transmissions", "transcripts", "annotations", "phraseology_rules", "readback_pairs", "events"]
```

and append to `SCHEMA_SQL` (before the closing `"""`):

```sql
-- Parsed events per transcript (see atcdb/engine.py, atcdb/replay.py). One row per event; a transcript
-- that parsed to nothing gets a single NOOP row so the cache knows it was parsed. Failed parses are not stored.
CREATE TABLE IF NOT EXISTS events (
    id               INTEGER PRIMARY KEY,
    transcript_id    INTEGER NOT NULL REFERENCES transcripts(id),
    parser           TEXT NOT NULL CHECK (parser IN ('rule', 'llm')),
    model            TEXT NOT NULL,
    model_version    TEXT NOT NULL DEFAULT '',
    context          TEXT NOT NULL CHECK (context IN ('none', 'role', 'window')),
    seq              INTEGER NOT NULL,
    kind             TEXT NOT NULL,
    callsign         TEXT NOT NULL DEFAULT '',
    runway           TEXT,
    extra_json       TEXT,
    created_at_utc   TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    UNIQUE (transcript_id, parser, model, model_version, context, seq)
);
CREATE INDEX IF NOT EXISTS ix_events_transcript ON events (transcript_id, parser, model);
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_schema.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add atcdb/schema.py tests/test_schema.py
git commit -m "feat: events table for cached parser output"
```

---

### Task 2: Engine event types and runway normalization

**Files:**
- Create: `atcdb/engine.py`
- Create: `tests/test_engine.py`

**Interfaces:**
- Produces (used by every later task):
  - `normalize_runway(text: str) -> str | None`
  - base `Event(callsign: str = "", t: float = 0.0, text: str = "")` — all fields keyword-only; `t` is the transmission `start_s`; `text` is the source transmission text (set on instructions so the engine can expect a readback).
  - `RunwayInstruction(Event)` adds `runway: str`; class attribute `kind`. Subclasses: `ClearToLand` (`kind="LAND"`), `ClearTakeoff` (`"TAKEOFF"`), `LineUpAndWait` (`"LUAW"`), `ClearToCross` (`"CROSS"`), `HoldShort` (`"HOLD_SHORT"`).
  - `RunwayVacated(Event)`, `GoAround(Event)`, `Handoff(Event, to: str)`, `ReadbackObserved(Event, text: str)`, `NoOp(Event)`.
  - `RESERVATION_KINDS = ("LAND", "TAKEOFF", "LUAW", "CROSS")`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_engine.py
import pytest

from atcdb.engine import (ClearTakeoff, ClearToCross, ClearToLand, Event, GoAround, Handoff, HoldShort,
                          LineUpAndWait, NoOp, ReadbackObserved, RunwayVacated, normalize_runway)


@pytest.mark.parametrize("text,expected", [
    ("three one", "31"),
    ("one three", "13"),
    ("one six right", "16R"),
    ("two four left", "24L"),
    ("zero six centre", "06C"),
    ("zero six center", "06C"),
    ("31", "31"),
    ("16r", "16R"),
    ("", None),
    ("three", None),
    ("four zero", None),   # no such runway: heading 01-36 only
])
def test_normalize_runway(text, expected):
    assert normalize_runway(text) == expected


def test_events_are_frozen_keyword_only_and_typed():
    e = ClearToLand(callsign="csa one two three", runway="31", t=12.5, text="csa one two three runway three one cleared to land")
    assert (e.callsign, e.runway, e.t, e.kind) == ("csa one two three", "31", 12.5, "LAND")
    with pytest.raises(Exception):
        e.runway = "13"  # frozen
    with pytest.raises(TypeError):
        ClearToLand("csa one two three", "31")  # positional not allowed
    assert ClearToLand(callsign="a", runway="31") != ClearTakeoff(callsign="a", runway="31")  # class matters
    assert ClearToLand(callsign="a", runway="31") == ClearToLand(callsign="a", runway="31")


def test_event_kinds():
    assert ClearTakeoff.kind == "TAKEOFF"
    assert LineUpAndWait.kind == "LUAW"
    assert ClearToCross.kind == "CROSS"
    assert HoldShort.kind == "HOLD_SHORT"
    assert Handoff(callsign="a", to="ground").to == "ground"
    assert ReadbackObserved(callsign="a", text="roger").text == "roger"
    assert isinstance(RunwayVacated(callsign="a"), Event)
    assert isinstance(GoAround(callsign="a"), Event)
    assert NoOp().callsign == ""
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_engine.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'atcdb.engine'`.

- [ ] **Step 3: Write the event types**

```python
# atcdb/engine.py
"""Runway-conflict engine: typed events, a pure state fold, and the conflict rules.

No I/O here. A parser (atcdb/parse_rules.py, later atcdb/parse_llm.py) turns a transmission into
a list of events; `apply` folds one event into a frozen `State` and returns the conflicts it raised.
Because the fold is pure, "state after transmission k" is just a fold over the first k transmissions'
events, and tests are event lists in, conflicts out.

Domain: LAND = cleared to land, TAKEOFF = cleared for takeoff, LUAW = line up and wait (enter the
runway and hold), CROSS = cross the runway while taxiing, HOLD_SHORT = stop before the runway.
"""
import re
from dataclasses import dataclass, field, replace
from typing import ClassVar

from atcdb.readback import check_readback, extract_items

_DIGIT_WORD = {"zero": "0", "one": "1", "two": "2", "three": "3", "four": "4",
               "five": "5", "six": "6", "seven": "7", "eight": "8", "nine": "9"}
_SIDE = {"left": "L", "right": "R", "centre": "C", "center": "C", "l": "L", "r": "R", "c": "C"}
_RUNWAY_RE = re.compile(r"^(\d{2})([lrc])?$")


def normalize_runway(text: str) -> str | None:
    """'three one' -> '31', 'one six right' -> '16R', '16r' -> '16R'. None if it is not a runway designator."""
    words = (text or "").strip().lower().split()
    if not words:
        return None
    if all(w in _DIGIT_WORD for w in words[:2]) and len(words) >= 2:
        digits = _DIGIT_WORD[words[0]] + _DIGIT_WORD[words[1]]
        rest = words[2:]
    else:
        m = _RUNWAY_RE.match(words[0])
        if not m:
            return None
        digits, rest = m.group(1), ([m.group(2)] if m.group(2) else []) + words[1:]
    if not 1 <= int(digits) <= 36:
        return None
    if len(rest) > 1 or (rest and rest[0] not in _SIDE):
        return None
    return digits + (_SIDE[rest[0]] if rest else "")


# --- events -----------------------------------------------------------------------------------

@dataclass(frozen=True, kw_only=True)
class Event:
    callsign: str = ""   # normalized transcript words, e.g. "csa one two three"; "" = unknown
    t: float = 0.0       # transmission start_s; drives the staleness timeout
    text: str = ""       # source transmission text; on an instruction, what the pilot must read back


@dataclass(frozen=True, kw_only=True)
class RunwayInstruction(Event):
    runway: str          # normalized designator, e.g. "31", "16R"
    kind: ClassVar[str] = ""


class ClearToLand(RunwayInstruction):
    kind = "LAND"


class ClearTakeoff(RunwayInstruction):
    kind = "TAKEOFF"


class LineUpAndWait(RunwayInstruction):
    kind = "LUAW"


class ClearToCross(RunwayInstruction):
    kind = "CROSS"


class HoldShort(RunwayInstruction):
    kind = "HOLD_SHORT"


@dataclass(frozen=True, kw_only=True)
class RunwayVacated(Event):
    pass


@dataclass(frozen=True, kw_only=True)
class GoAround(Event):
    pass


@dataclass(frozen=True, kw_only=True)
class Handoff(Event):
    to: str              # ground | departure | tower | approach


@dataclass(frozen=True, kw_only=True)
class ReadbackObserved(Event):
    text: str


@dataclass(frozen=True, kw_only=True)
class NoOp(Event):
    pass


RESERVATION_KINDS = ("LAND", "TAKEOFF", "LUAW", "CROSS")
```

Note: `ReadbackObserved` redeclares `text` without a default so it is required there; `field`/`replace` are imported now for Task 3.

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_engine.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add atcdb/engine.py tests/test_engine.py
git commit -m "feat: engine event types and runway normalization"
```

---

### Task 3: State, reservations and the compatibility matrix

**Files:**
- Modify: `atcdb/engine.py` (append below the event types)
- Modify: `tests/test_engine.py` (append)

**Interfaces:**
- Produces:
  - `Reservation(callsign, kind, seq, t)` frozen dataclass.
  - `Aircraft(callsign, runway=None, kind=None, holding_short=None, pending=None, last_seq=0)` frozen dataclass.
  - `Conflict(type, severity, runway, callsigns, seq, explanation)` frozen dataclass; `type ∈ {RUNWAY, READBACK}`, `severity ∈ {alert, warning}`, `callsigns` is a tuple, the triggering callsign first.
  - `State(seq=0, runways: dict[str, tuple[Reservation, ...]], aircraft: dict[str, Aircraft])` frozen dataclass.
  - `MATRIX: dict[tuple[str, str], str]` keyed `(new_kind, active_kind)` → `"ok" | "warning" | "alert"`.
  - `apply(state: State, event: Event) -> tuple[State, list[Conflict]]` — handles `RunwayInstruction` kinds LAND/TAKEOFF/LUAW/CROSS and `NoOp` in this task; Task 4 adds HOLD_SHORT and releases, Task 5 adds readbacks.
  - `fold(events: Iterable[Event], state: State | None = None) -> tuple[State, list[Conflict]]`.
- Design rule: an aircraft's **own** earlier reservation is always replaced by its new instruction and never conflicts with it. That is how "TAKEOFF after LUAW, same callsign = ok (upgrade)" falls out without a special case; the matrix is only consulted against **other** callsigns' reservations on the same runway.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_engine.py` (extend the import line to include `MATRIX, RESERVATION_KINDS, State, apply, fold`):

```python
def _kinds(state, runway):
    return [(r.callsign, r.kind) for r in state.runways.get(runway, ())]


def test_land_after_land_is_anticipated_separation_not_a_conflict():
    state, conflicts = fold([ClearToLand(callsign="a", runway="31"), ClearToLand(callsign="b", runway="31")])
    assert conflicts == []
    assert _kinds(state, "31") == [("a", "LAND"), ("b", "LAND")]


def test_luaw_then_land_same_runway_is_an_alert():  # Austin 2023 FedEx / Southwest pattern
    _, conflicts = fold([LineUpAndWait(callsign="southwest", runway="18L", t=0.0),
                         ClearToLand(callsign="fedex", runway="18L", t=30.0)])
    assert len(conflicts) == 1
    c = conflicts[0]
    assert (c.type, c.severity, c.runway, c.callsigns, c.seq) == ("RUNWAY", "alert", "18L", ("fedex", "southwest"), 2)
    assert "fedex" in c.explanation and "southwest" in c.explanation and "18L" in c.explanation


def test_cross_against_active_landing_is_an_alert():
    _, conflicts = fold([ClearToLand(callsign="a", runway="13"), ClearToCross(callsign="b", runway="13")])
    assert [(c.severity, c.callsigns) for c in conflicts] == [("alert", ("b", "a"))]


def test_takeoff_after_luaw_same_callsign_is_an_upgrade_not_a_conflict():
    state, conflicts = fold([LineUpAndWait(callsign="a", runway="13"), ClearTakeoff(callsign="a", runway="13")])
    assert conflicts == []
    assert _kinds(state, "13") == [("a", "TAKEOFF")]
    assert (state.aircraft["a"].runway, state.aircraft["a"].kind) == ("13", "TAKEOFF")


def test_takeoff_after_luaw_different_callsign_is_an_alert():
    _, conflicts = fold([LineUpAndWait(callsign="a", runway="13"), ClearTakeoff(callsign="b", runway="13")])
    assert [c.severity for c in conflicts] == ["alert"]


def test_takeoff_after_takeoff_and_luaw_after_luaw_are_warnings():
    _, c1 = fold([ClearTakeoff(callsign="a", runway="13"), ClearTakeoff(callsign="b", runway="13")])
    _, c2 = fold([LineUpAndWait(callsign="a", runway="13"), LineUpAndWait(callsign="b", runway="13")])
    assert [c.severity for c in c1] == ["warning"] and [c.severity for c in c2] == ["warning"]


def test_cross_after_cross_is_ok():
    _, conflicts = fold([ClearToCross(callsign="a", runway="13"), ClearToCross(callsign="b", runway="13")])
    assert conflicts == []


def test_different_runways_never_conflict():
    _, conflicts = fold([ClearToLand(callsign="a", runway="31"), ClearToCross(callsign="b", runway="13")])
    assert conflicts == []


def test_one_new_reservation_can_conflict_with_several_active_ones():
    _, conflicts = fold([ClearToLand(callsign="a", runway="31"), LineUpAndWait(callsign="b", runway="31"),
                         ClearToCross(callsign="c", runway="31")])
    # b vs a (LUAW after LAND = alert), then c vs a (alert) and c vs b (CROSS after LUAW = warning)
    assert [(c.callsigns, c.severity) for c in conflicts] == [(("b", "a"), "alert"), (("c", "a"), "alert"), (("c", "b"), "warning")]


def test_matrix_is_complete_and_matches_the_spec():
    assert set(MATRIX) == {(n, a) for n in RESERVATION_KINDS for a in RESERVATION_KINDS}
    assert set(MATRIX.values()) <= {"ok", "warning", "alert"}
    assert MATRIX[("LAND", "LAND")] == "ok" and MATRIX[("LAND", "LUAW")] == "alert"
    assert MATRIX[("CROSS", "CROSS")] == "ok" and MATRIX[("TAKEOFF", "TAKEOFF")] == "warning"


def test_a_new_instruction_moves_the_aircraft_off_its_old_runway():
    state, _ = fold([ClearToLand(callsign="a", runway="31"), ClearToCross(callsign="a", runway="13")])
    assert "31" not in state.runways and _kinds(state, "13") == [("a", "CROSS")]


def test_apply_does_not_mutate_its_input_and_seq_counts_every_event():
    s0 = State()
    s1, _ = apply(s0, ClearToLand(callsign="a", runway="31"))
    assert s0.seq == 0 and s0.runways == {} and s0.aircraft == {}
    assert s1.seq == 1 and s1.aircraft["a"].last_seq == 1
    s2, _ = fold([NoOp(), NoOp()], s1)
    assert s2.seq == 3
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_engine.py -v`
Expected: the new tests FAIL with `ImportError: cannot import name 'MATRIX'`.

- [ ] **Step 3: Write state, matrix and apply**

Append to `atcdb/engine.py`:

```python
# --- state ------------------------------------------------------------------------------------

@dataclass(frozen=True)
class Reservation:
    callsign: str
    kind: str            # LAND | TAKEOFF | LUAW | CROSS
    seq: int             # event seq that created it
    t: float             # transmission time it was created at


@dataclass(frozen=True)
class Aircraft:
    callsign: str
    runway: str | None = None          # runway of its active reservation, if any
    kind: str | None = None            # kind of that reservation
    holding_short: str | None = None   # runway it was told to hold short of
    pending: str | None = None         # instruction text awaiting the pilot's readback
    last_seq: int = 0


@dataclass(frozen=True)
class Conflict:
    type: str                    # RUNWAY | READBACK
    severity: str                # alert | warning
    runway: str | None
    callsigns: tuple[str, ...]   # triggering callsign first
    seq: int                     # seq of the triggering event
    explanation: str             # what the app displays


@dataclass(frozen=True)
class State:
    seq: int = 0
    runways: dict[str, tuple[Reservation, ...]] = field(default_factory=dict)
    aircraft: dict[str, Aircraft] = field(default_factory=dict)


# --- rules ------------------------------------------------------------------------------------

STALE_S = 300.0   # a reservation this old (transmission time) is dropped silently: we missed the release call

# (new_kind, active_kind) -> verdict, checked against OTHER aircraft's reservations on the same runway.
# LAND after LAND is legal (anticipated separation). LUAW then LAND is the Austin 2023 pattern.
MATRIX: dict[tuple[str, str], str] = {
    ("LAND", "LAND"): "ok",        ("LAND", "TAKEOFF"): "alert",      ("LAND", "LUAW"): "alert",      ("LAND", "CROSS"): "alert",
    ("TAKEOFF", "LAND"): "alert",  ("TAKEOFF", "TAKEOFF"): "warning", ("TAKEOFF", "LUAW"): "alert",   ("TAKEOFF", "CROSS"): "alert",
    ("LUAW", "LAND"): "alert",     ("LUAW", "TAKEOFF"): "warning",    ("LUAW", "LUAW"): "warning",    ("LUAW", "CROSS"): "warning",
    ("CROSS", "LAND"): "alert",    ("CROSS", "TAKEOFF"): "alert",     ("CROSS", "LUAW"): "warning",   ("CROSS", "CROSS"): "ok",
}

_PHRASE = {"LAND": "a landing clearance", "TAKEOFF": "a takeoff clearance",
           "LUAW": "a line-up-and-wait instruction", "CROSS": "a crossing clearance"}


def _name(callsign: str) -> str:
    return callsign or "an unidentified aircraft"


def _release(runways: dict[str, tuple[Reservation, ...]], callsign: str,
             kinds: tuple[str, ...] = RESERVATION_KINDS) -> tuple[dict[str, tuple[Reservation, ...]], bool]:
    """Drop `callsign`'s reservations of the given kinds. Returns (new runways, whether anything was dropped)."""
    out, dropped = {}, False
    for rwy, res in runways.items():
        keep = tuple(r for r in res if not (r.callsign == callsign and r.kind in kinds))
        dropped = dropped or len(keep) != len(res)
        if keep:
            out[rwy] = keep
    return out, dropped


def _expire(state: State, now: float) -> tuple[dict[str, tuple[Reservation, ...]], dict[str, Aircraft]]:
    """Copy of the runway map and aircraft map with reservations older than STALE_S removed."""
    runways, aircraft = {}, dict(state.aircraft)
    for rwy, res in state.runways.items():
        keep = tuple(r for r in res if now - r.t <= STALE_S)
        for r in res:
            if r not in keep and r.callsign in aircraft:
                aircraft[r.callsign] = replace(aircraft[r.callsign], runway=None, kind=None)
        if keep:
            runways[rwy] = keep
    return runways, aircraft


def apply(state: State, event: Event) -> tuple[State, list[Conflict]]:
    """Fold one event into the state. Pure: returns a new State and the conflicts this event raised."""
    seq = state.seq + 1
    runways, aircraft = _expire(state, event.t)
    conflicts: list[Conflict] = []
    cs = event.callsign
    ac = aircraft.get(cs, Aircraft(callsign=cs)) if cs else None

    if isinstance(event, RunwayInstruction) and event.kind in RESERVATION_KINDS:
        if cs:
            runways, _ = _release(runways, cs)   # one aircraft is in one place: its old reservation is superseded
        for r in runways.get(event.runway, ()):
            verdict = MATRIX[(event.kind, r.kind)]
            if verdict != "ok":
                conflicts.append(Conflict(
                    "RUNWAY", verdict, event.runway, (cs, r.callsign), seq,
                    f"{_name(cs)} given {_PHRASE[event.kind]} on runway {event.runway} while "
                    f"{_name(r.callsign)} still holds {_PHRASE[r.kind]} on runway {event.runway}"))
        runways[event.runway] = runways.get(event.runway, ()) + (Reservation(cs, event.kind, seq, event.t),)
        if cs:
            aircraft[cs] = replace(ac, runway=event.runway, kind=event.kind, holding_short=None,
                                   pending=event.text or ac.pending, last_seq=seq)
    elif isinstance(event, NoOp):
        pass
    return State(seq=seq, runways=runways, aircraft=aircraft), conflicts


def fold(events, state: State | None = None) -> tuple[State, list[Conflict]]:
    """Apply events in order. Returns the final state and every conflict raised along the way."""
    state = state or State()
    conflicts: list[Conflict] = []
    for e in events:
        state, new = apply(state, e)
        conflicts.extend(new)
    return state, conflicts
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_engine.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add atcdb/engine.py tests/test_engine.py
git commit -m "feat: engine state fold with runway compatibility matrix"
```

---

### Task 4: Releases, staleness and hold-short

**Files:**
- Modify: `atcdb/engine.py` (extend `apply`)
- Modify: `tests/test_engine.py` (append)

**Interfaces:**
- Consumes: everything from Task 3.
- Produces: `apply` now handles `HoldShort`, `RunwayVacated`, `GoAround`, `Handoff`. Release rules: `RunwayVacated` drops all of the callsign's reservations; `GoAround` drops LAND only; `Handoff(to="ground")` drops LAND and CROSS; `Handoff(to="departure")` drops TAKEOFF; other handoffs drop nothing. Every handoff with text sets `pending` (the frequency must be read back).

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_engine.py` (add `STALE_S` to the import):

```python
def test_runway_vacated_releases_so_a_crossing_is_fine():
    state, conflicts = fold([ClearToLand(callsign="a", runway="31"), RunwayVacated(callsign="a"),
                             ClearToCross(callsign="b", runway="31")])
    assert conflicts == []
    assert _kinds(state, "31") == [("b", "CROSS")]
    assert (state.aircraft["a"].runway, state.aircraft["a"].kind) == (None, None)


def test_handoff_to_ground_releases_landing_and_crossing_but_tower_does_not():
    _, c = fold([ClearToLand(callsign="a", runway="31"), Handoff(callsign="a", to="ground"), ClearToCross(callsign="b", runway="31")])
    assert c == []
    _, c = fold([ClearToCross(callsign="a", runway="31"), Handoff(callsign="a", to="ground"), ClearToLand(callsign="b", runway="31")])
    assert c == []
    _, c = fold([ClearToLand(callsign="a", runway="31"), Handoff(callsign="a", to="tower"), ClearToCross(callsign="b", runway="31")])
    assert [x.severity for x in c] == ["alert"]


def test_handoff_to_departure_releases_takeoff_only():
    _, c = fold([ClearTakeoff(callsign="a", runway="31"), Handoff(callsign="a", to="departure"), ClearToLand(callsign="b", runway="31")])
    assert c == []
    _, c = fold([ClearToLand(callsign="a", runway="31"), Handoff(callsign="a", to="departure"), ClearToCross(callsign="b", runway="31")])
    assert [x.severity for x in c] == ["alert"]


def test_go_around_cancels_landing_only():
    state, c = fold([ClearToLand(callsign="a", runway="31"), GoAround(callsign="a"), ClearToCross(callsign="b", runway="31")])
    assert c == [] and _kinds(state, "31") == [("b", "CROSS")]
    state, _ = fold([ClearTakeoff(callsign="a", runway="31"), GoAround(callsign="a")])
    assert _kinds(state, "31") == [("a", "TAKEOFF")]


def test_stale_reservation_is_dropped_silently():
    _, c = fold([ClearToLand(callsign="a", runway="31", t=0.0), ClearToCross(callsign="b", runway="31", t=STALE_S + 1)])
    assert c == []
    state, c = fold([ClearToLand(callsign="a", runway="31", t=0.0), ClearToCross(callsign="b", runway="31", t=100.0)])
    assert [x.severity for x in c] == ["alert"]
    state, _ = fold([NoOp(t=STALE_S + 101)], state)   # both the t=0 LAND and the t=100 CROSS are now stale
    assert state.runways == {} and state.aircraft["a"].runway is None


def test_hold_short_never_conflicts_and_is_recorded_until_the_next_instruction():
    state, c = fold([ClearToLand(callsign="a", runway="13"), HoldShort(callsign="b", runway="13")])
    assert c == []
    assert state.aircraft["b"].holding_short == "13" and _kinds(state, "13") == [("a", "LAND")]
    state, c = fold([ClearToCross(callsign="b", runway="13")], state)
    assert state.aircraft["b"].holding_short is None and state.aircraft["b"].kind == "CROSS"


def test_release_events_for_unknown_callsigns_do_not_crash():
    state, c = fold([RunwayVacated(callsign="zzz"), GoAround(callsign=""), Handoff(callsign="", to="ground")])
    assert c == [] and state.seq == 3
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_engine.py -v`
Expected: the vacated / handoff / go-around / hold-short tests FAIL (the events fall through `apply` and the reservation is still there); the stale test FAILS on the NoOp expiry assertion only if `_expire` is wrong — it should already pass.

- [ ] **Step 3: Extend `apply`**

In `atcdb/engine.py`, replace the `elif isinstance(event, NoOp): pass` branch with:

```python
    elif isinstance(event, HoldShort):
        if cs:
            aircraft[cs] = replace(ac, holding_short=event.runway, pending=event.text or ac.pending, last_seq=seq)
    elif isinstance(event, RunwayVacated):
        runways, dropped = _release(runways, cs)
        if cs:
            aircraft[cs] = replace(ac, runway=None, kind=None, last_seq=seq)
    elif isinstance(event, GoAround):
        runways, dropped = _release(runways, cs, ("LAND",))
        if cs:
            aircraft[cs] = replace(ac, runway=None if dropped else ac.runway, kind=None if dropped else ac.kind, last_seq=seq)
    elif isinstance(event, Handoff):
        kinds = {"ground": ("LAND", "CROSS"), "departure": ("TAKEOFF",)}.get(event.to, ())
        runways, dropped = _release(runways, cs, kinds) if kinds else (runways, False)
        if cs:
            aircraft[cs] = replace(ac, runway=None if dropped else ac.runway, kind=None if dropped else ac.kind,
                                   pending=event.text or ac.pending, last_seq=seq)
    elif isinstance(event, NoOp):
        pass
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_engine.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add atcdb/engine.py tests/test_engine.py
git commit -m "feat: engine releases, staleness timeout and hold-short"
```

---

### Task 5: Readback conflicts

**Files:**
- Modify: `atcdb/engine.py` (extend `apply`)
- Modify: `tests/test_engine.py` (append)

**Interfaces:**
- Consumes: `extract_items(text) -> list[(kind, value)]` and `check_readback(items, readback) -> list[(kind, value, "ok"|"missing")]` from `atcdb/readback.py` (already exist; `kind ∈ {frequency, level, altitude, heading, squawk, runway}`).
- Produces: `apply` handles `ReadbackObserved`: if the aircraft has a `pending` instruction, check it; any missing item → `Conflict(type="READBACK")`, severity `alert` if a missing item's kind is `runway` else `warning`; `pending` is cleared either way. No pending → nothing happens.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_engine.py`:

```python
CSA = "csa one two three"
LAND_31 = ClearToLand(callsign=CSA, runway="31", text="csa one two three runway three one cleared to land")


def test_correct_readback_clears_pending_without_conflict():
    state, c = fold([LAND_31, ReadbackObserved(callsign=CSA, text="cleared to land runway three one csa one two three")])
    assert c == [] and state.aircraft[CSA].pending is None


def test_wrong_runway_in_readback_is_an_alert():
    state, c = fold([LAND_31, ReadbackObserved(callsign=CSA, text="cleared to land runway one three csa one two three")])
    assert len(c) == 1
    assert (c[0].type, c[0].severity, c[0].runway, c[0].callsigns, c[0].seq) == ("READBACK", "alert", "31", (CSA,), 2)
    assert "three one" in c[0].explanation and "one three" in c[0].explanation
    assert state.aircraft[CSA].pending is None


def test_missing_frequency_after_handoff_is_a_warning():
    lh = "lufthansa five mike echo"
    events = [Handoff(callsign=lh, to="ground", text="lufthansa five mike echo contact ground one two one nine bye"),
              ReadbackObserved(callsign=lh, text="one two one five bye bye lufthansa five mike echo")]
    _, c = fold(events)
    assert [(x.type, x.severity, x.runway) for x in c] == [("READBACK", "warning", None)]


def test_readback_with_nothing_pending_is_ignored():
    state, c = fold([ReadbackObserved(callsign=CSA, text="roger")])
    assert c == [] and state.aircraft == {}
    state, c = fold([LAND_31, ReadbackObserved(callsign=CSA, text="cleared to land runway three one csa one two three"),
                     ReadbackObserved(callsign=CSA, text="runway vacated csa one two three")])
    assert c == []


def test_instruction_without_text_expects_no_readback():
    _, c = fold([ClearToLand(callsign=CSA, runway="31"), ReadbackObserved(callsign=CSA, text="roger")])
    assert c == []


def test_instruction_with_no_readback_items_expects_nothing():
    _, c = fold([GoAround(callsign=CSA, text="csa one two three go around"), ReadbackObserved(callsign=CSA, text="going around")])
    assert c == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_engine.py -v`
Expected: `test_wrong_runway_in_readback_is_an_alert` and `test_missing_frequency_after_handoff_is_a_warning` FAIL (no conflicts raised); the others may already pass.

- [ ] **Step 3: Add the readback branch**

In `atcdb/engine.py`, insert before `elif isinstance(event, NoOp):`:

```python
    elif isinstance(event, ReadbackObserved):
        if ac is not None and ac.pending:
            missing = [(k, v) for k, v, verdict in check_readback(extract_items(ac.pending), event.text) if verdict == "missing"]
            if missing:
                severity = "alert" if any(k == "runway" for k, _ in missing) else "warning"
                what = ", ".join(f"{k} {v}" for k, v in missing)
                conflicts.append(Conflict(
                    "READBACK", severity, ac.runway, (cs,), seq,
                    f"{cs} did not read back {what} (instruction: '{ac.pending}'; readback: '{event.text}')"))
            aircraft[cs] = replace(ac, pending=None, last_seq=seq)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_engine.py -v`
Expected: all PASS. Then run the whole suite: `.venv/bin/python -m pytest -q` — expected all green (47 old + the new ones).

- [ ] **Step 5: Commit**

```bash
git add atcdb/engine.py tests/test_engine.py
git commit -m "feat: readback mismatch conflicts routed through the engine"
```

---

### Task 6: Shared parser types and events-table serialization

**Files:**
- Create: `atcdb/parsing.py`
- Create: `tests/test_parsing.py`

**Interfaces:**
- Consumes: event classes from `atcdb/engine.py` (Task 2).
- Produces (used by `parse_rules.py`, `replay.py`, and later `parse_llm.py`):
  - `CONTEXT_MODES = ("none", "role", "window")`, `WINDOW = 4`.
  - `Transmission(id: int, transcript_id: int, text: str, role: str, start_s: float)` frozen dataclass.
  - `Context(mode="window", role="unknown", history=(), active_callsigns=(), active_runways=())` frozen dataclass; `history` is a tuple of `(role, text)` pairs, oldest first.
  - `Parser = Callable[[Transmission, Context], list[Event]]` type alias.
  - `event_to_row(e: Event) -> tuple[str, str, str | None, str | None]` = `(kind, callsign, runway, extra_json)`.
  - `row_to_event(kind, callsign, runway, extra_json, t=0.0, text="") -> Event`; kinds: `LAND TAKEOFF LUAW CROSS HOLD_SHORT VACATED GO_AROUND HANDOFF READBACK NOOP`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_parsing.py
import pytest

from atcdb.engine import (ClearTakeoff, ClearToCross, ClearToLand, GoAround, Handoff, HoldShort, LineUpAndWait, NoOp,
                          ReadbackObserved, RunwayVacated)
from atcdb.parsing import CONTEXT_MODES, Context, Transmission, event_to_row, row_to_event

TEXT = "csa one two three runway three one cleared to land"


@pytest.mark.parametrize("event,row", [
    (ClearToLand(callsign="csa one two three", runway="31"), ("LAND", "csa one two three", "31", None)),
    (ClearTakeoff(callsign="a", runway="13"), ("TAKEOFF", "a", "13", None)),
    (LineUpAndWait(callsign="a", runway="13"), ("LUAW", "a", "13", None)),
    (ClearToCross(callsign="a", runway="13"), ("CROSS", "a", "13", None)),
    (HoldShort(callsign="a", runway="24"), ("HOLD_SHORT", "a", "24", None)),
    (RunwayVacated(callsign="a"), ("VACATED", "a", None, None)),
    (GoAround(callsign="a"), ("GO_AROUND", "a", None, None)),
    (Handoff(callsign="a", to="ground"), ("HANDOFF", "a", None, '{"to": "ground"}')),
    (ReadbackObserved(callsign="a", text="roger"), ("READBACK", "a", None, None)),
    (NoOp(), ("NOOP", "", None, None)),
])
def test_event_to_row(event, row):
    assert event_to_row(event) == row


def test_row_to_event_reattaches_time_and_text():
    e = row_to_event("LAND", "csa one two three", "31", None, t=12.5, text=TEXT)
    assert e == ClearToLand(callsign="csa one two three", runway="31", t=12.5, text=TEXT)
    h = row_to_event("HANDOFF", "a", None, '{"to": "ground"}', t=1.0, text="a contact ground")
    assert h == Handoff(callsign="a", to="ground", t=1.0, text="a contact ground")
    r = row_to_event("READBACK", "a", None, None, t=2.0, text="roger a")
    assert r == ReadbackObserved(callsign="a", text="roger a", t=2.0)
    assert row_to_event("NOOP", "", None, None, t=3.0, text="hi") == NoOp(t=3.0, text="hi")


def test_round_trip_every_kind():
    events = [ClearToLand(callsign="a", runway="31", t=1.0, text="x"), HoldShort(callsign="b", runway="13", t=1.0, text="x"),
              RunwayVacated(callsign="a", t=1.0, text="x"), GoAround(callsign="a", t=1.0, text="x"),
              Handoff(callsign="a", to="departure", t=1.0, text="x"), ReadbackObserved(callsign="a", text="x", t=1.0), NoOp(t=1.0, text="x")]
    for e in events:
        assert row_to_event(*event_to_row(e), t=1.0, text="x") == e


def test_unknown_kind_raises():
    with pytest.raises(KeyError):
        row_to_event("TELEPORT", "a", None, None)


def test_context_defaults_and_modes():
    assert CONTEXT_MODES == ("none", "role", "window")
    c = Context()
    assert (c.mode, c.role, c.history, c.active_callsigns, c.active_runways) == ("window", "unknown", (), (), ())
    tx = Transmission(id=1, transcript_id=2, text="hello", role="pilot", start_s=3.5)
    assert (tx.id, tx.transcript_id, tx.role, tx.start_s) == (1, 2, "pilot", 3.5)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_parsing.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'atcdb.parsing'`.

- [ ] **Step 3: Write the module**

```python
# atcdb/parsing.py
"""Types shared by every parser (rules now, Claude later) and the `events` table serialization.

A parser is `parse(tx: Transmission, ctx: Context) -> list[Event]`. `Context` is the ablatable
knob from the spec: mode `none` gives the parser nothing but the text, `role` adds the speaker role
from the DB, `window` adds the last WINDOW transmissions and what the engine currently tracks.
"""
import json
from dataclasses import dataclass
from typing import Callable

from atcdb.engine import (ClearTakeoff, ClearToCross, ClearToLand, Event, GoAround, Handoff, HoldShort, LineUpAndWait,
                          NoOp, ReadbackObserved, RunwayInstruction, RunwayVacated)

CONTEXT_MODES = ("none", "role", "window")
WINDOW = 4   # how many previous transmissions `window` mode carries


@dataclass(frozen=True)
class Transmission:
    id: int              # transmissions.id
    transcript_id: int   # transcripts.id that `text` came from (gold or asr)
    text: str            # normalized transcript text
    role: str            # pilot | controller | mixed | unknown (from the DB)
    start_s: float


@dataclass(frozen=True)
class Context:
    mode: str = "window"                            # none | role | window
    role: str = "unknown"                           # speaker role; 'unknown' in mode none
    history: tuple[tuple[str, str], ...] = ()       # (role, text) of the previous WINDOW transmissions, oldest first
    active_callsigns: tuple[str, ...] = ()          # aircraft the engine currently tracks (window mode only)
    active_runways: tuple[str, ...] = ()            # runways with an active reservation (window mode only)


Parser = Callable[[Transmission, Context], list[Event]]

KINDS: dict[type, str] = {ClearToLand: "LAND", ClearTakeoff: "TAKEOFF", LineUpAndWait: "LUAW", ClearToCross: "CROSS",
                          HoldShort: "HOLD_SHORT", RunwayVacated: "VACATED", GoAround: "GO_AROUND", Handoff: "HANDOFF",
                          ReadbackObserved: "READBACK", NoOp: "NOOP"}
_BY_KIND = {v: k for k, v in KINDS.items()}


def event_to_row(e: Event) -> tuple[str, str, str | None, str | None]:
    """(kind, callsign, runway, extra_json). `t` and `text` are not stored: they are re-attached from the transcript."""
    runway = e.runway if isinstance(e, RunwayInstruction) else None
    extra = json.dumps({"to": e.to}) if isinstance(e, Handoff) else None
    return KINDS[type(e)], e.callsign, runway, extra


def row_to_event(kind: str, callsign: str, runway: str | None, extra_json: str | None, t: float = 0.0, text: str = "") -> Event:
    cls = _BY_KIND[kind]   # KeyError on an unknown kind is deliberate
    extra = json.loads(extra_json) if extra_json else {}
    if issubclass(cls, RunwayInstruction):
        return cls(callsign=callsign, runway=runway, t=t, text=text)
    if cls is Handoff:
        return Handoff(callsign=callsign, to=extra["to"], t=t, text=text)
    if cls is ReadbackObserved:
        return ReadbackObserved(callsign=callsign, text=text, t=t)
    return cls(callsign=callsign, t=t, text=text)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_parsing.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add atcdb/parsing.py tests/test_parsing.py
git commit -m "feat: shared parser types and events-table serialization"
```

---

### Task 7: Rules parser — controller instructions

**Files:**
- Create: `atcdb/parse_rules.py`
- Create: `tests/test_parse_rules.py`

**Interfaces:**
- Consumes: `Transmission`, `Context` (Task 6); event classes and `normalize_runway` (Task 2); `D` and `ITEM_PATTERNS` from `atcdb/readback.py` (exist).
- Produces: `VERSION = "v1"`, `parse(tx, ctx) -> list[Event]`. In this task only controller/mixed/unknown roles produce events; pilot role returns `[NoOp]` (Task 8 fills that in). Helpers `controller_callsign(blanked, first_start, last_end) -> str`, `take_prefix(words) -> list[str]`, `blank_values(text) -> str` (same length as `text`, readback item values and wind clauses replaced by spaces), `is_id(word) -> bool`.
- Heuristics (all are documented blind spots):
  - A controller callsign is the words **before the first instruction**, after dropping leading filler: up to 2 unknown words (airline name) followed by digit / NATO-letter tokens; stops at the first other word. If that has no digit/NATO token, try the words **after the last instruction** the same way. Otherwise `""` (unknown).
  - LAND / TAKEOFF / LUAW take the **nearest** `runway D D [side]` mention; with none, in `window` mode, the only active runway; otherwise the instruction is dropped.
  - CROSS and HOLD SHORT take the runway **immediately following** the phrase (`cross runway 13`, `hold short of runway 24`).
  - Events are emitted in text order; a transmission with no recognised instruction yields a single `NoOp`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_parse_rules.py
from atcdb.engine import (ClearTakeoff, ClearToCross, ClearToLand, GoAround, Handoff, HoldShort, LineUpAndWait, NoOp,
                          RunwayInstruction)
from atcdb.parse_rules import VERSION, blank_values, parse, take_prefix
from atcdb.parsing import Context, Transmission

CTL = Context(mode="role", role="controller")
PLT = Context(mode="role", role="pilot")


def _tx(text, role="controller", t=0.0):
    return Transmission(id=1, transcript_id=1, text=text, role=role, start_s=t)


def _kinds(events):
    return [(type(e).__name__, e.callsign, getattr(e, "runway", getattr(e, "to", None))) for e in events]


def test_version_is_a_string():
    assert isinstance(VERSION, str) and VERSION


def test_takeoff_clearance_with_runway_before_the_phrase():
    text = "csa seven eight eight runway one three cleared for takeoff wind zero three zero degrees"
    assert parse(_tx(text, t=5.0), CTL) == [ClearTakeoff(callsign="csa seven eight eight", runway="13", t=5.0, text=text)]


def test_landing_clearance_variants():
    ev = parse(_tx("shamrock six four four runway three one clear to land wind zero six zero degrees and five knots"), CTL)
    assert _kinds(ev) == [("ClearToLand", "shamrock six four four", "31")]
    ev = parse(_tx("hotel lima hotel wind zero one zero degrees one zero knots runway one zero cleared to land"), CTL)
    assert _kinds(ev) == [("ClearToLand", "hotel lima hotel", "10")]


def test_line_up_then_takeoff_in_one_transmission_yields_two_events():
    ev = parse(_tx("sky travel one one nine two line up runway three one cleared for takeoff wind is calm"), CTL)
    assert _kinds(ev) == [("LineUpAndWait", "sky travel one one nine two", "31"), ("ClearTakeoff", "sky travel one one nine two", "31")]


def test_line_up_and_wait_variants():
    assert _kinds(parse(_tx("swiss one eight line up and wait runway one zero"), CTL)) == [("LineUpAndWait", "swiss one eight", "10")]
    assert _kinds(parse(_tx("csa four zero six line up runway one three and wait"), CTL)) == [("LineUpAndWait", "csa four zero six", "13")]


def test_cross_and_hold_short_take_the_runway_that_follows():
    text = "air france one nine eight romeo now expedite cross runway one three continue via delta to hold short of runway two four"
    assert _kinds(parse(_tx(text), CTL)) == [("ClearToCross", "air france one nine eight romeo", "13"),
                                             ("HoldShort", "air france one nine eight romeo", "24")]


def test_hold_short_ignores_a_taxi_via_runway_mention():
    ev = parse(_tx("csa four delta romeo taxi via runway two four and hold short of runway one three"), CTL)
    assert _kinds(ev) == [("HoldShort", "csa four delta romeo", "13")]


def test_handoffs():
    assert _kinds(parse(_tx("csa eight two nine vacate to the left contact ruzyne ground one two one point nine"), CTL)) == \
        [("Handoff", "csa eight two nine", "ground")]
    assert _kinds(parse(_tx("lufthansa five mike echo contact ground one two one nine bye"), CTL)) == \
        [("Handoff", "lufthansa five mike echo", "ground")]
    assert _kinds(parse(_tx("contact departure one two zero decimal five"), CTL)) == [("Handoff", "", "departure")]
    assert _kinds(parse(_tx("sunturk niner four seven taxiway juliett cross runway two eight contact apron one two one decimal seven five five bye"), CTL)) == \
        [("ClearToCross", "sunturk niner four seven", "28"), ("Handoff", "sunturk niner four seven", "ground")]


def test_go_around_instruction():
    assert _kinds(parse(_tx("csa one two three go around"), CTL)) == [("GoAround", "csa one two three", None)]


def test_no_instruction_yields_a_single_noop_carrying_the_text():
    text = "csa eight three eight whiskey reduce speed one sixty"
    assert parse(_tx(text, t=2.0), CTL) == [NoOp(t=2.0, text=text)]


def test_callsign_after_the_instruction_and_unknown_callsign():
    assert _kinds(parse(_tx("ok line up runway three one csa seven nine"), CTL)) == [("LineUpAndWait", "csa seven nine", "31")]
    ev = parse(_tx("right turn and runway three one cleared for takeoff wind one six zero degrees four knots"), CTL)
    assert _kinds(ev) == [("ClearTakeoff", "", "31")]


def test_missing_runway_uses_the_only_active_runway_in_window_mode_only():
    text = "hotel mike november line up in sequence"
    assert _kinds(parse(_tx(text), Context(mode="window", role="controller", active_runways=("31",)))) == \
        [("LineUpAndWait", "hotel mike november", "31")]
    assert _kinds(parse(_tx(text), Context(mode="window", role="controller", active_runways=("31", "13")))) == [("NoOp", "", None)]
    assert _kinds(parse(_tx(text), CTL)) == [("NoOp", "", None)]


def test_mixed_and_unknown_roles_are_parsed_like_controller():
    text = "csa seven three two zero line up runway three one cleared for takeoff wind calm line up three one csa"
    assert [type(e) for e in parse(_tx(text, role="mixed"), Context(mode="role", role="mixed"))] == [LineUpAndWait, ClearTakeoff]
    assert [type(e) for e in parse(_tx(text, role="unknown"), Context(mode="role", role="unknown"))] == [LineUpAndWait, ClearTakeoff]


def test_pilot_role_never_produces_instructions():
    ev = parse(_tx("cleared for takeoff runway three one csa two mike zulu", role="pilot"), PLT)
    assert not any(isinstance(e, RunwayInstruction) for e in ev)


def test_take_prefix_and_blank_values():
    assert take_prefix("csa four delta romeo taxi via".split()) == ["csa", "four", "delta", "romeo"]
    assert take_prefix("sky travel one one nine two".split()) == ["sky", "travel", "one", "one", "nine", "two"]
    assert take_prefix("hotel bravo sierra delta foxtrot tower hello".split()) == ["hotel", "bravo", "sierra", "delta", "foxtrot"]
    assert take_prefix("right turn and".split()) == []
    text = "csa seven eight eight runway one three cleared for takeoff wind zero three zero degrees"
    blanked = blank_values(text)
    assert len(blanked) == len(text)
    assert blanked.split() == ["csa", "seven", "eight", "eight", "cleared", "for", "takeoff"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_parse_rules.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'atcdb.parse_rules'`.

- [ ] **Step 3: Write the parser**

```python
# atcdb/parse_rules.py
"""Rules parser: regexes over normalized transcript text -> engine events. The non-LLM baseline.

Known blind spots (report material): conditional clearances ("behind the landing airbus, line up"),
clipped or nonstandard phrasing, callsigns that are not at the start (controller) or end (pilot) of
the transmission, "go around" said *about* another aircraft, instructions to two aircraft in one call.
Bump VERSION whenever a pattern changes so cached events (atcdb/replay.get_events) are invalidated.
"""
import re

from atcdb.engine import (ClearTakeoff, ClearToCross, ClearToLand, Event, GoAround, Handoff, HoldShort, LineUpAndWait, NoOp,
                          ReadbackObserved, RunwayVacated, normalize_runway)
from atcdb.parsing import Context, Transmission
from atcdb.readback import D, ITEM_PATTERNS

VERSION = "v1"

DIGITS = set("zero one two three four five six seven eight nine niner".split())
NATO = set("alfa alpha bravo charlie delta echo foxtrot golf hotel india juliett juliet kilo lima mike november oscar oskar "
           "papa quebec romeo sierra tango uniform victor whiskey xray yankee zulu".split())
FILLER = set("roger ok okay tower ground hello hi good morning afternoon evening day bye thank you thanks and break copied "
             "wilco affirm yes yeah we are will expedite to the now sir again say please confirm correct that s is it for of "
             "your wait ruzyne".split())
_SIDE = r"(?: left| right| centre| center)?"
RUNWAY_RE = re.compile(rf"\brunway ({D} {D}{_SIDE})\b")
INSTRUCTION_RES = [   # kind, phrase regex. CROSS / HOLD_SHORT capture their runway directly.
    ("LAND", re.compile(r"\bclear(?:ed)? to land\b")),
    ("TAKEOFF", re.compile(r"\bclear(?:ed)? (?:for|to) take ?off\b")),
    ("LUAW", re.compile(r"\bline up\b")),
    ("CROSS", re.compile(rf"\b(?:cross|crossing) runway ({D} {D}{_SIDE})\b")),
    ("HOLD_SHORT", re.compile(rf"\bhold(?:ing)? short(?: of)?(?: runway)? ({D} {D}{_SIDE})\b")),
]
HANDOFF_RE = re.compile(r"\bcontact (?:[a-z]+ ){0,2}?(ground|apron|departure|tower|approach|radar)\b")
GO_AROUND_RE = re.compile(r"\bgo around\b")
_TAIL_NOISE_RE = re.compile(r"\b(?:winds?|good ?bye|bye)\b.*$")
_TO = {"ground": "ground", "apron": "ground", "departure": "departure", "tower": "tower", "approach": "approach", "radar": "approach"}
_EVENT = {"LAND": ClearToLand, "TAKEOFF": ClearTakeoff, "LUAW": LineUpAndWait, "CROSS": ClearToCross, "HOLD_SHORT": HoldShort}


def is_id(word: str) -> bool:
    """Digit or NATO-letter word: the identifying part of a callsign."""
    return word in DIGITS or word in NATO


def take_prefix(words: list[str]) -> list[str]:
    """Callsign at the start of `words`: leading filler dropped, then up to 2 name words + id tokens, stopping at
    the first other word. [] unless at least one id token is present."""
    i = 0
    while i < len(words) and words[i] in FILLER:
        i += 1
    out: list[str] = []
    names = 0
    for w in words[i:]:
        if is_id(w):
            out.append(w)
        elif not any(is_id(x) for x in out) and names < 2 and w not in FILLER:
            out.append(w)
            names += 1
        else:
            break
    return out if any(is_id(w) for w in out) else []


def blank_values(text: str) -> str:
    """Same-length copy of `text` with readback item values (runway/frequency/level/heading/squawk) and the trailing
    wind clause replaced by spaces, so callsign extraction cannot mistake a value for a callsign."""
    out = text
    for _, rx in ITEM_PATTERNS:
        out = rx.sub(lambda m: " " * len(m.group()), out)
    return _TAIL_NOISE_RE.sub(lambda m: " " * len(m.group()), out)


def controller_callsign(blanked: str, first_start: int, last_end: int) -> str:
    before = take_prefix(blanked[:first_start].split())
    if before:
        return " ".join(before)
    after = take_prefix(blanked[last_end:].split())
    return " ".join(after)


def _runway_for(text: str, m: re.Match, kind: str, ctx: Context) -> str | None:
    if kind in ("CROSS", "HOLD_SHORT"):
        return normalize_runway(m.group(1))
    mentions = [(min(abs(r.start() - m.end()), abs(m.start() - r.end())), r.group(1)) for r in RUNWAY_RE.finditer(text)]
    if mentions:
        return normalize_runway(min(mentions)[1])
    if ctx.mode == "window" and len(ctx.active_runways) == 1:
        return ctx.active_runways[0]
    return None


def _controller_events(tx: Transmission, ctx: Context) -> list[Event]:
    text = tx.text
    found: list[tuple[int, int, str, str | None]] = []   # (start, end, kind, runway-or-handoff-target)
    for kind, rx in INSTRUCTION_RES:
        for m in rx.finditer(text):
            runway = _runway_for(text, m, kind, ctx)
            if runway:
                found.append((m.start(), m.end(), kind, runway))
    for m in HANDOFF_RE.finditer(text):
        found.append((m.start(), m.end(), "HANDOFF", _TO[m.group(1)]))
    for m in GO_AROUND_RE.finditer(text):
        found.append((m.start(), m.end(), "GO_AROUND", None))
    if not found:
        return []
    found.sort()
    callsign = controller_callsign(blank_values(text), found[0][0], found[-1][1])
    events: list[Event] = []
    seen: set[tuple[str, str | None]] = set()
    for _, _, kind, arg in found:
        if (kind, arg) in seen:   # a mixed transmission repeats the instruction in the readback: keep the first
            continue
        seen.add((kind, arg))
        if kind == "HANDOFF":
            events.append(Handoff(callsign=callsign, to=arg, t=tx.start_s, text=text))
        elif kind == "GO_AROUND":
            events.append(GoAround(callsign=callsign, t=tx.start_s, text=text))
        else:
            events.append(_EVENT[kind](callsign=callsign, runway=arg, t=tx.start_s, text=text))
    return events


def _pilot_events(tx: Transmission, ctx: Context) -> list[Event]:
    return []   # Task 8


def parse(tx: Transmission, ctx: Context) -> list[Event]:
    """Events for one transmission. Controller-side phrasing is only extracted for controller / mixed / unknown
    roles; pilot transmissions become readbacks (plus pilot-reported releases). Mode `none` has no role, so
    every transmission is treated as controller-side — a pilot's readback then becomes a reservation, which is
    exactly the failure the context ablation is meant to measure."""
    role = ctx.role if ctx.mode != "none" else "unknown"
    events = _pilot_events(tx, ctx) if role == "pilot" else _controller_events(tx, ctx)
    return events or [NoOp(t=tx.start_s, text=tx.text)]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_parse_rules.py -v`
Expected: all PASS. If `test_handoffs` fails on the `sunturk` case, check that `HANDOFF_RE`'s lazy `{0,2}?` group is matching `apron` and that `_TO["apron"] == "ground"`.

- [ ] **Step 5: Commit**

```bash
git add atcdb/parse_rules.py tests/test_parse_rules.py
git commit -m "feat: rules parser for controller runway instructions and handoffs"
```

---

### Task 8: Rules parser — pilot readbacks, releases, context snapping

**Files:**
- Modify: `atcdb/parse_rules.py` (replace `_pilot_events`, add helpers)
- Modify: `tests/test_parse_rules.py` (append)

**Interfaces:**
- Consumes: Task 7.
- Produces: `pilot_callsign(text) -> str`, `take_suffix(words) -> list[str]`, `snap_callsign(raw, candidates) -> str`; `_pilot_events` now returns `[ReadbackObserved(callsign, text)]` plus `RunwayVacated` / `GoAround` when the pilot reports them.
- Heuristics:
  - Pilot callsign = the **trailing** id tokens of the transmission (after dropping trailing filler), plus up to 2 name words before them; rejected if the word before the run is a value keyword (`runway`, `level`, `heading`, `squawk`, `flight`, ...).
  - `snap_callsign`: in `window` mode, if the raw callsign's id tokens are an in-order subsequence of exactly one active callsign's id tokens (and any name words agree), return the active one. `"csa eight eight whiskey"` → `"csa eight three eight whiskey"`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_parse_rules.py` (extend the imports with `ReadbackObserved, RunwayVacated` from `atcdb.engine` and `pilot_callsign, snap_callsign, take_suffix` from `atcdb.parse_rules`):

```python
def test_pilot_transmission_is_a_readback_with_trailing_callsign():
    text = "cleared to land csa nine seven five"
    assert parse(_tx(text, role="pilot", t=4.0), PLT) == [ReadbackObserved(callsign="csa nine seven five", text=text, t=4.0)]


def test_pilot_callsign_survives_trailing_filler_and_bye():
    assert pilot_callsign("cleared to land one three csa three eight whiskey and will expedite to") == "csa three eight whiskey"
    assert pilot_callsign("one two one nine bye bye lufthansa five mike echo") == "lufthansa five mike echo"
    assert pilot_callsign("cleared for takeoff runway three one air france one zero eight three good bye") == "air france one zero eight three"
    assert pilot_callsign("reducing one sixty csa eight eight whiskey") == "csa eight eight whiskey"
    assert pilot_callsign("descending flight level one hundred swiss one two four") == "swiss one two four"
    assert pilot_callsign("hotel bravo sierra delta foxtrot") == "hotel bravo sierra delta foxtrot"


def test_pilot_values_are_not_mistaken_for_callsigns():
    assert pilot_callsign("we are cleared for takeoff runway one three") == ""
    assert pilot_callsign("climbing flight level one zero zero") == ""
    assert pilot_callsign("roger") == ""


def test_pilot_reports_vacated_and_going_around():
    ev = parse(_tx("runway vacated csa one two three", role="pilot"), PLT)
    assert _kinds(ev) == [("ReadbackObserved", "csa one two three", None), ("RunwayVacated", "csa one two three", None)]
    ev = parse(_tx("going around csa one two three", role="pilot"), PLT)
    assert _kinds(ev) == [("ReadbackObserved", "csa one two three", None), ("GoAround", "csa one two three", None)]
    ev = parse(_tx("vacating via bravo csa one two three", role="pilot"), PLT)
    assert [type(e) for e in ev] == [ReadbackObserved, RunwayVacated]


def test_take_suffix():
    assert take_suffix("cleared to land csa nine seven five".split()) == ["csa", "nine", "seven", "five"]
    assert take_suffix("we are cleared for takeoff runway one three".split()) == []
    assert take_suffix("line up runway three one csa two mike".split()) == ["csa", "two", "mike"]


def test_snap_callsign_matches_abbreviations_in_order_only():
    active = ("csa eight three eight whiskey", "csa seven three zero", "air france one nine eight romeo")
    assert snap_callsign("csa eight eight whiskey", active) == "csa eight three eight whiskey"
    assert snap_callsign("air france one nine", active) == "air france one nine eight romeo"
    assert snap_callsign("csa seven three charlie", active) == "csa seven three charlie"   # charlie is not in any candidate
    assert snap_callsign("lufthansa seven three", active) == "lufthansa seven three"       # name disagrees
    assert snap_callsign("", active) == ""
    assert snap_callsign("csa eight", ("csa eight one", "csa eight two")) == "csa eight"     # ambiguous: leave it


def test_window_mode_snaps_pilot_callsign_but_role_mode_does_not():
    text = "reducing one sixty csa eight eight whiskey"
    win = Context(mode="window", role="pilot", active_callsigns=("csa eight three eight whiskey",))
    assert parse(_tx(text, role="pilot"), win)[0].callsign == "csa eight three eight whiskey"
    assert parse(_tx(text, role="pilot"), PLT)[0].callsign == "csa eight eight whiskey"


def test_none_mode_turns_a_pilot_readback_into_a_reservation():
    text = "cleared for takeoff runway three one csa two mike zulu"
    assert _kinds(parse(_tx(text, role="pilot"), Context(mode="none"))) == [("ClearTakeoff", "csa two mike zulu", "31")]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_parse_rules.py -v`
Expected: the new tests FAIL with `ImportError: cannot import name 'pilot_callsign'`.

- [ ] **Step 3: Implement the pilot side**

In `atcdb/parse_rules.py`, add after `controller_callsign`:

```python
_VALUE_LEAD = set("runway level heading squawk flight altitude speed wind contact descend climb maintain reduce".split())
# Words that can sit right before a callsign's id tokens without being part of its name ("reducing one sixty csa ...").
_NOT_NAME = FILLER | _VALUE_LEAD | set(
    "land takeoff up short cross left right centre center hundred thousand ten twenty thirty forty fifty sixty seventy "
    "eighty ninety vacated vacating around established ready going holding lining landing climbing descending reducing "
    "passing leaving maintaining request copied".split())
PILOT_VACATED_RE = re.compile(r"\bvacat(?:ed|ing)\b")
PILOT_GO_AROUND_RE = re.compile(r"\bgoing around\b")


def take_suffix(words: list[str]) -> list[str]:
    """Callsign at the end of `words`: trailing filler dropped, then the trailing run of id tokens plus up to 2 name
    words before it. [] if there is no id run or it is a value ("runway one three")."""
    j = len(words)
    while j > 0 and words[j - 1] in FILLER:
        j -= 1
    i = j
    while i > 0 and is_id(words[i - 1]):
        i -= 1
    if i == j:
        return []
    if i > 0 and words[i - 1] in _VALUE_LEAD:
        return []
    k = i
    while k > 0 and i - k < 2 and not is_id(words[k - 1]) and words[k - 1] not in _NOT_NAME:
        k -= 1
    return words[k:j]


def pilot_callsign(text: str) -> str:
    return " ".join(take_suffix(text.split()))


def _ids(callsign: str) -> list[str]:
    return [w for w in callsign.split() if is_id(w)]


def _names(callsign: str) -> list[str]:
    return [w for w in callsign.split() if not is_id(w)]


def _is_subsequence(short: list[str], long: list[str]) -> bool:
    it = iter(long)
    return all(any(x == y for y in it) for x in short)


def snap_callsign(raw: str, candidates: tuple[str, ...]) -> str:
    """Map an abbreviated pilot callsign onto the one active aircraft it can only be; otherwise return it unchanged."""
    ids = _ids(raw)
    if len(ids) < 1:
        return raw
    hits = [c for c in candidates
            if _is_subsequence(ids, _ids(c)) and (not _names(raw) or not _names(c) or _names(raw) == _names(c))]
    return hits[0] if len(hits) == 1 else raw
```

and replace the `_pilot_events` stub with:

```python
def _pilot_events(tx: Transmission, ctx: Context) -> list[Event]:
    text = tx.text
    callsign = pilot_callsign(text)
    if ctx.mode == "window" and callsign:
        callsign = snap_callsign(callsign, ctx.active_callsigns)
    events: list[Event] = [ReadbackObserved(callsign=callsign, text=text, t=tx.start_s)]
    if PILOT_VACATED_RE.search(text):
        events.append(RunwayVacated(callsign=callsign, t=tx.start_s, text=text))
    if PILOT_GO_AROUND_RE.search(text):
        events.append(GoAround(callsign=callsign, t=tx.start_s, text=text))
    return events
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_parse_rules.py -v`
Expected: all PASS. Then `.venv/bin/python -m pytest -q` — all green.

- [ ] **Step 5: Commit**

```bash
git add atcdb/parse_rules.py tests/test_parse_rules.py
git commit -m "feat: rules parser pilot readbacks, releases and callsign snapping"
```

---

### Task 9: Replay — loading a recording, building context, listing recordings

**Files:**
- Create: `atcdb/replay.py`
- Create: `tests/test_replay.py`

**Interfaces:**
- Consumes: `State`, `Conflict`, `Event`, `apply` (Tasks 3–5); `Transmission`, `Context`, `CONTEXT_MODES`, `WINDOW`, `Parser`, `event_to_row`, `row_to_event` (Task 6); `parse_rules.parse`, `parse_rules.VERSION` (Tasks 7–8).
- Produces:
  - `PARSERS: dict[str, Parser] = {"rule": parse_rules.parse}` and `PARSER_MODELS: dict[str, tuple[str, str]] = {"rule": ("rules", parse_rules.VERSION)}` — phase 3 registers `"llm"` here.
  - `Step(tx, events, conflicts, state, error=None)` and `Timeline(recording_id, parser, model, model_version, context, transcript_kind, steps)` frozen dataclasses.
  - `load_recording(conn, recording_id, transcript_kind="gold", transcript_model=None) -> list[Transmission]` — time order; a transmission without a transcript of that kind is skipped.
  - `build_context(mode, tx, history, state) -> Context` — `history` is the list of earlier `Transmission`s; raises `ValueError` on an unknown mode.
  - `list_recordings(conn, facility="Tower", min_transmissions=4, transcript_kind="gold") -> list[sqlite3.Row]` with columns `id, source, external_id, airport_icao, facility, n_transmissions, n_runway_mentions`, most transmissions first (the spec's replay list).

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_replay.py
import pytest

from atcdb.engine import ClearToLand, NoOp, State, fold
from atcdb.parsing import Context
from atcdb.replay import (PARSER_MODELS, PARSERS, Step, Timeline, build_context, build_timeline, get_events,
                          list_recordings, load_recording)
from atcdb.schema import init_db


def _seed(conn, turns, external_id="r1", facility="Tower"):
    """One recording with `turns` = [(role, text), ...] at 10 s spacing, gold transcripts by 'human'. Returns its id."""
    conn.execute("INSERT OR IGNORE INTO sources (id, name, kind) VALUES (1, 'test', 'corpus')")
    rid = conn.execute("INSERT INTO recordings (source_id, external_id, facility) VALUES (1, ?, ?)", (external_id, facility)).lastrowid
    for i, (role, text) in enumerate(turns):
        xid = conn.execute("INSERT INTO transmissions (recording_id, external_id, start_s, end_s, speaker_role) VALUES (?, ?, ?, ?, ?)",
                           (rid, f"x{i}", 10.0 * i, 10.0 * i + 3, role)).lastrowid
        conn.execute("INSERT INTO transcripts (transmission_id, kind, model, raw_text, normalized_text) VALUES (?, 'gold', 'human', ?, ?)",
                     (xid, text, text))
    conn.commit()
    return rid


SEQUENCE = [
    ("controller", "csa one two three runway three one cleared to land wind calm"),
    ("pilot", "cleared to land runway three one csa one two three"),
    ("controller", "lufthansa four five six cross runway three one"),          # CROSS while csa still has LAND -> alert
    ("pilot", "crossing runway three one lufthansa four five six"),
    ("pilot", "runway vacated csa one two three"),
    ("controller", "lufthansa four five six contact ground one two one nine"),
    ("pilot", "one two one five lufthansa four five six"),                     # wrong frequency -> readback warning
]


def test_load_recording_is_in_time_order_and_picks_the_transcript_kind(tmp_path):
    conn = init_db(tmp_path / "t.sqlite")
    rid = _seed(conn, SEQUENCE)
    txs = load_recording(conn, rid)
    assert [(tx.role, tx.start_s) for tx in txs][:3] == [("controller", 0.0), ("pilot", 10.0), ("controller", 20.0)]
    assert txs[0].text == SEQUENCE[0][1] and txs[0].transcript_id > 0
    conn.execute("INSERT INTO transcripts (transmission_id, kind, model, raw_text, normalized_text) VALUES (?, 'asr', 'w', 'x', 'asr text')", (txs[2].id,))
    asr = load_recording(conn, rid, transcript_kind="asr")
    assert [(tx.id, tx.text) for tx in asr] == [(txs[2].id, "asr text")]
    assert load_recording(conn, 999) == []


def test_build_context_modes(tmp_path):
    conn = init_db(tmp_path / "t.sqlite")
    txs = load_recording(conn, _seed(conn, SEQUENCE))
    state, _ = fold([ClearToLand(callsign="csa one two three", runway="31", text="x")])
    assert build_context("none", txs[5], txs[:5], state) == Context(mode="none")
    assert build_context("role", txs[5], txs[:5], state) == Context(mode="role", role="controller")
    win = build_context("window", txs[5], txs[:5], state)
    assert win.mode == "window" and win.role == "controller"
    assert win.history == tuple((r, t) for r, t in SEQUENCE[1:5])     # last 4, oldest first
    assert win.active_callsigns == ("csa one two three",) and win.active_runways == ("31",)
    assert build_context("window", txs[0], [], State()).history == ()
    with pytest.raises(ValueError):
        build_context("everything", txs[0], [], State())


def test_list_recordings_keeps_tower_recordings_with_enough_transmissions_and_a_runway(tmp_path):
    conn = init_db(tmp_path / "t.sqlite")
    big = _seed(conn, SEQUENCE, external_id="big")
    _seed(conn, SEQUENCE[:2], external_id="short")
    _seed(conn, SEQUENCE, external_id="approach", facility="Approach")
    _seed(conn, [("controller", "csa one two three descend flight level one hundred")] * 5, external_id="no-runway")
    rows = list_recordings(conn)
    assert [(r["id"], r["external_id"], r["n_transmissions"], r["n_runway_mentions"]) for r in rows] == [(big, "big", 7, 5)]
    assert list_recordings(conn, min_transmissions=2)[1]["external_id"] == "short"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_replay.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'atcdb.replay'`.

- [ ] **Step 3: Write the module (first half)**

```python
# atcdb/replay.py
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
```

The `build_timeline` / `get_events` names imported by the test file do not exist yet — add these two placeholders at the end of the module so the import succeeds; Task 10 replaces them:

```python
def get_events(*args, **kwargs):
    raise NotImplementedError   # Task 10


def build_timeline(*args, **kwargs):
    raise NotImplementedError   # Task 10
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_replay.py -v`
Expected: the three tests PASS.

- [ ] **Step 5: Commit**

```bash
git add atcdb/replay.py tests/test_replay.py
git commit -m "feat: replay loading, context building and recording list"
```

---

### Task 10: Replay — cached events and the timeline fold

**Files:**
- Modify: `atcdb/replay.py` (replace the two placeholders)
- Modify: `tests/test_replay.py` (append)

**Interfaces:**
- Consumes: Task 9.
- Produces:
  - `get_events(conn, tx, parser, ctx, model=None, model_version=None) -> list[Event]` — cache hit returns rows with `t`/`text` re-attached from `tx`; miss calls `PARSERS[parser]`, stores one row per event (a parse that yields only `NoOp` stores one `NOOP` row) and commits. A parser exception propagates and **nothing is stored**.
  - `build_timeline(conn, recording_id, parser="rule", transcript_kind="gold", context="window", model=None, model_version=None, transcript_model=None) -> Timeline`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_replay.py`:

```python
def _fake_parser(events_by_text, calls):
    def parse(tx, ctx):
        calls.append(tx.text)
        out = events_by_text[tx.text]
        if isinstance(out, Exception):
            raise out
        return out
    return parse


def test_get_events_parses_once_then_serves_the_cache(tmp_path, monkeypatch):
    conn = init_db(tmp_path / "t.sqlite")
    txs = load_recording(conn, _seed(conn, SEQUENCE[:1]))
    calls = []
    monkeypatch.setitem(PARSERS, "rule", _fake_parser({SEQUENCE[0][1]: [ClearToLand(callsign="csa one two three", runway="31")]}, calls))
    monkeypatch.setitem(PARSER_MODELS, "rule", ("fake", "v0"))
    ctx = Context(mode="role", role="controller")
    first = get_events(conn, txs[0], "rule", ctx)
    second = get_events(conn, txs[0], "rule", ctx)
    assert calls == [SEQUENCE[0][1]]
    assert first == [ClearToLand(callsign="csa one two three", runway="31")]
    assert second == [ClearToLand(callsign="csa one two three", runway="31", t=0.0, text=SEQUENCE[0][1])]
    rows = conn.execute("SELECT parser, model, model_version, context, seq, kind, runway FROM events").fetchall()
    assert [tuple(r) for r in rows] == [("rule", "fake", "v0", "role", 0, "LAND", "31")]
    get_events(conn, txs[0], "rule", Context(mode="none"))   # a different context mode is a different cache entry
    assert len(calls) == 2 and conn.execute("SELECT count(*) FROM events").fetchone()[0] == 2


def test_get_events_stores_a_noop_row_for_an_empty_parse(tmp_path, monkeypatch):
    conn = init_db(tmp_path / "t.sqlite")
    txs = load_recording(conn, _seed(conn, SEQUENCE[:1]))
    calls = []
    monkeypatch.setitem(PARSERS, "rule", _fake_parser({SEQUENCE[0][1]: [NoOp()]}, calls))
    get_events(conn, txs[0], "rule", Context(mode="role", role="controller"))
    assert get_events(conn, txs[0], "rule", Context(mode="role", role="controller")) == [NoOp(t=0.0, text=SEQUENCE[0][1])]
    assert calls == [SEQUENCE[0][1]]
    assert conn.execute("SELECT kind FROM events").fetchone()[0] == "NOOP"


def test_get_events_does_not_cache_a_failed_parse(tmp_path, monkeypatch):
    conn = init_db(tmp_path / "t.sqlite")
    txs = load_recording(conn, _seed(conn, SEQUENCE[:1]))
    monkeypatch.setitem(PARSERS, "rule", _fake_parser({SEQUENCE[0][1]: RuntimeError("api down")}, []))
    with pytest.raises(RuntimeError):
        get_events(conn, txs[0], "rule", Context(mode="role", role="controller"))
    assert conn.execute("SELECT count(*) FROM events").fetchone()[0] == 0


def test_build_timeline_with_the_rules_parser_end_to_end(tmp_path):
    conn = init_db(tmp_path / "t.sqlite")
    rid = _seed(conn, SEQUENCE)
    tl = build_timeline(conn, rid)
    assert isinstance(tl, Timeline) and (tl.parser, tl.model, tl.context, tl.transcript_kind) == ("rule", "rules", "window", "gold")
    assert len(tl.steps) == 7 and all(isinstance(s, Step) and s.error is None for s in tl.steps)
    assert [(r.callsign, r.kind) for r in tl.steps[0].state.runways["31"]] == [("csa one two three", "LAND")]
    assert tl.steps[1].conflicts == () and tl.steps[1].state.aircraft["csa one two three"].pending is None
    c = tl.steps[2].conflicts
    assert len(c) == 1 and (c[0].type, c[0].severity, c[0].runway, c[0].callsigns) == ("RUNWAY", "alert", "31", ("lufthansa four five six", "csa one two three"))
    assert tl.steps[4].state.aircraft["csa one two three"].runway is None            # runway vacated
    assert "31" not in tl.steps[5].state.runways                                      # handoff to ground released the crossing
    r = tl.steps[6].conflicts
    assert len(r) == 1 and (r[0].type, r[0].severity, r[0].callsigns) == ("READBACK", "warning", ("lufthansa four five six",))
    assert sum(len(s.conflicts) for s in tl.steps) == 2
    assert conn.execute("SELECT count(DISTINCT transcript_id) FROM events").fetchone()[0] == 7
    again = build_timeline(conn, rid)   # second run is served from the cache and must be identical
    assert [s.events for s in again.steps] == [s.events for s in tl.steps]


def test_build_timeline_records_a_parser_error_and_keeps_going(tmp_path, monkeypatch):
    conn = init_db(tmp_path / "t.sqlite")
    rid = _seed(conn, SEQUENCE[:3])
    table = {SEQUENCE[0][1]: [ClearToLand(callsign="csa one two three", runway="31")],
             SEQUENCE[1][1]: RuntimeError("api down"),
             SEQUENCE[2][1]: [NoOp()]}
    monkeypatch.setitem(PARSERS, "rule", _fake_parser(table, []))
    tl = build_timeline(conn, rid, context="role")
    assert [s.error for s in tl.steps] == [None, "RuntimeError: api down", None]
    assert tl.steps[1].events == () and tl.steps[1].state == tl.steps[0].state
    assert tl.steps[2].state.seq == 2
    assert conn.execute("SELECT count(*) FROM events").fetchone()[0] == 2   # the failed one was not cached
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_replay.py -v`
Expected: the five new tests FAIL with `NotImplementedError`.

- [ ] **Step 3: Replace the placeholders**

Delete the two placeholder functions at the end of `atcdb/replay.py` and append:

```python
def get_events(conn: sqlite3.Connection, tx: Transmission, parser: str, ctx: Context,
               model: str | None = None, model_version: str | None = None) -> list[Event]:
    """Events for one transcript under (parser, model, version, context mode): from the `events` cache, or parsed
    and stored. A parser exception propagates and nothing is stored, so the next call retries."""
    if model is None:
        model, model_version = PARSER_MODELS[parser]
    model_version = model_version or ""
    rows = conn.execute(
        """SELECT kind, callsign, runway, extra_json FROM events
           WHERE transcript_id = ? AND parser = ? AND model = ? AND model_version = ? AND context = ?
           ORDER BY seq""", (tx.transcript_id, parser, model, model_version, ctx.mode)).fetchall()
    if rows:
        return [row_to_event(r["kind"], r["callsign"], r["runway"], r["extra_json"], t=tx.start_s, text=tx.text) for r in rows]
    events = PARSERS[parser](tx, ctx)
    conn.executemany(
        """INSERT INTO events (transcript_id, parser, model, model_version, context, seq, kind, callsign, runway, extra_json)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        [(tx.transcript_id, parser, model, model_version, ctx.mode, i, *event_to_row(e)) for i, e in enumerate(events)])
    conn.commit()
    return events


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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_replay.py -v`
Expected: all PASS. Then `.venv/bin/python -m pytest -q` — all green.

- [ ] **Step 5: Commit**

```bash
git add atcdb/replay.py tests/test_replay.py
git commit -m "feat: cached parser events and replay timeline fold"
```

---

### Task 11: Scripts, README, and a real-data smoke run

**Files:**
- Create: `scripts/parse_events.py`
- Create: `scripts/show_replay.py`
- Modify: `README.md`

**Interfaces:**
- Consumes: `list_recordings`, `build_timeline` (Tasks 9–10), `init_db` (exists).
- Produces: two CLIs. No library code; no unit tests (the repo does not test its thin scripts).

- [ ] **Step 1: Write the precompute script**

```python
# scripts/parse_events.py
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
```

- [ ] **Step 2: Write the replay viewer**

```python
# scripts/show_replay.py
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
from atcdb.replay import PARSERS, build_timeline  # noqa: E402
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
    tl = build_timeline(conn, row["id"], parser=args.parser, transcript_kind=args.transcript, context=args.context)
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
```

- [ ] **Step 3: Smoke-run both scripts on the real database**

Run:

```bash
.venv/bin/python scripts/show_replay.py uwb-atcc_TWR-DM7AI0
.venv/bin/python scripts/parse_events.py --limit 50
.venv/bin/python scripts/parse_events.py --limit 50    # second run: same numbers, near-instant (cache)
```

Expected for the first command: 27 transmissions printed; the "expedite cross runway one three" transmission shows `ClearToCross('air france one nine eight romeo', 13)` and `HoldShort(..., 24)`; "runway one three cleared to land" shows `ClearToLand('csa three eight whiskey', 13)`; "contact ruzyne ground" shows `Handoff('csa eight two nine', to=ground)`. Expect exactly **one** conflict: an ALERT on the landing clearance at 01:30, because Air France's crossing of runway 13 was never released on frequency (no "vacated" call, no handoff) and is still inside the 300 s staleness window. That is a **known false positive** of the v1 rules — a crossing lasts seconds, not minutes — and is report material for tuning per-kind staleness later; do not "fix" it in this task. The second command prints an events census over 50 recordings (roughly 350 readbacks, 220 no-ops, a few dozen runway instructions, about 20 conflicts); the third prints the same census with no new parsing and finishes in well under a second.

If a transmission crashes the parser (traceback instead of `!! parse error`), that is a bug in `parse_rules.py`: add a regression test with that exact text to `tests/test_parse_rules.py`, fix, and re-run.

- [ ] **Step 4: Update the README**

In `README.md`, append after the ASR baseline block (step 3) and before `pytest`:

```markdown
# 4. conflict engine (phase 1): parse transmissions into runway events, replay a recording, flag conflicts
python scripts/parse_events.py                     # cache rules-parser events for every replayable tower recording
python scripts/show_replay.py uwb-atcc_TWR-DM7AI0  # step through one recording: events, conflicts, runway board
```

and change the `pytest   # 29 tests` line to the number `.venv/bin/python -m pytest -q` actually reports. Add one sentence to the intro paragraph: "The conflict engine (`atcdb/engine.py`) turns parsed clearances into runway reservations and flags incompatible ones; see `docs/superpowers/specs/2026-09-12-conflict-engine-design.md`."

- [ ] **Step 5: Run the whole suite and commit**

Run: `.venv/bin/python -m pytest -q`
Expected: all green.

```bash
git add scripts/parse_events.py scripts/show_replay.py README.md
git commit -m "feat: parse_events and show_replay CLIs for the conflict engine"
```

---

## Out of scope for this plan (next plans)

- **Phase 2**: `atcdb/api.py` (FastAPI, `create_app`), `atcdb/static/`, clips/capabilities endpoints — spec Section 3.
- **Phase 3**: `atcdb/parse_llm.py` (register as `PARSERS["llm"]`, load the `claude-api` skill first), `scripts/make_event_sheet.py`, conflict injection under source `synthetic-conflicts`, `scripts/eval_parsers.py`, `eval_conflicts.py`, `eval_llm_judge.py` — spec Section 4.
- **Phase 4**: live push-to-talk endpoint, incident case studies.
