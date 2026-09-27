# Claude Parser (Phase 3a) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a Claude tool-use parser beside the frozen rules parser, with Haiku 4.5 and Sonnet 5 as its two models, and land the cache-affecting carry-overs first, so that `parser=llm` replays in the UI and every LLM parse is cached under a key that cannot go stale.

**Architecture:** A new `atcdb/parse_llm.py` turns one transmission into one forced `report_events` tool call and maps the tool input onto the engine's events; anything it cannot map becomes a new `Unresolved` event that the engine counts but never acts on, so the dropped count survives the cache. `atcdb/replay.py` gains a parser registry keyed by parser then model, resolves the Claude parser only on a cache miss (so a cached replay needs neither `anthropic` nor a key), and adds `ENGINE_VERSION` to the cache key of `window` parses. The API, the precompute script and the page follow the registry.

**Tech Stack:** Python 3.14, sqlite3, pytest, `anthropic` 1.8.0 (new), FastAPI, vanilla JS.

**Spec:** `docs/superpowers/specs/2026-09-12-conflict-engine-design.md` — the **Addendum — phase-3 design pass**, sections A.4 and A.7.2 (the addendum wins where it and the text above it differ). This plan is phase 3a in the addendum's build order (A.1). Phase 2.5 is done (PR #3).

## Global Constraints

- The rules parser is **frozen at v1** (spec A.7.1): `atcdb/parse_rules.py` is not modified, and `parse_rules.VERSION` stays `"v1"`.
- `atcdb/engine.py` stays pure: no I/O, no database access and no new imports.
- The Claude parser's models are exactly `claude-haiku-4-5` and `claude-sonnet-5` (spec A.4). Haiku runs at temperature 0; Sonnet 5 rejects `temperature`, so it runs with `thinking: {"type": "disabled"}` and `output_config: {"effort": "low"}`. Both use one strict tool, `report_events`, with a forced `tool_choice`.
- `anthropic` 1.x removed `temperature` from `messages.create`; Haiku's temperature goes in `extra_body={"temperature": 0}`.
- API errors and `stop_reason: "refusal"` propagate and **nothing is cached** (spec A.4). A parse with no events stores the NOOP row, as today.
- Importing `atcdb.replay` or `atcdb.api` must never import `anthropic`, and a replay served entirely from the cache must work without `anthropic` installed and without `ANTHROPIC_API_KEY`.
- The parser is named `llm`, not `claude`: the `events` table has `CHECK (parser IN ('rule', 'llm'))` (spec Section 1), and changing a CHECK constraint in SQLite means rebuilding the table.
- UWB-ATCC is CC BY-NC-ND and is **not redistributed**: no corpus transcript text goes into a fixture, a prompt example or a recorded response. Recorded responses use NTSB public-record text and invented transmissions only.
- Tests follow the repo's style: plain pytest functions, real SQLite files under `tmp_path`, `monkeypatch` only, no mock framework. The Anthropic client is injected; tests use a small fake client. Run with `.venv/bin/python -m pytest`.
- Commit after every task; `feat:`/`test:`/`docs:` subjects ending with the attribution lines the session provides.

## Decisions taken while planning (user-approved 2026-09-27)

- **ENGINE_VERSION in the cache key (A.7.2):** only `window` parses see engine state, so only `window` rows carry it. The stored `model_version` of a `window` row becomes `<parser version>+engine<ENGINE_VERSION>` (for example `v1+engine1`); `none` and `role` rows keep the plain version. No schema change. The existing rules `window` rows (stored as `v1`) are never read again; they re-parse instantly on the next replay. `Timeline.model_version` and the API still report the plain parser version.
- **Dropped events survive the cache:** an event from Claude that fails validation (a runway that does not normalise, a runway instruction without a runway, a handoff without a target) is stored as an `UNRESOLVED` row carrying what the model said. The engine counts it in `State.ignored` and does nothing else, so `Step.dropped` picks it up through the existing per-step delta, on cache hits too.
- **Recorded responses:** a few real Haiku and Sonnet responses, recorded once with `scripts/record_llm_fixtures.py`, back the response mapper. They are committed under `tests/fixtures/`.

## File structure

| File | Responsibility |
|---|---|
| `atcdb/engine.py` (modify) | `ENGINE_VERSION`; the `Unresolved` event, counted in `State.ignored` |
| `atcdb/parsing.py` (modify) | `UNRESOLVED` row kind and its `raw` payload |
| `atcdb/parse_llm.py` (create) | the `report_events` tool, the system prompt, prompt rendering, the per-model request, response-to-event mapping, `make_parser`, `availability`, cost estimate |
| `atcdb/replay.py` (modify) | registry (`PARSER_MODELS`, `PARSER_VERSIONS`, `PARSERS` factories), `cache_version`, per-recording transcript pinning, `get_events` re-raise |
| `atcdb/api.py` (modify) | capabilities per parser-model pair with `available`/`reason`; validated `model` on the replay route |
| `atcdb/static/app.js` (modify) | parser-model options (unavailable ones disabled), request token, dropped and unresolved chips |
| `scripts/parse_events.py` (modify) | `--model`, `--recording`, `--dry-run` |
| `scripts/show_replay.py` (modify) | `--model`, per-recording pinning |
| `scripts/record_llm_fixtures.py` (create) | records real responses into `tests/fixtures/llm_responses.json` |
| `requirements.txt` (modify) | `anthropic==1.8.0` |
| tests: `test_engine.py`, `test_parsing.py`, `test_serialize.py`, `test_replay.py`, `test_api.py` (modify); `test_parse_llm.py` (create); `tests/fixtures/llm_responses.json` (create) | |
| `README.md` (modify) | the Claude parser, the key, test count |

Domain vocabulary for the engineer: a **transmission** is one radio call; its **transcript** is the text (gold = human, or ASR). A parser turns one transcript into **events** (LAND = cleared to land, TAKEOFF = cleared for takeoff, LUAW = line up and wait, CROSS = cleared to cross, HOLD_SHORT, VACATED, GO_AROUND, HANDOFF to another frequency, READBACK = a pilot repeating an instruction, NOOP = nothing relevant). The engine folds events into runway reservations and raises **conflicts**. Parses are cached in the `events` table keyed by `(transcript_id, parser, model, model_version, context)`. **Context** is what the parser sees besides the text: `none`, `role` (the speaker's role) or `window` (role, the last 4 transmissions, and the aircraft and runways the engine is tracking, which is why `window` parses depend on the engine).

---

### Task 1: The Unresolved event and ENGINE_VERSION

Two engine additions the rest of the plan builds on. `Unresolved` is what a parser emits for an instruction it recognised but cannot express as an event; the engine counts it in `State.ignored` (already surfaced as `Step.dropped` by phase 2.5) and does nothing else. `ENGINE_VERSION` is a hand-bumped string that Task 2 puts into the cache key.

**Files:**
- Modify: `atcdb/engine.py`, `atcdb/parsing.py`
- Test: `tests/test_engine.py`, `tests/test_parsing.py`, `tests/test_serialize.py`

**Interfaces:**
- Produces: `engine.ENGINE_VERSION: str` (`"1"`); `engine.Unresolved(Event)` with `raw: str = ""`; `parsing.KINDS[Unresolved] == "UNRESOLVED"`; `event_to_row(Unresolved(...))` stores `{"raw": ...}` in `extra_json`, and `row_to_event` restores it.

- [ ] **Step 1: Write the failing tests**

In `tests/test_engine.py`, replace:

```python
from atcdb.engine import (ClearTakeoff, ClearToCross, ClearToLand, Event, GoAround, Handoff, HANDOFF_TARGETS, HoldShort,
                          LineUpAndWait, MATRIX, NoOp, ReadbackObserved, RESERVATION_KINDS, RunwayVacated,
                          STALE_S, State, apply, fold, normalize_runway)
```

with:

```python
from atcdb.engine import (ENGINE_VERSION, ClearTakeoff, ClearToCross, ClearToLand, Event, GoAround, Handoff, HANDOFF_TARGETS,
                          HoldShort, LineUpAndWait, MATRIX, NoOp, ReadbackObserved, RESERVATION_KINDS, RunwayVacated,
                          STALE_S, State, Unresolved, apply, fold, normalize_runway)
```

Append to `tests/test_engine.py`:

```python


# --- phase 3a (spec addendum A.4, A.7.2) -------------------------------------------------------

def test_unresolved_is_counted_and_changes_nothing_else():
    state, _ = fold([ClearToLand(callsign="a", runway="31")])
    after, c = fold([Unresolved(callsign="b", raw='{"kind": "CROSS", "runway": "three seven"}')], state)
    assert c == [] and after.ignored == 1
    assert (after.runways, after.aircraft) == (state.runways, state.aircraft)
    assert isinstance(ENGINE_VERSION, str) and ENGINE_VERSION
```

In `tests/test_parsing.py`, replace:

```python
from atcdb.engine import (ClearTakeoff, ClearToCross, ClearToLand, GoAround, Handoff, HoldShort, LineUpAndWait, NoOp,
                          ReadbackObserved, RunwayVacated)
```

with:

```python
from atcdb.engine import (ClearTakeoff, ClearToCross, ClearToLand, GoAround, Handoff, HoldShort, LineUpAndWait, NoOp,
                          ReadbackObserved, RunwayVacated, Unresolved)
```

In `tests/test_parsing.py`, replace:

```python
    (NoOp(), ("NOOP", "", None, None)),
])
```

with:

```python
    (NoOp(), ("NOOP", "", None, None)),
    (Unresolved(callsign="a", raw="CROSS three seven"), ("UNRESOLVED", "a", None, '{"raw": "CROSS three seven"}')),
])
```

In `tests/test_parsing.py`, replace:

```python
              Handoff(callsign="a", to="departure", t=1.0, text="x"), ReadbackObserved(callsign="a", text="x", t=1.0), NoOp(t=1.0, text="x")]
```

with:

```python
              Handoff(callsign="a", to="departure", t=1.0, text="x"), ReadbackObserved(callsign="a", text="x", t=1.0), NoOp(t=1.0, text="x"),
              Unresolved(callsign="a", raw="LAND", t=1.0, text="x")]
```

In `tests/test_serialize.py`, replace:

```python
from atcdb.engine import (ClearToLand, Handoff, HoldShort, LineUpAndWait, NoOp, ReadbackObserved, State, apply, fold)
```

with:

```python
from atcdb.engine import (ClearToLand, Handoff, HoldShort, LineUpAndWait, NoOp, ReadbackObserved, State, Unresolved, apply,
                          fold)
```

In `tests/test_serialize.py`, replace:

```python
    assert event_dict(NoOp()) == {"kind": "NOOP", "callsign": "", "runway": None, "to": None}
```

with:

```python
    assert event_dict(NoOp()) == {"kind": "NOOP", "callsign": "", "runway": None, "to": None}
    assert event_dict(Unresolved(callsign="a", raw="LAND")) == {"kind": "UNRESOLVED", "callsign": "a", "runway": None, "to": None}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_engine.py tests/test_parsing.py tests/test_serialize.py -q`
Expected: FAIL — `ImportError: cannot import name 'ENGINE_VERSION'` and `cannot import name 'Unresolved'` (the three modules fail to collect).

- [ ] **Step 3: Write minimal implementation**

In `atcdb/engine.py`, replace:

```python
@dataclass(frozen=True, kw_only=True)
class NoOp(Event):
    pass
```

with:

```python
@dataclass(frozen=True, kw_only=True)
class NoOp(Event):
    pass


@dataclass(frozen=True, kw_only=True)
class Unresolved(Event):
    raw: str = ""        # what the parser reported, verbatim (e.g. a runway that does not normalise); never acted on
```

In `atcdb/engine.py`, replace:

```python
    ignored: int = 0     # events so far that the engine received but could not act on (unknown handoff target)
```

with:

```python
    ignored: int = 0     # events so far that the engine received but could not act on (unknown handoff target, Unresolved)
```

In `atcdb/engine.py`, replace:

```python
# --- rules ------------------------------------------------------------------------------------

```

with:

```python
# --- rules ------------------------------------------------------------------------------------

# Bumped by hand whenever a change to the rules below can change what the engine tracks. `window`-mode parses see the
# engine's active runways and callsigns, so the events cache keys them by this too (spec addendum A.7.2).
# "1" = the engine after phase 2.5.
ENGINE_VERSION = "1"

```

In `atcdb/engine.py`, replace:

```python
    elif isinstance(event, NoOp):
        pass
```

with:

```python
    elif isinstance(event, Unresolved):
        ignored += 1   # a parser saw an instruction it could not express as an event: counted, never acted on
    elif isinstance(event, NoOp):
        pass
```

In `atcdb/parsing.py`, replace:

```python
                          NoOp, ReadbackObserved, RunwayInstruction, RunwayVacated)
```

with:

```python
                          NoOp, ReadbackObserved, RunwayInstruction, RunwayVacated, Unresolved)
```

In `atcdb/parsing.py`, replace:

```python
                          ReadbackObserved: "READBACK", NoOp: "NOOP"}
```

with:

```python
                          ReadbackObserved: "READBACK", NoOp: "NOOP", Unresolved: "UNRESOLVED"}
```

In `atcdb/parsing.py`, replace:

```python
    extra = json.dumps({"to": e.to}) if isinstance(e, Handoff) else None
```

with:

```python
    extra = None
    if isinstance(e, Handoff):
        extra = json.dumps({"to": e.to})
    elif isinstance(e, Unresolved):
        extra = json.dumps({"raw": e.raw})
```

In `atcdb/parsing.py`, replace:

```python
    if cls is ReadbackObserved:
```

with:

```python
    if cls is Unresolved:
        return Unresolved(callsign=callsign, raw=extra.get("raw", ""), t=t, text=text)
    if cls is ReadbackObserved:
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest -q`
Expected: PASS — 185 passed.

- [ ] **Step 5: Commit**

```bash
git add atcdb/engine.py atcdb/parsing.py tests/test_engine.py tests/test_parsing.py tests/test_serialize.py
git commit -m "feat: Unresolved event counted by the engine, and ENGINE_VERSION"
```

---

### Task 2: ENGINE_VERSION in the cache key, and the get_events re-raise

Two cache fixes that must land before the first LLM parse is cached (spec A.4 carry-overs, A.7.2). A `window` parse sees the engine's state, so its cache rows are keyed by `ENGINE_VERSION` as well: `cache_version(model_version, mode)` appends `+engine<ENGINE_VERSION>` for `window` and leaves `none` and `role` alone. Bumping `ENGINE_VERSION` then turns every `window` row into a cache miss without touching the others. Separately, when the insert raises `IntegrityError` and the re-read finds nothing, the error did not come from a racing writer (a foreign-key failure, say); today `get_events` returns `[]` and the replay silently loses that transmission. It now re-raises.

**Files:**
- Modify: `atcdb/replay.py`, `scripts/parse_events.py` (`--refresh`)
- Test: `tests/test_replay.py`

**Interfaces:**
- Consumes: `engine.ENGINE_VERSION` (Task 1), read at call time through the module so a test can monkeypatch it.
- Produces: `replay.cache_version(model_version: str, mode: str) -> str`. `get_events` stores and reads `cache_version(model_version, ctx.mode)` in the `model_version` column. `Timeline.model_version` stays the plain parser version.

- [ ] **Step 1: Write the failing tests**

In `tests/test_replay.py`, replace:

```python
import pytest

from atcdb.engine import ClearToLand, Handoff, NoOp, ReadbackObserved, State, fold
from atcdb.parsing import Context
from atcdb.replay import (PARSER_MODELS, PARSERS, Step, Timeline, build_context, build_timeline, clear_events,
                          default_transcript_model, get_events, get_recording, list_recordings, load_recording,
                          transcript_models)
```

with:

```python
import sqlite3
from dataclasses import replace

import pytest

from atcdb import engine
from atcdb.engine import ClearToLand, Handoff, NoOp, ReadbackObserved, State, fold
from atcdb.parse_rules import VERSION
from atcdb.parsing import Context
from atcdb.replay import (PARSER_MODELS, PARSERS, Step, Timeline, build_context, build_timeline, cache_version, clear_events,
                          default_transcript_model, get_events, get_recording, list_recordings, load_recording,
                          transcript_models)
```

Append to `tests/test_replay.py`:

```python


def test_window_parses_are_keyed_by_the_engine_version(tmp_path, monkeypatch):
    conn = init_db(tmp_path / "t.sqlite")
    txs = load_recording(conn, _seed(conn, SEQUENCE[:1]))
    calls = []
    monkeypatch.setitem(PARSERS, "rule", _fake_parser({SEQUENCE[0][1]: [NoOp()]}, calls))
    window, role = Context(mode="window", role="controller"), Context(mode="role", role="controller")
    get_events(conn, txs[0], "rule", window)
    get_events(conn, txs[0], "rule", role)
    stored = sorted(r[0] for r in conn.execute("SELECT model_version FROM events"))
    assert stored == [VERSION, f"{VERSION}+engine{engine.ENGINE_VERSION}"]
    monkeypatch.setattr(engine, "ENGINE_VERSION", "test")
    assert (cache_version("v1", "window"), cache_version("v1", "role"), cache_version("v1", "none")) == ("v1+enginetest", "v1", "v1")
    get_events(conn, txs[0], "rule", window)   # a new engine: the window parse is a miss and is parsed again
    get_events(conn, txs[0], "rule", role)     # role parses never see engine state: still served from the cache
    assert len(calls) == 3


def test_get_events_re_raises_an_integrity_error_that_left_no_rows(tmp_path, monkeypatch):
    conn = init_db(tmp_path / "t.sqlite")
    txs = load_recording(conn, _seed(conn, SEQUENCE[:1]))
    monkeypatch.setitem(PARSERS, "rule", _fake_parser({SEQUENCE[0][1]: [NoOp()]}, []))
    orphan = replace(txs[0], transcript_id=999_999)   # no such transcript: the foreign key fails and nobody cached anything
    with pytest.raises(sqlite3.IntegrityError):
        get_events(conn, orphan, "rule", Context(mode="role", role="controller"))
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_replay.py -q`
Expected: FAIL — `ImportError: cannot import name 'cache_version'` (the module fails to collect).

- [ ] **Step 3: Write minimal implementation**

In `atcdb/replay.py`, replace:

```python
precompute script and the web API both go through it. `build_timeline` folds the cached/parsed events so
"state after transmission k" is available for every k, which is what the replay UI scrubs through.
Window-mode parses depend on engine state, so after changing engine rules run `scripts/parse_events.py
--refresh` (see `clear_events`).
"""
import sqlite3
from dataclasses import dataclass
from typing import Callable

from atcdb import parse_rules
```

with:

```python
precompute script and the web API both go through it. `build_timeline` folds the cached/parsed events so
"state after transmission k" is available for every k, which is what the replay UI scrubs through.
Window-mode parses depend on engine state, so their cache key carries `engine.ENGINE_VERSION` (see `cache_version`):
bump it after changing engine rules and the old window parses are simply never read again.
"""
import sqlite3
from dataclasses import dataclass
from typing import Callable

from atcdb import engine, parse_rules
```

In `atcdb/replay.py`, replace:

```python
def _cached_events(conn: sqlite3.Connection, tx: Transmission, parser: str, model: str, model_version: str,
                   mode: str) -> list[Event]:
    rows = conn.execute(
        """SELECT kind, callsign, runway, extra_json FROM events
           WHERE transcript_id = ? AND parser = ? AND model = ? AND model_version = ? AND context = ?
           ORDER BY seq""", (tx.transcript_id, parser, model, model_version, mode)).fetchall()
```

with:

```python
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
```

In `atcdb/replay.py`, replace:

```python
    so the cache never mixes rows from two different parses."""
```

with:

```python
    so the cache never mixes rows from two different parses. An `IntegrityError` that leaves no rows behind was not a
    race (a foreign-key failure, say) and is re-raised rather than returned as an empty parse."""
```

In `atcdb/replay.py`, replace:

```python
            [(tx.transcript_id, parser, model, model_version, ctx.mode, i, *event_to_row(e)) for i, e in enumerate(events)])
        conn.commit()
    except sqlite3.IntegrityError:
        conn.rollback()   # lost the race: nothing of ours is kept
        return _cached_events(conn, tx, parser, model, model_version, ctx.mode)
```

with:

```python
            [(tx.transcript_id, parser, model, cache_version(model_version, ctx.mode), ctx.mode, i, *event_to_row(e))
             for i, e in enumerate(events)])
        conn.commit()
    except sqlite3.IntegrityError:
        conn.rollback()   # lost the race: nothing of ours is kept
        winner = _cached_events(conn, tx, parser, model, model_version, ctx.mode)
        if not winner:
            raise
        return winner
```

In `scripts/parse_events.py`, replace:

```python
from atcdb.replay import PARSER_MODELS, PARSERS, build_timeline, clear_events, default_transcript_model, list_recordings  # noqa: E402
```

with:

```python
from atcdb.replay import (PARSER_MODELS, PARSERS, build_timeline, cache_version, clear_events,  # noqa: E402
                          default_transcript_model, list_recordings)
```

In `scripts/parse_events.py`, replace:

```python
        n = clear_events(conn, args.parser, model, version, args.context)
```

with:

```python
        n = clear_events(conn, args.parser, model, cache_version(version, args.context), args.context)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest -q`
Expected: PASS — 187 passed.

- [ ] **Step 5: Commit**

```bash
git add atcdb/replay.py scripts/parse_events.py tests/test_replay.py
git commit -m "feat: key window parses by ENGINE_VERSION; re-raise an IntegrityError that left no rows"
```

---

### Task 3: Per-recording transcript pinning

Today a replay that names no transcript model pins one model for the whole database: `human` for gold. Phase 3b's conflict injection writes recordings whose gold transcripts all come from a `synthetic` model, and those would replay empty. The default is now chosen per recording, from the models that recording actually has, with the same preference order (`human` for gold, else the alphabetically first). The database-wide form stays for callers that pass no recording.

**Files:**
- Modify: `atcdb/replay.py` (`default_transcript_model`), `atcdb/api.py` (replay route), `scripts/parse_events.py`, `scripts/show_replay.py`
- Test: `tests/test_replay.py`, `tests/test_api.py`

**Interfaces:**
- Produces: `default_transcript_model(conn, transcript_kind, recording_id: int | None = None) -> str | None`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_replay.py`:

```python


def test_the_pinned_transcript_model_is_chosen_per_recording(tmp_path):
    conn = init_db(tmp_path / "t.sqlite")
    human = _seed(conn, SEQUENCE[:1], external_id="human")
    synthetic = _seed(conn, SEQUENCE[:1], external_id="synthetic")
    conn.execute("UPDATE transcripts SET model = 'synthetic' WHERE transmission_id IN "
                 "(SELECT id FROM transmissions WHERE recording_id = ?)", (synthetic,))
    assert default_transcript_model(conn, "gold") == "human"                 # database-wide, as before
    assert default_transcript_model(conn, "gold", human) == "human"
    assert default_transcript_model(conn, "gold", synthetic) == "synthetic"  # conflict injection's recordings replay
    assert default_transcript_model(conn, "asr", synthetic) is None
```

In `tests/test_api.py`, replace:

```python
def test_replay_with_an_explicit_transcript_model_or_asr(client):
```

with:

```python
def test_replay_pins_the_transcript_model_per_recording(client, tmp_path):
    conn = init_db(tmp_path / "t.sqlite")
    conn.execute("INSERT INTO recordings (id, source_id, external_id, facility) VALUES (12, 1, 'rec-synthetic', 'Tower')")
    conn.execute("INSERT INTO transmissions (id, recording_id, external_id, start_s, speaker_role) "
                 "VALUES (120, 12, 's0', 0.0, 'controller')")
    _transcript(conn, 120, "gold", "synthetic", "csa one two three runway three one cleared to land")
    conn.commit()
    conn.close()
    d = client.get("/api/recordings/12/replay").json()
    assert d["transcript_model"] == "synthetic" and [e["kind"] for s in d["steps"] for e in s["events"]] == ["LAND"]
    assert client.get("/api/recordings/10/replay").json()["transcript_model"] == "human"


def test_replay_with_an_explicit_transcript_model_or_asr(client):
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_replay.py tests/test_api.py -q`
Expected: FAIL — 2 failed: `test_the_pinned_transcript_model_is_chosen_per_recording` (`TypeError: default_transcript_model() takes 2 positional arguments but 3 were given`) and `test_replay_pins_the_transcript_model_per_recording` (the replay pins `human` and returns no steps).

- [ ] **Step 3: Write minimal implementation**

In `atcdb/replay.py`, replace:

```python
def default_transcript_model(conn: sqlite3.Connection, transcript_kind: str) -> str | None:
    """The transcript model a replay pins when none is given, so cache keys do not drift between runs: `human` for
    gold (some transmissions also carry an `atco2-xml` gold transcript), otherwise the alphabetically first model.
    None when the DB has no transcripts of that kind."""
    models = transcript_models(conn).get(transcript_kind, [])
```

with:

```python
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
```

In `atcdb/api.py`, replace:

```python
            model = transcript_model or default_transcript_model(conn, transcript)
```

with:

```python
            model = transcript_model or default_transcript_model(conn, transcript, recording_id)
```

In `scripts/parse_events.py`, replace:

```python
    transcript_model = default_transcript_model(conn, args.transcript)
    if args.limit:
        recordings = recordings[:args.limit]
    kinds, conflicts, errors, n_steps = Counter(), Counter(), 0, 0
    for i, rec in enumerate(recordings, 1):
        tl = build_timeline(conn, rec["id"], parser=args.parser, transcript_kind=args.transcript, context=args.context, transcript_model=transcript_model)
```

with:

```python
    if args.limit:
        recordings = recordings[:args.limit]
    kinds, conflicts, errors, n_steps = Counter(), Counter(), 0, 0
    for i, rec in enumerate(recordings, 1):
        tl = build_timeline(conn, rec["id"], parser=args.parser, transcript_kind=args.transcript, context=args.context,
                            transcript_model=default_transcript_model(conn, args.transcript, rec["id"]))
```

In `scripts/show_replay.py`, replace:

```python
                       transcript_model=default_transcript_model(conn, args.transcript))
```

with:

```python
                       transcript_model=default_transcript_model(conn, args.transcript, row["id"]))
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest -q`
Expected: PASS — 189 passed.

- [ ] **Step 5: Commit**

```bash
git add atcdb/replay.py atcdb/api.py scripts/parse_events.py scripts/show_replay.py tests/test_replay.py tests/test_api.py
git commit -m "feat: pin the default transcript model per recording"
```

---

### Task 4: The Claude parser module

`atcdb/parse_llm.py` holds everything about one Claude parse: the strict `report_events` tool (its `kind` enumerates the ten event kinds and `to` the handoff targets), a short ATC system prompt, the user message for each context mode, the per-model request settings, and the mapping from the tool input to engine events. `make_parser(model, client=None)` returns a `Parser`; with no client injected it creates the Anthropic client on the first call, so importing the module never imports `anthropic`. A refusal, a truncated response or a response without the tool call raises `ParseError`; an API error propagates as the SDK raised it. Either way `get_events` caches nothing and the next replay retries.

**Files:**
- Create: `atcdb/parse_llm.py`, `tests/test_parse_llm.py`
- Modify: `requirements.txt`

**Interfaces:**
- Consumes: `engine.Unresolved` (Task 1), `engine.normalize_runway`, `engine.HANDOFF_TARGETS`, `parsing.Context`, `parsing.Transmission`.
- Produces: `parse_llm.VERSION = "p1"`; `parse_llm.MODELS = ("claude-haiku-4-5", "claude-sonnet-5")`; `EVENT_KINDS` (the ten tool kinds); `SYSTEM`; `TOOL`; `render_prompt(tx, ctx) -> str`; `request(model, tx, ctx) -> dict` (keyword arguments for `messages.create`); `to_events(items, tx) -> list[Event]`; `events_from_response(response, tx) -> list[Event]`; `class ParseError(RuntimeError)`; `make_parser(model, client=None) -> Parser`; `availability() -> tuple[bool, str | None]`.

- [ ] **Step 1: Install the SDK**

In `requirements.txt`, replace:

```text
ctranslate2==4.8.1
```

with:

```text
anthropic==1.8.0
ctranslate2==4.8.1
```

Run: `.venv/bin/pip install -q -r requirements.txt`
Expected: PASS — installs `anthropic` 1.8.0; `httpx2` stays at 2.13.0.

- [ ] **Step 2: Write the failing tests**

Create `tests/test_parse_llm.py`:

```python
import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from atcdb import parse_llm
from atcdb.engine import (HANDOFF_TARGETS, ClearToCross, ClearToLand, GoAround, Handoff, HoldShort, ReadbackObserved,
                          RunwayVacated, Unresolved)
from atcdb.parse_llm import EVENT_KINDS, MODELS, SYSTEM, TOOL, ParseError, make_parser, render_prompt, request, to_events
from atcdb.parsing import Context, Transmission

ROOT = Path(__file__).resolve().parents[1]
TX = Transmission(id=1, transcript_id=10, text="csa one two three runway three one cleared to land", role="controller",
                  start_s=42.0)
ROLE = Context(mode="role", role="controller")


class FakeMessages:
    """Stands in for `client.messages`: records each call's keyword arguments and returns (or raises) the next reply."""

    def __init__(self, replies):
        self.replies, self.calls = list(replies), []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply


class FakeClient:
    def __init__(self, *replies):
        self.messages = FakeMessages(replies)


def reply(events, stop_reason="tool_use"):
    """A response shaped like the SDK's Message: one report_events tool_use block."""
    return SimpleNamespace(stop_reason=stop_reason,
                           content=[SimpleNamespace(type="tool_use", name="report_events", input={"events": events})])


def item(kind, callsign="csa one two three", runway=None, to=None):
    return {"kind": kind, "callsign": callsign, "runway": runway, "to": to}


def test_the_tool_is_strict_and_mirrors_the_engine_events():
    assert TOOL["name"] == "report_events" and TOOL["strict"] is True
    schema = TOOL["input_schema"]
    assert (schema["required"], schema["additionalProperties"]) == (["events"], False)
    ev = schema["properties"]["events"]["items"]
    assert ev["required"] == ["kind", "callsign", "runway", "to"] and ev["additionalProperties"] is False
    assert tuple(ev["properties"]["kind"]["enum"]) == EVENT_KINDS
    assert EVENT_KINDS == ("LAND", "TAKEOFF", "LUAW", "CROSS", "HOLD_SHORT", "VACATED", "GO_AROUND", "HANDOFF", "READBACK", "NOOP")
    to_choices = ev["properties"]["to"]["anyOf"]
    assert tuple(to_choices[0]["enum"]) == HANDOFF_TARGETS and to_choices[1] == {"type": "null"}


def test_render_prompt_shows_only_what_the_context_mode_allows():
    assert render_prompt(TX, Context(mode="none")) == f"Transmission: {TX.text}"
    assert render_prompt(TX, ROLE) == f"Speaker: controller\nTransmission: {TX.text}"
    window = Context(mode="window", role="controller", history=(("pilot", "csa one two three with you"),),
                     active_callsigns=("lufthansa four five six",), active_runways=("31",))
    assert render_prompt(TX, window) == (
        "Previous transmissions, oldest first:\n"
        "  [pilot] csa one two three with you\n"
        "Aircraft being tracked: lufthansa four five six\n"
        "Runways with active clearances: 31\n"
        "Speaker: controller\n"
        f"Transmission: {TX.text}")
    empty = render_prompt(TX, Context(mode="window", role="pilot"))
    assert "Aircraft being tracked: none\nRunways with active clearances: none" in empty and "Previous" not in empty


def test_request_settings_per_model():
    haiku, sonnet = request("claude-haiku-4-5", TX, ROLE), request("claude-sonnet-5", TX, ROLE)
    for r in (haiku, sonnet):
        assert r["system"] == SYSTEM and r["tools"] == [TOOL]
        assert r["tool_choice"] == {"type": "tool", "name": "report_events"}
        assert r["messages"] == [{"role": "user", "content": render_prompt(TX, ROLE)}]
        assert "temperature" not in r   # anthropic 1.x has no temperature parameter
    assert haiku["model"] == "claude-haiku-4-5" and haiku["extra_body"] == {"temperature": 0}
    assert "thinking" not in haiku and "output_config" not in haiku
    assert sonnet["model"] == "claude-sonnet-5" and "extra_body" not in sonnet   # Sonnet 5 rejects temperature
    assert (sonnet["thinking"], sonnet["output_config"]) == ({"type": "disabled"}, {"effort": "low"})
    assert MODELS == ("claude-haiku-4-5", "claude-sonnet-5")


def test_every_kind_maps_to_its_engine_event():
    items = [item("LAND", runway="31"), item("CROSS", callsign="Lufthansa  Four five six", runway="three one"),
             item("HOLD_SHORT", runway="04L"), item("HANDOFF", to="ground"), item("READBACK"), item("VACATED"),
             item("GO_AROUND"), item("NOOP", callsign="")]
    common = {"callsign": "csa one two three", "t": 42.0, "text": TX.text}
    assert to_events(items, TX) == [
        ClearToLand(runway="31", **common),
        ClearToCross(runway="31", callsign="lufthansa four five six", t=42.0, text=TX.text),   # callsign normalised
        HoldShort(runway="04L", **common), Handoff(to="ground", **common),
        ReadbackObserved(callsign="csa one two three", text=TX.text, t=42.0),
        RunwayVacated(**common), GoAround(**common)]                                         # NOOP adds nothing


def test_events_that_cannot_be_placed_become_unresolved():
    bad = [item("LAND", runway="three seven"), item("TAKEOFF"), item("HANDOFF")]
    out = to_events(bad, TX)
    assert [type(e) for e in out] == [Unresolved] * 3
    assert [json.loads(e.raw) for e in out] == bad
    assert (out[0].callsign, out[0].t, out[0].text) == ("csa one two three", 42.0, TX.text)


def test_the_parser_sends_one_request_and_maps_the_reply():
    client = FakeClient(reply([item("LAND", runway="31")]))
    parse = make_parser("claude-sonnet-5", client)
    assert parse(TX, ROLE) == [ClearToLand(callsign="csa one two three", runway="31", t=42.0, text=TX.text)]
    assert client.messages.calls == [request("claude-sonnet-5", TX, ROLE)]
    assert make_parser("claude-haiku-4-5", FakeClient(reply([])))(TX, ROLE) == []   # get_events stores the NOOP row


@pytest.mark.parametrize("response,message", [
    (SimpleNamespace(stop_reason="refusal", content=[]), "refused"),
    (reply([item("LAND", runway="31")], stop_reason="max_tokens"), "max_tokens"),
    (SimpleNamespace(stop_reason="end_turn", content=[SimpleNamespace(type="text", text="no events")]), "no report_events"),
])
def test_unusable_replies_raise_parse_error(response, message):
    with pytest.raises(ParseError, match=message):
        make_parser("claude-haiku-4-5", FakeClient(response))(TX, ROLE)


def test_an_api_error_propagates_unchanged():
    boom = RuntimeError("529 overloaded")
    with pytest.raises(RuntimeError) as raised:
        make_parser("claude-haiku-4-5", FakeClient(boom))(TX, ROLE)
    assert raised.value is boom


def test_make_parser_rejects_an_unknown_model():
    with pytest.raises(ValueError, match="unknown Claude model"):
        make_parser("claude-opus-5")


def test_availability_reports_why_a_cold_parse_cannot_run(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    assert parse_llm.availability() == (True, None)
    monkeypatch.delenv("ANTHROPIC_API_KEY")
    assert parse_llm.availability() == (False, "ANTHROPIC_API_KEY not set")
    monkeypatch.setitem(sys.modules, "anthropic", None)   # makes `import anthropic` raise ImportError
    assert parse_llm.availability() == (False, "anthropic not installed")


def test_importing_the_parser_does_not_import_the_sdk():
    code = "import sys, atcdb.parse_llm; print('anthropic' in sys.modules)"
    out = subprocess.run([sys.executable, "-c", code], cwd=ROOT, capture_output=True, text=True, check=True)
    assert out.stdout.strip() == "False"
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_parse_llm.py -q`
Expected: FAIL — `ImportError: cannot import name 'parse_llm' from 'atcdb'` (the module fails to collect).

- [ ] **Step 4: Write the implementation**

Create `atcdb/parse_llm.py`:

```python
"""Claude parser (spec Section 2, amended by addendum A.4): one forced `report_events` tool call per transmission.

The tool mirrors the engine's events one to one. `make_parser(model)` returns a `Parser` for the registry in
`atcdb/replay.py`. The Anthropic client is created on the first call that needs one, so importing this module never
imports `anthropic` and a replay served from the events cache never touches the API. API errors propagate as the SDK
raised them, and a refusal, a truncated reply or a reply without the tool call raises `ParseError`; `get_events` caches
nothing for either, so the next replay retries. A reported event that cannot become an engine event (a runway that does
not normalise, a runway instruction without a runway, a handoff without a target) becomes `Unresolved`, which the engine
counts as dropped.

Bump VERSION by hand whenever SYSTEM, TOOL, `render_prompt` or the request settings change: it is part of the cache key.
"""
import functools
import json
import os
from typing import Any

from atcdb.engine import (HANDOFF_TARGETS, ClearTakeoff, ClearToCross, ClearToLand, Event, GoAround, Handoff, HoldShort,
                          LineUpAndWait, ReadbackObserved, RunwayVacated, Unresolved, normalize_runway)
from atcdb.parsing import Context, Parser, Transmission

VERSION = "p1"
MODELS = ("claude-haiku-4-5", "claude-sonnet-5")   # the cheap and the strong arm (spec addendum A.4)

# Both models do one-shot extraction with thinking off. anthropic 1.x has no `temperature` parameter, so Haiku's goes in
# extra_body; Sonnet 5 rejects temperature altogether and runs with thinking disabled at low effort instead.
MODEL_SETTINGS: dict[str, dict[str, Any]] = {
    "claude-haiku-4-5": {"extra_body": {"temperature": 0}},
    "claude-sonnet-5": {"thinking": {"type": "disabled"}, "output_config": {"effort": "low"}},
}
MAX_TOKENS = 1024   # a transmission yields a handful of events; a truncated reply raises ParseError

_RUNWAY_EVENTS = {"LAND": ClearToLand, "TAKEOFF": ClearTakeoff, "LUAW": LineUpAndWait, "CROSS": ClearToCross,
                  "HOLD_SHORT": HoldShort}
EVENT_KINDS = (*_RUNWAY_EVENTS, "VACATED", "GO_AROUND", "HANDOFF", "READBACK", "NOOP")

SYSTEM = """You read one radio transmission from an airport tower frequency and report its runway events with the \
report_events tool, in the order they are spoken. Report an empty list when there are none.

Event kinds:
- LAND, TAKEOFF, LUAW (line up and wait), CROSS (cross a runway), HOLD_SHORT: a controller's instruction to an \
aircraft about a runway. Give the runway.
- HANDOFF: the controller tells an aircraft to contact another frequency. Give `to`: ground, departure, tower or \
approach.
- READBACK: a pilot repeating an instruction back to the controller. Report one READBACK for the pilot's transmission, \
never the instructions it repeats: pilots do not issue instructions.
- VACATED: a pilot reporting that it has left the runway.
- GO_AROUND: an instruction to go around, or a pilot reporting one.
- NOOP: nothing relevant. You may leave it out.

Fields:
- callsign: the aircraft's callsign in the transcript's own words, lower case, for example "csa one two three". Use \
the same words for the same aircraft every time; the tracked aircraft, when shown, are the forms already in use. Use \
an empty string when no callsign is said.
- runway: the designator in digits with an optional L, R or C, for example "31" or "04L", or null. When an \
instruction names no runway and exactly one runway has an active clearance, use that runway.
- to: only for HANDOFF; otherwise null.

Report only what the transmission says."""

TOOL: dict[str, Any] = {
    "name": "report_events",
    "description": "Report every runway event in the transmission, in spoken order. An empty list means none.",
    "strict": True,
    "input_schema": {
        "type": "object",
        "properties": {"events": {"type": "array", "items": {
            "type": "object",
            "properties": {
                "kind": {"type": "string", "enum": list(EVENT_KINDS)},
                "callsign": {"type": "string", "description": "lower-case words as spoken; empty if none"},
                "runway": {"anyOf": [{"type": "string"}, {"type": "null"}],
                           "description": "digits plus optional L/R/C, e.g. 31 or 04L; null if none"},
                "to": {"anyOf": [{"type": "string", "enum": list(HANDOFF_TARGETS)}, {"type": "null"}],
                       "description": "the frequency handed to; HANDOFF only"},
            },
            "required": ["kind", "callsign", "runway", "to"],
            "additionalProperties": False,
        }}},
        "required": ["events"],
        "additionalProperties": False,
    },
}


class ParseError(RuntimeError):
    """The model answered, but not with a usable report_events call: a refusal, a truncated reply, or no call at all."""


def render_prompt(tx: Transmission, ctx: Context) -> str:
    """The user message: the transmission, plus what the context mode allows (spec Section 2)."""
    lines = []
    if ctx.mode == "window":
        if ctx.history:
            lines.append("Previous transmissions, oldest first:")
            lines += [f"  [{role}] {text}" for role, text in ctx.history]
        lines.append("Aircraft being tracked: " + (", ".join(ctx.active_callsigns) or "none"))
        lines.append("Runways with active clearances: " + (", ".join(ctx.active_runways) or "none"))
    if ctx.mode != "none":
        lines.append(f"Speaker: {ctx.role}")
    lines.append(f"Transmission: {tx.text}")
    return "\n".join(lines)


def request(model: str, tx: Transmission, ctx: Context) -> dict[str, Any]:
    """Keyword arguments for `client.messages.create` for one transmission."""
    return {"model": model, "max_tokens": MAX_TOKENS, "system": SYSTEM, "tools": [TOOL],
            "tool_choice": {"type": "tool", "name": TOOL["name"]},
            "messages": [{"role": "user", "content": render_prompt(tx, ctx)}], **MODEL_SETTINGS[model]}


def to_events(items: list[dict], tx: Transmission) -> list[Event]:
    """The tool's event list as engine events. NOOP adds nothing; an item that cannot be placed becomes Unresolved."""
    events: list[Event] = []
    for it in items:
        kind = it.get("kind")
        common = {"callsign": " ".join((it.get("callsign") or "").lower().split()), "t": tx.start_s, "text": tx.text}
        event: Event | None = None
        if kind in _RUNWAY_EVENTS:
            runway = normalize_runway(it.get("runway") or "")
            event = _RUNWAY_EVENTS[kind](runway=runway, **common) if runway else None
        elif kind == "HANDOFF":
            event = Handoff(to=it["to"], **common) if it.get("to") in HANDOFF_TARGETS else None
        elif kind == "READBACK":
            event = ReadbackObserved(callsign=common["callsign"], text=tx.text, t=tx.start_s)
        elif kind == "VACATED":
            event = RunwayVacated(**common)
        elif kind == "GO_AROUND":
            event = GoAround(**common)
        elif kind == "NOOP":
            continue
        events.append(event or Unresolved(raw=json.dumps(it, sort_keys=True), **common))
    return events


def events_from_response(response: Any, tx: Transmission) -> list[Event]:
    """Map a Messages API response to events, or raise ParseError when it holds no usable report_events call."""
    if response.stop_reason == "refusal":
        raise ParseError("the model refused this transmission")
    if response.stop_reason == "max_tokens":
        raise ParseError(f"reply truncated at max_tokens={MAX_TOKENS}")
    call = next((b for b in response.content if b.type == "tool_use" and b.name == TOOL["name"]), None)
    if call is None:
        raise ParseError("no report_events call in the reply")
    return to_events(call.input["events"], tx)


@functools.cache
def _default_client() -> Any:
    import anthropic   # deferred: importing this module, or replaying from the cache, never needs the SDK
    return anthropic.Anthropic()


def make_parser(model: str, client: Any = None) -> Parser:
    """A Parser that asks `model` for one transmission's events. Tests inject `client`; otherwise the default Anthropic
    client is created on the first call."""
    if model not in MODELS:
        raise ValueError(f"unknown Claude model {model!r}; expected one of {MODELS}")

    def parse(tx: Transmission, ctx: Context) -> list[Event]:
        response = (client or _default_client()).messages.create(**request(model, tx, ctx))
        return events_from_response(response, tx)

    return parse


def availability() -> tuple[bool, str | None]:
    """Whether a cold Claude parse can run here, and if not, why (spec addendum A.4, capabilities)."""
    try:
        import anthropic  # noqa: F401
    except ImportError:
        return False, "anthropic not installed"
    if not os.environ.get("ANTHROPIC_API_KEY"):
        return False, "ANTHROPIC_API_KEY not set"
    return True, None
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest -q`
Expected: PASS — 202 passed.

- [ ] **Step 6: Commit**

```bash
git add requirements.txt atcdb/parse_llm.py tests/test_parse_llm.py
git commit -m "feat: Claude parser module with a strict report_events tool"
```

---

### Task 5: Parser registry, lazy resolution and the API

The registry now knows parsers by name and models by parser (spec A.4): `PARSER_MODELS: dict[str, list[str]]` (the first model is the default), `PARSER_VERSIONS` for the cache key, and `PARSERS`, which maps a parser name to a *factory* taking the model id. `get_events` calls the factory only on a cache miss, so the Claude client is created the first time a transmission actually needs parsing, and a replay served from the cache needs neither `anthropic` nor a key. `PARSER_AVAILABILITY` says whether each parser can run a cold parse here. The capabilities route lists one entry per parser-model pair with `available` and `reason`; the replay route takes a validated `model`, and an unknown parser-model pair is a 422 (today an unknown query parameter is silently ignored).

**Files:**
- Modify: `atcdb/replay.py`, `atcdb/api.py`, `scripts/parse_events.py` (`--refresh` reads the new registry)
- Test: `tests/test_replay.py`, `tests/test_api.py`

**Interfaces:**
- Consumes: `parse_llm.make_parser`, `parse_llm.MODELS`, `parse_llm.VERSION`, `parse_llm.availability` (Task 4); `cache_version` (Task 2).
- Produces: `replay.PARSERS: dict[str, Callable[[str], Parser]]` (`"rule"`, `"llm"`); `replay.PARSER_MODELS: dict[str, list[str]]` = `{"rule": ["rules"], "llm": ["claude-haiku-4-5", "claude-sonnet-5"]}`; `replay.PARSER_VERSIONS: dict[str, str]` = `{"rule": "v1", "llm": "p1"}`; `replay.PARSER_AVAILABILITY: dict[str, Callable[[], tuple[bool, str | None]]]`. `get_events` and `build_timeline` default `model` to `PARSER_MODELS[parser][0]` and `model_version` to `PARSER_VERSIONS[parser]`. `GET /api/capabilities` parsers entries are `{"name", "model", "model_version", "available", "reason"}`; `GET /api/recordings/{id}/replay` takes `model`.

- [ ] **Step 1: Write the failing tests**

In `tests/test_replay.py`, replace:

```python
from atcdb.engine import ClearToLand, Handoff, NoOp, ReadbackObserved, State, fold
from atcdb.parse_rules import VERSION
from atcdb.parsing import Context
from atcdb.replay import (PARSER_MODELS, PARSERS, Step, Timeline, build_context, build_timeline, cache_version, clear_events,
                          default_transcript_model, get_events, get_recording, list_recordings, load_recording,
                          transcript_models)
```

with:

```python
from atcdb.engine import ClearToLand, Handoff, NoOp, ReadbackObserved, State, Unresolved, fold
from atcdb.parse_rules import VERSION
from atcdb.parsing import Context
from atcdb.replay import (PARSER_AVAILABILITY, PARSER_MODELS, PARSER_VERSIONS, PARSERS, Step, Timeline, build_context,
                          build_timeline, cache_version, clear_events, default_transcript_model, get_events, get_recording,
                          list_recordings, load_recording, transcript_models)
```

In `tests/test_replay.py`, replace:

```python
        return out
    return parse
```

with:

```python
        return out
    return lambda model: parse   # PARSERS maps a parser name to a factory taking the model id
```

In `tests/test_replay.py`, replace:

```python
    monkeypatch.setitem(PARSER_MODELS, "rule", ("fake", "v0"))
```

with:

```python
    monkeypatch.setitem(PARSER_MODELS, "rule", ["fake"])
    monkeypatch.setitem(PARSER_VERSIONS, "rule", "v0")
```

In `tests/test_replay.py`, replace:

```python
                     "VALUES (?, 'rule', 'rules', ?, 'role', 0, 'LAND', 'csa one two three', '31')", (tx.transcript_id, PARSER_MODELS["rule"][1]))
        conn.commit()
        return [ClearToLand(callsign="csa one two three", runway="31")]

    monkeypatch.setitem(PARSERS, "rule", racing_parser)
```

with:

```python
                     "VALUES (?, 'rule', 'rules', ?, 'role', 0, 'LAND', 'csa one two three', '31')", (tx.transcript_id, VERSION))
        conn.commit()
        return [ClearToLand(callsign="csa one two three", runway="31")]

    monkeypatch.setitem(PARSERS, "rule", lambda model: racing_parser)
```

In `tests/test_replay.py`, replace:

```python
                     "VALUES (?, 'rule', 'rules', ?, 'role', 0, 'NOOP')", (tx.transcript_id, PARSER_MODELS["rule"][1]))
        conn.commit()
        return [ClearToLand(callsign="csa one two three", runway="31"), ReadbackObserved(callsign="csa one two three", text="x")]

    monkeypatch.setitem(PARSERS, "rule", racing_parser)
```

with:

```python
                     "VALUES (?, 'rule', 'rules', ?, 'role', 0, 'NOOP')", (tx.transcript_id, VERSION))
        conn.commit()
        return [ClearToLand(callsign="csa one two three", runway="31"), ReadbackObserved(callsign="csa one two three", text="x")]

    monkeypatch.setitem(PARSERS, "rule", lambda model: racing_parser)
```

Append to `tests/test_replay.py`:

```python


def test_the_registry_knows_both_parsers_and_their_models():
    assert PARSER_MODELS == {"rule": ["rules"], "llm": ["claude-haiku-4-5", "claude-sonnet-5"]}
    assert PARSER_VERSIONS == {"rule": VERSION, "llm": "p1"}
    assert set(PARSERS) == set(PARSER_AVAILABILITY) == set(PARSER_MODELS)
    assert PARSER_AVAILABILITY["rule"]() == (True, None)


def test_llm_replays_resolve_the_model_only_on_a_miss_and_cache_unresolved_events(tmp_path, monkeypatch):
    conn = init_db(tmp_path / "t.sqlite")
    rid = _seed(conn, SEQUENCE[:2])
    made, calls = [], []
    table = {SEQUENCE[0][1]: [ClearToLand(callsign="csa one two three", runway="31"), Unresolved(callsign="csa one two three", raw="x")],
             SEQUENCE[1][1]: [ReadbackObserved(callsign="csa one two three", text=SEQUENCE[1][1])]}

    def factory(model):
        made.append(model)
        return _fake_parser(table, calls)(model)

    monkeypatch.setitem(PARSERS, "llm", factory)
    tl = build_timeline(conn, rid, parser="llm", model="claude-sonnet-5")
    assert (tl.parser, tl.model, tl.model_version) == ("llm", "claude-sonnet-5", "p1")
    assert made == ["claude-sonnet-5"] * 2 and len(calls) == 2
    assert [s.dropped for s in tl.steps] == [1, 0]
    again = build_timeline(conn, rid, parser="llm", model="claude-sonnet-5")   # all cached: no parser is even created
    assert len(made) == 2 and [s.dropped for s in again.steps] == [1, 0]
    assert [tuple(r) for r in conn.execute("SELECT DISTINCT parser, model, model_version FROM events")] == \
        [("llm", "claude-sonnet-5", f"p1+engine{engine.ENGINE_VERSION}")]
    assert build_timeline(conn, rid, parser="llm").model == "claude-haiku-4-5"   # the first model is the default
```

In `tests/test_api.py`, replace:

```python
import numpy as np
import pytest
import soundfile as sf
from fastapi.testclient import TestClient

from atcdb.api import create_app
from atcdb.parse_rules import VERSION
from atcdb.schema import init_db
```

with:

```python
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest
import soundfile as sf
from fastapi.testclient import TestClient

from atcdb.api import create_app
from atcdb.engine import ClearToLand
from atcdb.parse_rules import VERSION
from atcdb.replay import PARSERS
from atcdb.schema import init_db
```

In `tests/test_api.py`, replace:

```python
def test_capabilities(client):
    assert client.get("/api/capabilities").json() == {
        "parsers": [{"name": "rule", "model": "rules", "model_version": VERSION}],
```

with:

```python
def test_capabilities(client, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    unavailable = {"model_version": "p1", "available": False, "reason": "ANTHROPIC_API_KEY not set"}
    assert client.get("/api/capabilities").json() == {
        "parsers": [{"name": "llm", "model": "claude-haiku-4-5", **unavailable},
                    {"name": "llm", "model": "claude-sonnet-5", **unavailable},
                    {"name": "rule", "model": "rules", "model_version": VERSION, "available": True, "reason": None}],
```

In `tests/test_api.py`, replace:

```python
    for params in ({"parser": "magic"}, {"context": "everything"}, {"transcript": "llm"}):
```

with:

```python
    for params in ({"parser": "magic"}, {"context": "everything"}, {"transcript": "llm"}, {"model": "claude-sonnet-5"},
                   {"parser": "llm", "model": "claude-opus-5"}, {"parser": "llm", "model": "rules"}):
```

Append to `tests/test_api.py`:

```python


def test_replay_with_the_llm_parser_and_a_model(client, monkeypatch):
    seen = []

    def factory(model):
        seen.append(model)
        return lambda tx, ctx: [ClearToLand(callsign="csa one two three", runway="31")] if tx.role == "controller" else []

    monkeypatch.setitem(PARSERS, "llm", factory)
    d = client.get("/api/recordings/10/replay", params={"parser": "llm", "model": "claude-sonnet-5", "context": "role"}).json()
    assert (d["parser"], d["model"], d["model_version"]) == ("llm", "claude-sonnet-5", "p1")
    assert set(seen) == {"claude-sonnet-5"} and len(d["steps"]) == 4
    assert client.get("/api/recordings/10/replay", params={"parser": "llm", "context": "role"}).json()["model"] == "claude-haiku-4-5"


def test_importing_the_app_does_not_import_the_sdk():
    code = "import sys, atcdb.api; print('anthropic' in sys.modules)"
    root = Path(__file__).resolve().parents[1]
    out = subprocess.run([sys.executable, "-c", code], cwd=root, capture_output=True, text=True, check=True)
    assert out.stdout.strip() == "False"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_replay.py tests/test_api.py -q`
Expected: FAIL — `ImportError: cannot import name 'PARSER_AVAILABILITY'`: `tests/test_replay.py` fails to collect, which stops the run. (Run `tests/test_api.py` alone and `test_capabilities`, `test_replay_errors` and `test_replay_with_the_llm_parser_and_a_model` fail.)

- [ ] **Step 3: Write minimal implementation**

In `atcdb/replay.py`, replace:

```python
from atcdb import engine, parse_rules
from atcdb.engine import Conflict, Event, NoOp, State, apply
from atcdb.parsing import CONTEXT_MODES, WINDOW, Context, Parser, Transmission, event_to_row, row_to_event

PARSERS: dict[str, Parser] = {"rule": parse_rules.parse}
PARSER_MODELS: dict[str, tuple[str, str]] = {"rule": ("rules", parse_rules.VERSION)}   # parser -> (model, model_version)
```

with:

```python
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
```

In `atcdb/replay.py`, replace:

```python
    if model is None:
        model, model_version = PARSER_MODELS[parser]
    model_version = model_version or ""
    cached = _cached_events(conn, tx, parser, model, model_version, ctx.mode)
    if cached:
        return cached
    events = PARSERS[parser](tx, ctx) or [NoOp(t=tx.start_s, text=tx.text)]
```

with:

```python
    model = model or PARSER_MODELS[parser][0]
    model_version = PARSER_VERSIONS[parser] if model_version is None else model_version
    cached = _cached_events(conn, tx, parser, model, model_version, ctx.mode)
    if cached:
        return cached
    events = PARSERS[parser](model)(tx, ctx) or [NoOp(t=tx.start_s, text=tx.text)]
```

In `atcdb/replay.py`, replace:

```python
    """Fold a whole recording: one Step per transmission with its events, the conflicts they raised and the state after."""
    if model is None:
        model, model_version = PARSER_MODELS[parser]
```

with:

```python
    """Fold a whole recording: one Step per transmission with its events, the conflicts they raised and the state after."""
    model = model or PARSER_MODELS[parser][0]
    model_version = PARSER_VERSIONS[parser] if model_version is None else model_version
```

In `atcdb/replay.py`, replace:

```python
    return Timeline(recording_id, parser, model, model_version or "", context, transcript_kind, tuple(steps))
```

with:

```python
    return Timeline(recording_id, parser, model, model_version, context, transcript_kind, tuple(steps))
```

In `atcdb/api.py`, replace:

```python
from atcdb.replay import (PARSER_MODELS, PARSERS, build_timeline, default_transcript_model, get_recording,
                          list_recordings, transcript_models)
```

with:

```python
from atcdb.replay import (PARSER_AVAILABILITY, PARSER_MODELS, PARSER_VERSIONS, build_timeline, default_transcript_model,
                          get_recording, list_recordings, transcript_models)
```

In `atcdb/api.py`, replace:

```python
        with db() as conn:
            models = transcript_models(conn)
        return {"parsers": [{"name": p, "model": m, "model_version": v} for p, (m, v) in sorted(PARSER_MODELS.items())],
```

with:

```python
        with db() as conn:
            models = transcript_models(conn)
        parsers = []
        for name in sorted(PARSER_MODELS):
            available, reason = PARSER_AVAILABILITY[name]()   # whether a cold parse can run; cached replays always can
            parsers += [{"name": name, "model": m, "model_version": PARSER_VERSIONS[name], "available": available,
                         "reason": reason} for m in PARSER_MODELS[name]]
        return {"parsers": parsers,
```

In `atcdb/api.py`, replace:

```python
    def replay(recording_id: int, parser: str = "rule", context: str = "window", transcript: str = "gold",
               transcript_model: str | None = None):
        _require("parser", parser, PARSERS)
        _require("context mode", context, CONTEXT_MODES)
        _require("transcript kind", transcript, TRANSCRIPT_KINDS)
        with db() as conn:
            recording = get_recording(conn, recording_id)
            if recording is None:
                raise HTTPException(404, f"no recording {recording_id}")
            model = transcript_model or default_transcript_model(conn, transcript, recording_id)
            tl = build_timeline(conn, recording_id, parser=parser, transcript_kind=transcript, context=context,
                                transcript_model=model)
        return timeline_dict(tl, recording, model)
```

with:

```python
    def replay(recording_id: int, parser: str = "rule", model: str | None = None, context: str = "window",
               transcript: str = "gold", transcript_model: str | None = None):
        _require("parser", parser, PARSER_MODELS)
        model = model or PARSER_MODELS[parser][0]
        _require("model", model, PARSER_MODELS[parser])
        _require("context mode", context, CONTEXT_MODES)
        _require("transcript kind", transcript, TRANSCRIPT_KINDS)
        with db() as conn:
            recording = get_recording(conn, recording_id)
            if recording is None:
                raise HTTPException(404, f"no recording {recording_id}")
            pinned = transcript_model or default_transcript_model(conn, transcript, recording_id)
            tl = build_timeline(conn, recording_id, parser=parser, model=model, transcript_kind=transcript, context=context,
                                transcript_model=pinned)
        return timeline_dict(tl, recording, pinned)
```

In `scripts/parse_events.py`, replace:

```python
from atcdb.replay import (PARSER_MODELS, PARSERS, build_timeline, cache_version, clear_events,  # noqa: E402
                          default_transcript_model, list_recordings)
```

with:

```python
from atcdb.replay import (PARSER_MODELS, PARSER_VERSIONS, PARSERS, build_timeline, cache_version,  # noqa: E402
                          clear_events, default_transcript_model, list_recordings)
```

In `scripts/parse_events.py`, replace:

```python
        model, version = PARSER_MODELS[args.parser]
```

with:

```python
        model, version = PARSER_MODELS[args.parser][0], PARSER_VERSIONS[args.parser]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest -q`
Expected: PASS — 206 passed.

- [ ] **Step 5: Commit**

```bash
git add atcdb/replay.py atcdb/api.py scripts/parse_events.py tests/test_replay.py tests/test_api.py
git commit -m "feat: parser registry by model, lazy Claude resolution, capabilities and a validated model"
```

---

### Task 6: Precompute and inspection scripts for the Claude parser

`scripts/parse_events.py` fills the cache before a demo or an evaluation run. It gains `--model`, `--recording` (repeatable; any recording, including ones `list_recordings` would filter out) and `--dry-run`, which prints how many transmissions still need parsing and a rough cost, then stops without calling the API or writing anything (spec A.4, latency and cost). The miss count comes from a new `replay.uncached_parses`, which walks a recording like `build_timeline` but parses nothing: it folds whatever is already cached, so a miss in `window` mode carries the context it would really be parsed with, as far as the cache knows. `scripts/show_replay.py` gains `--model`.

**Files:**
- Modify: `atcdb/replay.py` (`uncached_parses`), `atcdb/parse_llm.py` (`estimate_cost`), `scripts/parse_events.py`, `scripts/show_replay.py`
- Test: `tests/test_replay.py`, `tests/test_parse_llm.py`

**Interfaces:**
- Consumes: `parse_llm.render_prompt`, `SYSTEM`, `TOOL` (Task 4); the registry (Task 5).
- Produces: `replay.uncached_parses(conn, recording_id, parser="rule", transcript_kind="gold", context="window", model=None, model_version=None, transcript_model=None) -> list[tuple[Transmission, Context]]`; `parse_llm.PRICES_PER_MTOK`; `parse_llm.estimate_cost(model: str, prompts: list[str]) -> float` (USD).

- [ ] **Step 1: Write the failing tests**

In `tests/test_replay.py`, replace:

```python
                          list_recordings, load_recording, transcript_models)
```

with:

```python
                          list_recordings, load_recording, transcript_models, uncached_parses)
```

Append to `tests/test_replay.py`:

```python


def test_uncached_parses_lists_what_a_replay_would_still_have_to_parse(tmp_path):
    conn = init_db(tmp_path / "t.sqlite")
    rid = _seed(conn, SEQUENCE[:3])
    txs = load_recording(conn, rid)
    assert [tx for tx, _ in uncached_parses(conn, rid)] == txs
    build_timeline(conn, rid)                                  # the rules parser caches all three in window mode
    assert uncached_parses(conn, rid) == []
    assert len(uncached_parses(conn, rid, context="role")) == 3   # another context mode is another cache entry
    conn.execute("DELETE FROM events WHERE transcript_id = ?", (txs[2].transcript_id,))
    conn.commit()
    [(tx, ctx)] = uncached_parses(conn, rid)
    assert tx == txs[2] and ctx.active_runways == ("31",)       # the cached LAND on 31 is folded into the context
    assert ctx.history == tuple((r, t) for r, t in SEQUENCE[:2])
    assert conn.execute("SELECT count(*) FROM events").fetchone()[0] == 2   # counting parsed and stored nothing
```

In `tests/test_parse_llm.py`, replace:

```python
from atcdb.parse_llm import EVENT_KINDS, MODELS, SYSTEM, TOOL, ParseError, make_parser, render_prompt, request, to_events
```

with:

```python
from atcdb.parse_llm import (EVENT_KINDS, MODELS, SYSTEM, TOOL, ParseError, estimate_cost, make_parser, render_prompt, request,
                             to_events)
```

Append to `tests/test_parse_llm.py`:

```python


def test_estimate_cost_scales_with_the_calls_and_the_price():
    assert estimate_cost("claude-haiku-4-5", []) == 0
    one = estimate_cost("claude-haiku-4-5", ["x" * 400])
    assert 0 < one < 0.01
    assert estimate_cost("claude-haiku-4-5", ["x" * 400] * 10) == pytest.approx(10 * one)
    assert estimate_cost("claude-sonnet-5", ["x" * 400]) == pytest.approx(2 * one)   # both prices are double Haiku's
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_replay.py tests/test_parse_llm.py -q`
Expected: FAIL — `ImportError: cannot import name 'uncached_parses'` (test_replay fails to collect, which stops the run).

- [ ] **Step 3: Write the implementation**

In `atcdb/replay.py`, replace:

```python
def build_timeline(conn: sqlite3.Connection, recording_id: int, parser: str = "rule", transcript_kind: str = "gold",
```

with:

```python
def uncached_parses(conn: sqlite3.Connection, recording_id: int, parser: str = "rule", transcript_kind: str = "gold",
                    context: str = "window", model: str | None = None, model_version: str | None = None,
                    transcript_model: str | None = None) -> list[tuple[Transmission, Context]]:
    """The transmissions `build_timeline` would have to parse, each with the context it would be parsed in as far as the
    cache knows (cached events are folded; a missing parse contributes nothing to later context). Parses nothing and
    stores nothing: this is what `parse_events.py --dry-run` counts."""
    model = model or PARSER_MODELS[parser][0]
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
```

In `atcdb/parse_llm.py`, replace:

```python
MAX_TOKENS = 1024   # a transmission yields a handful of events; a truncated reply raises ParseError
```

with:

```python
MAX_TOKENS = 1024   # a transmission yields a handful of events; a truncated reply raises ParseError

# For `parse_events.py --dry-run` only. USD per million tokens, (input, output), as listed 2026-06.
PRICES_PER_MTOK: dict[str, tuple[float, float]] = {"claude-haiku-4-5": (1.00, 5.00), "claude-sonnet-5": (2.00, 10.00)}
_TOOL_USE_OVERHEAD_TOKENS = 350   # the system prompt the API adds when tools are present (rough)
_OUTPUT_TOKENS = 150              # a tool call with a handful of events (rough)
```

In `atcdb/parse_llm.py`, replace:

```python
def availability() -> tuple[bool, str | None]:
```

with:

```python
def estimate_cost(model: str, prompts: list[str]) -> float:
    """Rough USD for one call per user prompt: about four characters a token for the prompt, the system prompt and the
    tool, plus the API's tool-use overhead in, and a short tool call out. Good to a factor of two; for dry runs only."""
    fixed = (len(SYSTEM) + len(json.dumps(TOOL))) / 4 + _TOOL_USE_OVERHEAD_TOKENS
    tokens_in = sum(fixed + len(p) / 4 for p in prompts)
    price_in, price_out = PRICES_PER_MTOK[model]
    return (tokens_in * price_in + len(prompts) * _OUTPUT_TOKENS * price_out) / 1e6


def availability() -> tuple[bool, str | None]:
```

In `scripts/parse_events.py`, replace:

```python
Usage:
    python scripts/parse_events.py [--parser rule] [--context window] [--transcript gold]
                                   [--facility Tower] [--min-transmissions 4] [--limit N] [--db data/atc.sqlite]
                                   [--refresh]

Idempotent per (parser, model, version, context): re-running only parses what is missing.
"""
```

with:

```python
Usage:
    python scripts/parse_events.py [--parser rule|llm] [--model MODEL] [--context window] [--transcript gold]
                                   [--facility Tower] [--min-transmissions 4] [--limit N] [--recording ID ...]
                                   [--db data/atc.sqlite] [--refresh | --dry-run]

Idempotent per (parser, model, version, context): re-running only parses what is missing. `--dry-run` prints how many
transmissions still need parsing and a rough cost, then stops without calling the API or writing anything. A cold
`window` run with the Claude parser is sequential, since each parse sees the engine state the previous ones built.
"""
```

In `scripts/parse_events.py`, replace:

```python
from atcdb.parsing import CONTEXT_MODES  # noqa: E402
from atcdb.replay import (PARSER_MODELS, PARSER_VERSIONS, PARSERS, build_timeline, cache_version,  # noqa: E402
                          clear_events, default_transcript_model, list_recordings)
```

with:

```python
from atcdb.parse_llm import estimate_cost, render_prompt  # noqa: E402
from atcdb.parsing import CONTEXT_MODES  # noqa: E402
from atcdb.replay import (PARSER_MODELS, PARSER_VERSIONS, PARSERS, build_timeline, cache_version,  # noqa: E402
                          clear_events, default_transcript_model, list_recordings, uncached_parses)
```

In `scripts/parse_events.py`, replace:

```python
    ap.add_argument("--parser", choices=sorted(PARSERS), default="rule")
    ap.add_argument("--context", choices=CONTEXT_MODES, default="window")
    ap.add_argument("--transcript", choices=["gold", "asr"], default="gold")
    ap.add_argument("--facility", default="Tower")
    ap.add_argument("--min-transmissions", type=int, default=4)
    ap.add_argument("--limit", type=int)
    ap.add_argument("--refresh", action="store_true", help="delete this parser/context's cached events first")
    args = ap.parse_args()

    conn = init_db(args.db)
    if args.refresh:
        model, version = PARSER_MODELS[args.parser][0], PARSER_VERSIONS[args.parser]
        n = clear_events(conn, args.parser, model, cache_version(version, args.context), args.context)
        print(f"cleared {n} cached events")
    recordings = list_recordings(conn, facility=args.facility, min_transmissions=args.min_transmissions, transcript_kind=args.transcript)
    if args.limit:
        recordings = recordings[:args.limit]
    kinds, conflicts, errors, n_steps = Counter(), Counter(), 0, 0
    for i, rec in enumerate(recordings, 1):
        tl = build_timeline(conn, rec["id"], parser=args.parser, transcript_kind=args.transcript, context=args.context,
                            transcript_model=default_transcript_model(conn, args.transcript, rec["id"]))
```

with:

```python
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
```

In `scripts/parse_events.py`, replace:

```python
    print(f"{len(recordings)} recordings, {n_steps} transmissions, {errors} parse errors "
          f"({args.parser}/{args.context}/{args.transcript})")
```

with:

```python
    print(f"{len(recordings)} recordings, {n_steps} transmissions, {errors} parse errors ({run})")
```

In `scripts/show_replay.py`, replace:

```python
    python scripts/show_replay.py RECORDING [--parser rule] [--context window] [--transcript gold] [--db data/atc.sqlite]
```

with:

```python
    python scripts/show_replay.py RECORDING [--parser rule|llm] [--model MODEL] [--context window] [--transcript gold]
                                            [--db data/atc.sqlite]
```

In `scripts/show_replay.py`, replace:

```python
from atcdb.replay import PARSERS, build_timeline, default_transcript_model  # noqa: E402
```

with:

```python
from atcdb.replay import PARSER_MODELS, PARSERS, build_timeline, default_transcript_model  # noqa: E402
```

In `scripts/show_replay.py`, replace:

```python
    ap.add_argument("--parser", choices=sorted(PARSERS), default="rule")
    ap.add_argument("--context", choices=CONTEXT_MODES, default="window")
    ap.add_argument("--transcript", choices=["gold", "asr"], default="gold")
    args = ap.parse_args()
```

with:

```python
    ap.add_argument("--parser", choices=sorted(PARSERS), default="rule")
    ap.add_argument("--model", help="one of the parser's models (default: its first)")
    ap.add_argument("--context", choices=CONTEXT_MODES, default="window")
    ap.add_argument("--transcript", choices=["gold", "asr"], default="gold")
    args = ap.parse_args()
    if args.model and args.model not in PARSER_MODELS[args.parser]:
        ap.error(f"--model {args.model!r} is not a model of --parser {args.parser}; expected one of {PARSER_MODELS[args.parser]}")
```

In `scripts/show_replay.py`, replace:

```python
    tl = build_timeline(conn, row["id"], parser=args.parser, transcript_kind=args.transcript, context=args.context,
                       transcript_model=default_transcript_model(conn, args.transcript, row["id"]))
    print(f"recording {row['id']} ({row['external_id']}) — {len(tl.steps)} transmissions — {tl.parser}/{tl.context}/{tl.transcript_kind}\n")
```

with:

```python
    tl = build_timeline(conn, row["id"], parser=args.parser, model=args.model, transcript_kind=args.transcript,
                        context=args.context, transcript_model=default_transcript_model(conn, args.transcript, row["id"]))
    print(f"recording {row['id']} ({row['external_id']}) — {len(tl.steps)} transmissions — "
          f"{tl.parser}/{tl.model}/{tl.context}/{tl.transcript_kind}\n")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest -q`
Expected: PASS — 208 passed.

- [ ] **Step 5: Check the scripts on the corpus**

Skip this step if `data/atc.sqlite` is absent. Neither command calls the API. The dry run writes nothing; `show_replay.py` caches the rules parse of recording 528, as any replay does.

Run: `.venv/bin/python scripts/parse_events.py --parser llm --model claude-sonnet-5 --dry-run`
Expected: PASS — `dry run: 2016 transmissions to parse in 309 recordings (llm/claude-sonnet-5/window/gold); estimated cost $7.15` (fewer transmissions and a lower cost if some Claude parses are already cached).

Run: `.venv/bin/python scripts/show_replay.py 528 --parser rule | tail -1`
Expected: PASS — `1 conflict(s)` (recording 528's known false alert, unchanged).

- [ ] **Step 6: Commit**

```bash
git add atcdb/replay.py atcdb/parse_llm.py scripts/parse_events.py scripts/show_replay.py tests/test_replay.py tests/test_parse_llm.py
git commit -m "feat: parse_events --model, --recording and --dry-run; show_replay --model"
```

---

### Task 7: The replay page chooses a parser model

The page lists one parser option per parser-model pair from the capabilities route; an unavailable one is disabled with its reason as the tooltip (spec A.4). The replay request carries the model. A request token discards a reply that arrives after the user has already changed the selection: a cold Claude replay is one API call per transmission and can take a minute, so without it a slow reply could overwrite a newer one (carry-over, spec A.4). Each feed item shows how many instructions were dropped at that step (phase 2.5's counter, which now includes Claude's UNRESOLVED events, so those are not also drawn as event chips), and a conflict in the list shows its ICAO basis as a tooltip.

The repo has no JavaScript test harness: the page is checked by a smoke run in a browser, as in phase 2 (spec Section 3 addendum, Testing).

**Files:**
- Modify: `atcdb/static/app.js`, `atcdb/static/style.css`

**Interfaces:**
- Consumes: capabilities `parsers[]` entries `{name, model, model_version, available, reason}` and the replay route's `model` parameter (Task 5); `step.dropped` and `conflict.basis` (phase 2.5).
- Produces: nothing other tasks use.

- [ ] **Step 1: Write the implementation**

In `atcdb/static/app.js`, replace:

```javascript
const ui = { timeline: null, k: 0, timer: null, wanted: new URLSearchParams(location.search).get("recording") };
```

with:

```javascript
// `request` numbers replay loads: a reply is used only if no newer load started while it was in flight.
const ui = { timeline: null, k: 0, timer: null, request: 0, wanted: new URLSearchParams(location.search).get("recording") };
```

In `atcdb/static/app.js`, replace:

```javascript
  for (const p of caps.parsers) $("parser").append(option(p.name, `${p.name} (${p.model} ${p.model_version})`));
  for (const c of caps.contexts) $("context").append(option(c, c));
  for (const kind of Object.keys(caps.transcripts)) $("transcript").append(option(kind, kind));
  $("context").value = "window";
```

with:

```javascript
  for (const p of caps.parsers) {
    const o = option(`${p.name}|${p.model}`, `${p.name} · ${p.model} (${p.model_version})`);
    o.disabled = !p.available;   // e.g. no API key: cold parses cannot run here
    if (p.reason) o.title = p.reason;
    $("parser").append(o);
  }
  for (const c of caps.contexts) $("context").append(option(c, c));
  for (const kind of Object.keys(caps.transcripts)) $("transcript").append(option(kind, kind));
  $("parser").value = "rule|rules";
  $("context").value = "window";
```

In `atcdb/static/app.js`, replace:

```javascript
async function loadReplay() {
  stop();
  const id = $("recording").value;
  ui.timeline = null;
  ui.k = 0;
  render();   // clear the previous recording and disable the transport while the new one loads
  if (id) {
    const query = new URLSearchParams({ parser: $("parser").value, context: $("context").value, transcript: $("transcript").value });
    setStatus("Loading…");
    try {
      ui.timeline = await getJSON(`/api/recordings/${id}/replay?${query}`);
      setStatus(ui.timeline.steps.length ? "" : "This recording has no transcripts of that kind.");
      history.replaceState(null, "", `?recording=${id}`);
    } catch (error) {
      setStatus(`Could not load the replay: ${error.message}`);
    }
  }
  render();
}
```

with:

```javascript
async function loadReplay() {
  stop();
  const token = ++ui.request;
  const id = $("recording").value;
  ui.timeline = null;
  ui.k = 0;
  render();   // clear the previous recording and disable the transport while the new one loads
  if (id) {
    const [parser, model] = $("parser").value.split("|");
    const query = new URLSearchParams({ parser, model, context: $("context").value, transcript: $("transcript").value });
    setStatus(parser === "rule" ? "Loading…" : "Loading… (a first Claude replay parses every transmission; this can take a minute)");
    try {
      const timeline = await getJSON(`/api/recordings/${id}/replay?${query}`);
      if (token !== ui.request) return;   // superseded: a newer selection is loading
      ui.timeline = timeline;
      setStatus(timeline.steps.length ? "" : "This recording has no transcripts of that kind.");
      history.replaceState(null, "", `?recording=${id}`);
    } catch (error) {
      if (token !== ui.request) return;
      setStatus(`Could not load the replay: ${error.message}`);
    }
  }
  render();
}
```

In `atcdb/static/app.js`, replace:

```javascript
    for (const e of s.events) if (e.kind !== "NOOP") chips.append(el("span", `chip ${e.kind.toLowerCase()}`, eventLabel(e)));
    for (const c of s.conflicts) chips.append(el("span", `chip flag ${c.severity}`, `${c.severity} · ${c.type.toLowerCase()}`));
    if (s.error) chips.append(el("span", "chip failed", `parse error: ${s.error}`));
```

with:

```javascript
    for (const e of s.events) {
      if (e.kind !== "NOOP" && e.kind !== "UNRESOLVED") chips.append(el("span", `chip ${e.kind.toLowerCase()}`, eventLabel(e)));
    }
    for (const c of s.conflicts) chips.append(el("span", `chip flag ${c.severity}`, `${c.severity} · ${c.type.toLowerCase()}`));
    if (s.dropped) chips.append(el("span", "chip dropped", `${s.dropped} dropped`));   // includes UNRESOLVED events
    if (s.error) chips.append(el("span", "chip failed", `parse error: ${s.error}`));
```

In `atcdb/static/app.js`, replace:

```javascript
      const item = el("li", `conflict ${c.severity}`);
```

with:

```javascript
      const item = el("li", `conflict ${c.severity}`);
      if (c.basis) item.title = `Basis: ${c.basis}`;
```

In `atcdb/static/style.css`, replace:

```css
.chip.failed { color: var(--alert); border-color: currentColor; }
```

with:

```css
.chip.failed { color: var(--alert); border-color: currentColor; }
.chip.dropped { color: var(--warn); border-color: currentColor; border-style: dashed; }
```

- [ ] **Step 2: Run the tests**

Run: `.venv/bin/python -m pytest -q`
Expected: PASS — 208 passed (`test_front_end_assets_are_served` still finds `/api/capabilities` in `app.js`).

- [ ] **Step 3: Smoke-check in a browser**

Start the server with no key, so the Claude options are disabled: `env -u ANTHROPIC_API_KEY .venv/bin/uvicorn atcdb.api:app --port 8010` (port 8000 is usually taken), and open `http://127.0.0.1:8010/?recording=528`. Check:

- The Parser list shows `llm · claude-haiku-4-5 (p1)` and `llm · claude-sonnet-5 (p1)` greyed out, with "ANTHROPIC_API_KEY not set" on hover, and `rule · rules (v1)` selected.
- Recording 528 replays with the rules parser; stepping to transmission 17 shows the RUNWAY alert on runway 13, and hovering the conflict in "Conflicts so far" shows no basis (LAND against a held CROSS has none).
- Switching Context quickly between `none`, `role` and `window` leaves the page showing the last choice.
- The browser console shows no errors.

Stop the server.

- [ ] **Step 4: Commit**

```bash
git add atcdb/static/app.js atcdb/static/style.css
git commit -m "feat: replay page chooses a parser model, ignores superseded replies, shows drops"
```

---

### Task 8: Recorded replies, a live smoke test, and the README

The response mapper is backed by real replies (spec A.4, Testing): `scripts/record_llm_fixtures.py` sends six transmissions to both models with exactly the request the parser makes and stores each reply's stop reason and content blocks in `tests/fixtures/llm_responses.json`. The texts are NTSB public record (Austin) or invented; no corpus text. A test maps every recorded reply and pins the events it yields, and another pins the fixture to the current `parse_llm.VERSION`, so a prompt or schema change cannot pass without re-recording. These are characterisation tests: the recorded replies include two findings for phase 3b. Haiku reads the Austin pilot's takeoff readback as a new TAKEOFF clearance for "one seven zero" (the heading); Sonnet reads it as a READBACK but misses the callsign at the end. The prompt is not tuned to them. One live smoke test calls Haiku once and skips without `ANTHROPIC_API_KEY`.

The recorded replies below were captured on 2026-09-27. Copy the fixture exactly; do not re-record it as part of this task.

**Files:**
- Create: `scripts/record_llm_fixtures.py`, `tests/fixtures/llm_responses.json`
- Modify: `tests/test_parse_llm.py`, `README.md`

**Interfaces:**
- Consumes: `parse_llm.request`, `events_from_response`, `make_parser`, `VERSION`, `MODELS` (Task 4).
- Produces: nothing other tasks use.

- [ ] **Step 1: Create the recording script and the recorded replies**

Create `scripts/record_llm_fixtures.py`:

```python
#!/usr/bin/env python3
"""Record real Claude replies for the parser's regression fixtures (tests/fixtures/llm_responses.json).

Usage:
    ANTHROPIC_API_KEY=... python scripts/record_llm_fixtures.py

Sends each case below to every model in parse_llm.MODELS with exactly the request the parser makes, and stores each
reply's stop reason and content blocks. Re-run it whenever parse_llm.VERSION is bumped, then update the expectations in
tests/test_parse_llm.py. The texts are NTSB public record (Austin, DCA23FA149) or invented: UWB-ATCC corpus text is
CC BY-NC-ND and must never be written into a fixture.
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import anthropic  # noqa: E402

from atcdb.parse_llm import MODELS, VERSION, request  # noqa: E402
from atcdb.parsing import Context, Transmission  # noqa: E402

OUT = ROOT / "tests" / "fixtures" / "llm_responses.json"
AUSTIN_LAND = ("fedex fourteen thirty-two heavy austin tower one eight left r-v-r touchdown one thousand four hundred "
               "midpoint six hundred rollout one thousand eight hundred one eight left cleared to land")
AUSTIN_TAKEOFF = ("southwest seven zero eight austin tower runway one eight left r-v-r one thousand two hundred midpoint six "
                  "hundred rollout one thousand six hundred fly heading one seven zero runway one eight left cleared for "
                  "takeoff traffic three mile final is a heavy seven sixty-seven")

# name -> (role, text, context). Contexts are built by hand so every case is self-contained.
CASES: dict[str, tuple[str, str, Context]] = {
    "austin_landing_clearance": ("controller", AUSTIN_LAND, Context(mode="role", role="controller")),
    "austin_takeoff_clearance": ("controller", AUSTIN_TAKEOFF, Context(mode="role", role="controller")),
    "austin_takeoff_readback": ("pilot", "okay that's one seven zero cleared for takeoff one eight left copy the traffic "
                                "southwest seven zero eight", Context(mode="role", role="pilot")),
    "austin_handoff": ("controller", "american nineteen thirteen contact departure", Context(mode="role", role="controller")),
    "cross_then_hold_short": ("controller", "lufthansa four five six cross runway two four hold short of runway three one",
                              Context(mode="role", role="controller")),
    "window_snaps_to_the_active_runway": ("controller", "csa one two three cleared to land wind calm", Context(
        mode="window", role="controller", history=(("pilot", "csa one two three established runway three one"),),
        active_callsigns=("csa one two three",), active_runways=("31",))),
}


def main() -> None:
    client = anthropic.Anthropic()
    records = []
    for name, (role, text, ctx) in CASES.items():
        tx = Transmission(id=0, transcript_id=0, text=text, role=role, start_s=0.0)
        for model in MODELS:
            reply = client.messages.create(**request(model, tx, ctx))
            records.append({"case": name, "model": model, "version": VERSION, "role": role, "text": text,
                            "context": {"mode": ctx.mode, "role": ctx.role, "history": [list(h) for h in ctx.history],
                                        "active_callsigns": list(ctx.active_callsigns),
                                        "active_runways": list(ctx.active_runways)},
                            "stop_reason": reply.stop_reason,
                            "content": [b.to_dict() for b in reply.content]})
            print(f"{name:36} {model:18} {reply.stop_reason}", flush=True)
    OUT.write_text(json.dumps(records, indent=1) + "\n")
    print(f"wrote {len(records)} replies to {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
```

Create `tests/fixtures/llm_responses.json`:

```json
[
 {
  "case": "austin_landing_clearance",
  "model": "claude-haiku-4-5",
  "version": "p1",
  "role": "controller",
  "text": "fedex fourteen thirty-two heavy austin tower one eight left r-v-r touchdown one thousand four hundred midpoint six hundred rollout one thousand eight hundred one eight left cleared to land",
  "context": {
   "mode": "role",
   "role": "controller",
   "history": [],
   "active_callsigns": [],
   "active_runways": []
  },
  "stop_reason": "tool_use",
  "content": [
   {
    "id": "toolu_01EY2vh6vUHsWiQhL8DNEBw4",
    "caller": {
     "type": "direct"
    },
    "input": {
     "events": [
      {
       "kind": "LAND",
       "callsign": "fedex fourteen thirty-two heavy",
       "runway": "18L",
       "to": null
      }
     ]
    },
    "name": "report_events",
    "type": "tool_use"
   }
  ]
 },
 {
  "case": "austin_landing_clearance",
  "model": "claude-sonnet-5",
  "version": "p1",
  "role": "controller",
  "text": "fedex fourteen thirty-two heavy austin tower one eight left r-v-r touchdown one thousand four hundred midpoint six hundred rollout one thousand eight hundred one eight left cleared to land",
  "context": {
   "mode": "role",
   "role": "controller",
   "history": [],
   "active_callsigns": [],
   "active_runways": []
  },
  "stop_reason": "tool_use",
  "content": [
   {
    "id": "toolu_011tUR66YxN7WP7JcbniEFb4",
    "caller": {
     "type": "direct"
    },
    "input": {
     "events": [
      {
       "kind": "LAND",
       "callsign": "fedex fourteen thirty-two heavy",
       "runway": "18L",
       "to": null
      }
     ]
    },
    "name": "report_events",
    "type": "tool_use"
   }
  ]
 },
 {
  "case": "austin_takeoff_clearance",
  "model": "claude-haiku-4-5",
  "version": "p1",
  "role": "controller",
  "text": "southwest seven zero eight austin tower runway one eight left r-v-r one thousand two hundred midpoint six hundred rollout one thousand six hundred fly heading one seven zero runway one eight left cleared for takeoff traffic three mile final is a heavy seven sixty-seven",
  "context": {
   "mode": "role",
   "role": "controller",
   "history": [],
   "active_callsigns": [],
   "active_runways": []
  },
  "stop_reason": "tool_use",
  "content": [
   {
    "id": "toolu_01S4FopmgjpEVQSCuYKrdqZd",
    "caller": {
     "type": "direct"
    },
    "input": {
     "events": [
      {
       "kind": "TAKEOFF",
       "callsign": "southwest seven zero eight",
       "runway": "18L",
       "to": null
      }
     ]
    },
    "name": "report_events",
    "type": "tool_use"
   }
  ]
 },
 {
  "case": "austin_takeoff_clearance",
  "model": "claude-sonnet-5",
  "version": "p1",
  "role": "controller",
  "text": "southwest seven zero eight austin tower runway one eight left r-v-r one thousand two hundred midpoint six hundred rollout one thousand six hundred fly heading one seven zero runway one eight left cleared for takeoff traffic three mile final is a heavy seven sixty-seven",
  "context": {
   "mode": "role",
   "role": "controller",
   "history": [],
   "active_callsigns": [],
   "active_runways": []
  },
  "stop_reason": "tool_use",
  "content": [
   {
    "id": "toolu_01CRQEiQTAQgTbp3eW9JhNMq",
    "caller": {
     "type": "direct"
    },
    "input": {
     "events": [
      {
       "kind": "TAKEOFF",
       "callsign": "southwest seven zero eight",
       "runway": "18L",
       "to": null
      }
     ]
    },
    "name": "report_events",
    "type": "tool_use"
   }
  ]
 },
 {
  "case": "austin_takeoff_readback",
  "model": "claude-haiku-4-5",
  "version": "p1",
  "role": "pilot",
  "text": "okay that's one seven zero cleared for takeoff one eight left copy the traffic southwest seven zero eight",
  "context": {
   "mode": "role",
   "role": "pilot",
   "history": [],
   "active_callsigns": [],
   "active_runways": []
  },
  "stop_reason": "tool_use",
  "content": [
   {
    "id": "toolu_018p87zTD7TmipwX1etMhvwq",
    "caller": {
     "type": "direct"
    },
    "input": {
     "events": [
      {
       "kind": "TAKEOFF",
       "callsign": "one seven zero",
       "runway": "18L",
       "to": null
      }
     ]
    },
    "name": "report_events",
    "type": "tool_use"
   }
  ]
 },
 {
  "case": "austin_takeoff_readback",
  "model": "claude-sonnet-5",
  "version": "p1",
  "role": "pilot",
  "text": "okay that's one seven zero cleared for takeoff one eight left copy the traffic southwest seven zero eight",
  "context": {
   "mode": "role",
   "role": "pilot",
   "history": [],
   "active_callsigns": [],
   "active_runways": []
  },
  "stop_reason": "tool_use",
  "content": [
   {
    "id": "toolu_017BMTEjGb5Lu3CpEnWcA12N",
    "caller": {
     "type": "direct"
    },
    "input": {
     "events": [
      {
       "kind": "READBACK",
       "callsign": "",
       "runway": "18L",
       "to": null
      }
     ]
    },
    "name": "report_events",
    "type": "tool_use"
   }
  ]
 },
 {
  "case": "austin_handoff",
  "model": "claude-haiku-4-5",
  "version": "p1",
  "role": "controller",
  "text": "american nineteen thirteen contact departure",
  "context": {
   "mode": "role",
   "role": "controller",
   "history": [],
   "active_callsigns": [],
   "active_runways": []
  },
  "stop_reason": "tool_use",
  "content": [
   {
    "id": "toolu_01PUojKofBGxif9NCd4rBCQF",
    "caller": {
     "type": "direct"
    },
    "input": {
     "events": [
      {
       "kind": "HANDOFF",
       "callsign": "american nineteen thirteen",
       "runway": null,
       "to": "departure"
      }
     ]
    },
    "name": "report_events",
    "type": "tool_use"
   }
  ]
 },
 {
  "case": "austin_handoff",
  "model": "claude-sonnet-5",
  "version": "p1",
  "role": "controller",
  "text": "american nineteen thirteen contact departure",
  "context": {
   "mode": "role",
   "role": "controller",
   "history": [],
   "active_callsigns": [],
   "active_runways": []
  },
  "stop_reason": "tool_use",
  "content": [
   {
    "id": "toolu_015VnW6iBENruugpEpbPSY9V",
    "caller": {
     "type": "direct"
    },
    "input": {
     "events": [
      {
       "kind": "HANDOFF",
       "callsign": "american nineteen thirteen",
       "runway": null,
       "to": "departure"
      }
     ]
    },
    "name": "report_events",
    "type": "tool_use"
   }
  ]
 },
 {
  "case": "cross_then_hold_short",
  "model": "claude-haiku-4-5",
  "version": "p1",
  "role": "controller",
  "text": "lufthansa four five six cross runway two four hold short of runway three one",
  "context": {
   "mode": "role",
   "role": "controller",
   "history": [],
   "active_callsigns": [],
   "active_runways": []
  },
  "stop_reason": "tool_use",
  "content": [
   {
    "id": "toolu_01P9bX1A5vDYjKq59boPMNG6",
    "caller": {
     "type": "direct"
    },
    "input": {
     "events": [
      {
       "kind": "CROSS",
       "callsign": "lufthansa four five six",
       "runway": "24",
       "to": null
      },
      {
       "kind": "HOLD_SHORT",
       "callsign": "lufthansa four five six",
       "runway": "31",
       "to": null
      }
     ]
    },
    "name": "report_events",
    "type": "tool_use"
   }
  ]
 },
 {
  "case": "cross_then_hold_short",
  "model": "claude-sonnet-5",
  "version": "p1",
  "role": "controller",
  "text": "lufthansa four five six cross runway two four hold short of runway three one",
  "context": {
   "mode": "role",
   "role": "controller",
   "history": [],
   "active_callsigns": [],
   "active_runways": []
  },
  "stop_reason": "tool_use",
  "content": [
   {
    "id": "toolu_01NNU9ZdsXtSXjqoonxo7dLV",
    "caller": {
     "type": "direct"
    },
    "input": {
     "events": [
      {
       "kind": "CROSS",
       "callsign": "lufthansa four five six",
       "runway": "24",
       "to": null
      },
      {
       "kind": "HOLD_SHORT",
       "callsign": "lufthansa four five six",
       "runway": "31",
       "to": null
      }
     ]
    },
    "name": "report_events",
    "type": "tool_use"
   }
  ]
 },
 {
  "case": "window_snaps_to_the_active_runway",
  "model": "claude-haiku-4-5",
  "version": "p1",
  "role": "controller",
  "text": "csa one two three cleared to land wind calm",
  "context": {
   "mode": "window",
   "role": "controller",
   "history": [
    [
     "pilot",
     "csa one two three established runway three one"
    ]
   ],
   "active_callsigns": [
    "csa one two three"
   ],
   "active_runways": [
    "31"
   ]
  },
  "stop_reason": "tool_use",
  "content": [
   {
    "id": "toolu_01P6Em1F1w9CpM6Hy8qWGEYg",
    "caller": {
     "type": "direct"
    },
    "input": {
     "events": [
      {
       "kind": "LAND",
       "callsign": "csa one two three",
       "runway": "31",
       "to": null
      }
     ]
    },
    "name": "report_events",
    "type": "tool_use"
   }
  ]
 },
 {
  "case": "window_snaps_to_the_active_runway",
  "model": "claude-sonnet-5",
  "version": "p1",
  "role": "controller",
  "text": "csa one two three cleared to land wind calm",
  "context": {
   "mode": "window",
   "role": "controller",
   "history": [
    [
     "pilot",
     "csa one two three established runway three one"
    ]
   ],
   "active_callsigns": [
    "csa one two three"
   ],
   "active_runways": [
    "31"
   ]
  },
  "stop_reason": "tool_use",
  "content": [
   {
    "id": "toolu_01E3J7WM6a5HGFLMcEddjzhK",
    "caller": {
     "type": "direct"
    },
    "input": {
     "events": [
      {
       "kind": "LAND",
       "callsign": "csa one two three",
       "runway": "31",
       "to": null
      }
     ]
    },
    "name": "report_events",
    "type": "tool_use"
   }
  ]
 }
]
```

- [ ] **Step 2: Write the tests**

In `tests/test_parse_llm.py`, replace:

```python
import json
import subprocess
```

with:

```python
import json
import os
import subprocess
```

In `tests/test_parse_llm.py`, replace:

```python
from atcdb.parse_llm import (EVENT_KINDS, MODELS, SYSTEM, TOOL, ParseError, estimate_cost, make_parser, render_prompt, request,
                             to_events)
```

with:

```python
from atcdb.parse_llm import (EVENT_KINDS, MODELS, SYSTEM, TOOL, ParseError, estimate_cost, events_from_response, make_parser,
                             render_prompt, request, to_events)
```

Append to `tests/test_parse_llm.py`:

```python


# --- recorded replies (scripts/record_llm_fixtures.py) -----------------------------------------

FIXTURE = ROOT / "tests" / "fixtures" / "llm_responses.json"

# (case, model) -> what the recorded reply maps to: (event type, callsign, runway or handoff target).
RECORDED = {
    **{("austin_landing_clearance", m): [("ClearToLand", "fedex fourteen thirty-two heavy", "18L")] for m in MODELS},
    **{("austin_takeoff_clearance", m): [("ClearTakeoff", "southwest seven zero eight", "18L")] for m in MODELS},
    # Findings, not expectations to fix here: Haiku reads the pilot's readback as a new clearance for the heading,
    # Sonnet sees a readback but misses the callsign said at the end.
    ("austin_takeoff_readback", "claude-haiku-4-5"): [("ClearTakeoff", "one seven zero", "18L")],
    ("austin_takeoff_readback", "claude-sonnet-5"): [("ReadbackObserved", "", None)],
    **{("austin_handoff", m): [("Handoff", "american nineteen thirteen", "departure")] for m in MODELS},
    **{("cross_then_hold_short", m): [("ClearToCross", "lufthansa four five six", "24"),
                                      ("HoldShort", "lufthansa four five six", "31")] for m in MODELS},
    **{("window_snaps_to_the_active_runway", m): [("ClearToLand", "csa one two three", "31")] for m in MODELS},
}


def _recorded():
    """Each recorded reply as (case, model, transmission, context, response), the response shaped like the SDK's Message."""
    for r in json.loads(FIXTURE.read_text()):
        c = r["context"]
        ctx = Context(mode=c["mode"], role=c["role"], history=tuple(tuple(h) for h in c["history"]),
                      active_callsigns=tuple(c["active_callsigns"]), active_runways=tuple(c["active_runways"]))
        tx = Transmission(id=0, transcript_id=0, text=r["text"], role=r["role"], start_s=0.0)
        response = SimpleNamespace(stop_reason=r["stop_reason"], content=[SimpleNamespace(**b) for b in r["content"]])
        yield r["case"], r["model"], tx, ctx, response


def test_recorded_replies_map_to_the_pinned_events():
    seen = set()
    for case, model, tx, ctx, response in _recorded():
        got = [(type(e).__name__, e.callsign, getattr(e, "runway", None) or getattr(e, "to", None))
               for e in events_from_response(response, tx)]
        assert got == RECORDED[(case, model)], (case, model)
        seen.add((case, model))
    assert seen == set(RECORDED)


def test_the_recorded_replies_are_for_this_parser_version():
    # A change to the prompt, the tool or the request bumps VERSION; then re-run scripts/record_llm_fixtures.py.
    assert {r["version"] for r in json.loads(FIXTURE.read_text())} == {parse_llm.VERSION}


@pytest.mark.skipif(not os.environ.get("ANTHROPIC_API_KEY"), reason="ANTHROPIC_API_KEY not set: live smoke test skipped")
def test_live_smoke_haiku_parses_a_landing_clearance():
    events = make_parser("claude-haiku-4-5")(TX, ROLE)
    assert [(type(e).__name__, e.callsign, e.runway) for e in events] == [("ClearToLand", "csa one two three", "31")]
```

- [ ] **Step 3: Run the tests**

Run: `.venv/bin/python -m pytest tests/test_parse_llm.py -q`
Expected: PASS — 17 passed (16 passed, 1 skipped without `ANTHROPIC_API_KEY`).

- [ ] **Step 4: Update the README**

In `README.md`, replace:

```text
# 5. replay UI: step through a recording in the browser (runway board, transmissions, conflicts, audio)
uvicorn atcdb.api:app --reload                     # then open http://127.0.0.1:8000/?recording=528

pytest   # 183 tests
```

with:

```text
# 5. replay UI: step through a recording in the browser (runway board, transmissions, conflicts, audio)
uvicorn atcdb.api:app --reload                     # then open http://127.0.0.1:8000/?recording=528

# 6. Claude parser (phase 3a): Haiku 4.5 and Sonnet 5 through one forced tool call; needs ANTHROPIC_API_KEY.
#    Without a key the page lists it disabled, and replays already in the cache still work.
python scripts/parse_events.py --parser llm --model claude-sonnet-5 --recording 528 --dry-run   # count and cost first
python scripts/parse_events.py --parser llm --model claude-sonnet-5 --recording 528             # parse and cache

pytest   # 211 tests; the live smoke test skips without ANTHROPIC_API_KEY
```

- [ ] **Step 5: Run the whole suite**

Run: `.venv/bin/python -m pytest -q`
Expected: PASS — 211 passed (210 passed, 1 skipped without `ANTHROPIC_API_KEY`).

- [ ] **Step 6: Commit**

```bash
git add scripts/record_llm_fixtures.py tests/fixtures/llm_responses.json tests/test_parse_llm.py README.md
git commit -m "test: recorded Claude replies back the mapper; live smoke test; README"
```

---

## Out of scope for this plan

- Phase 3b (spec A.5): the evaluation, labelling, conflict injection, choosing CROSS and LUAW staleness, and any prompt change prompted by the recorded readback findings (a prompt change bumps `parse_llm.VERSION`).
- Running Claude over the corpus. The plan's only API calls are the fixture recording (already done) and the live smoke test; a corpus run is a `parse_events.py` command after `--dry-run`.
- Parallel parsing of `none` and `role` contexts: it belongs to 3b's evaluation script (spec A.4, latency).
- The LLM judge arm (spec A.5, ablation).
