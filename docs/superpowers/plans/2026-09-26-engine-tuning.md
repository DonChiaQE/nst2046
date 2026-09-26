# Engine Tuning (Phase 2.5) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Settle the runway-conflict engine before any LLM parse or evaluation number is produced against it: single-digit runways, per-kind staleness, a holding-short lifecycle, readback conflicts that name a runway, validated handoff targets, a dropped-instruction counter, the ICAO basis for each rule, and two real incidents as regression fixtures.

**Architecture:** Almost everything lands in the pure engine (`atcdb/engine.py`). The rules parser gains one diagnostic function beside `parse` without changing `parse` itself. `atcdb/replay.py` and `atcdb/serialize.py` carry the new counter and citation out to the JSON API. A new data-only module `atcdb/doctrine.py` holds the ICAO citations and is seeded into the existing, empty `phraseology_rules` table by `init_db`.

**Tech Stack:** Python 3.14, sqlite3, pytest. No new dependencies.

**Spec:** `docs/superpowers/specs/2026-09-12-conflict-engine-design.md` — the **Addendum — phase-3 design pass**, sections A.2, A.3 and A.7 (the addendum wins where it and the text above it differ). This plan is phase 2.5 in the addendum's build order (A.1). Phases 1 and 2 are merged.

## Global Constraints

- The rules parser is **frozen at v1** (spec A.7.1): `parse_rules.parse` must return exactly what it returns today for every input, and `parse_rules.VERSION` stays `"v1"`. The only permitted addition to `atcdb/parse_rules.py` is the new diagnostic function in Task 5.
- `atcdb/engine.py` stays pure: no I/O, no database access and no new imports.
- `STALE_S` defaults every kind to **300 s**; **LAND must stay ≥ 284 s** (Austin 2023: the landing and conflicting takeoff clearances were 284 s apart). CROSS and LUAW values are chosen in phase 3b, not here.
- A hold-short of a *different* runway releases nothing (spec A.3.2). Corpus recording 528 must still raise its alert at step 17.
- UWB-ATCC is CC BY-NC-ND and is **not redistributed**: no corpus transcript text is committed. The recording-528 test reads `data/atc.sqlite` read-only and skips when it is absent. The Austin transcript is NTSB public record and is committed as a fixture.
- Tests follow the repo's style: plain pytest functions, real SQLite files under `tmp_path`, `monkeypatch` only, no mock framework. Run with `.venv/bin/python -m pytest`.
- Commit after every task; `feat:`/`test:`/`docs:` subjects ending with the attribution lines the session provides.

## File structure

| File | Responsibility |
|---|---|
| `atcdb/engine.py` (modify) | `normalize_runway`, `STALE_S`, `HANDOFF_TARGETS`, `MATRIX_BASIS`; `Aircraft.holding_short_t`, `State.ignored`, `Conflict.basis`; `_expire`, `_release`, `apply` |
| `atcdb/parse_rules.py` (modify) | new `count_unresolved(tx, ctx) -> int` beside `parse`; `parse` untouched |
| `atcdb/replay.py` (modify) | `DROP_COUNTERS`, `Step.dropped`, `Timeline.dropped`, counting in `build_timeline` |
| `atcdb/serialize.py` (modify) | `dropped` on steps and timelines, `basis` on conflicts |
| `atcdb/doctrine.py` (create) | the ICAO Doc 4444 citations and engineering heuristics, `seed(conn)` |
| `atcdb/schema.py` (modify) | `init_db` seeds `phraseology_rules` |
| `tests/fixtures/austin_dca23fa149.txt` (create) | the NTSB Austin tower transcript |
| `tests/test_engine.py`, `tests/test_parse_rules.py`, `tests/test_replay.py`, `tests/test_serialize.py` (modify); `tests/test_doctrine.py`, `tests/test_incidents.py` (create) | tests |
| `README.md` (modify) | test count |

Domain vocabulary for the engineer: a **reservation** is a runway held by one aircraft's clearance — LAND (cleared to land), TAKEOFF (cleared for takeoff), LUAW (line up and wait: on the runway, not rolling) or CROSS (cleared to cross while taxiing). A **hold-short** is an instruction to stop before a runway; it reserves nothing. A **release** ends a reservation: the aircraft vacated, was handed to another frequency, went around, or its reservation went **stale** (older than a timeout, because tower recordings are short clips and the release call is usually never heard). A **conflict** is RUNWAY (two incompatible reservations on one runway) or READBACK (a pilot failed to read back an item), severity `alert` or `warning`. `window` context mode gives the parser the engine's active runways and callsigns, so parses in that mode depend on engine state.

**Measured on the corpus while this plan was prototyped:** after all tasks, the rules parser's events are byte-for-byte identical to today's in all three context modes across the 309 foldable tower recordings, and the conflict total stays at 85 (27 READBACK alert, 8 READBACK warning, 12 RUNWAY alert, 38 RUNWAY warning). The only changed conflict is recording 1970's READBACK alert, which now names runway 13 instead of none. So the existing `events` cache stays valid and no `parse_events.py --refresh` is needed.

---

### Task 1: Single-digit runway designators

US controllers drop the leading zero ("runway four left"); ICAO phraseology keeps it ("zero four left"). Today `normalize_runway("four left")` returns `None`. Every extractor's runway string passes through this function, so it is fixed here, in the engine. The rules parser's own regexes only ever capture two digit words, so this cannot change a v1 parse.

**Files:**
- Modify: `atcdb/engine.py` (`_RUNWAY_RE`, `normalize_runway`)
- Test: `tests/test_engine.py` (`test_normalize_runway` cases)

**Interfaces:**
- Produces: `normalize_runway(text: str) -> str | None`, now zero-padding a single digit: `"four left" -> "04L"`, `"three" -> "03"`, `"4l" -> "04L"`. The existing case `("three", None)` becomes `("three", "03")` — an intended change.

- [ ] **Step 1: Write the failing test**

In `tests/test_engine.py`, replace:

```python
    ("", None),
    ("three", None),
    ("four zero", None),   # no such runway: heading 01-36 only
])
```

with:

```python
    ("", None),
    ("three", "03"),       # US phraseology drops the leading zero: "runway three"
    ("four left", "04L"),
    ("nine", "09"),
    ("4l", "04L"),
    ("zero", None),        # no runway 00
    ("four zero", None),   # no such runway: heading 01-36 only
    ("left", None),
])
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_engine.py -q -k normalize_runway`
Expected: FAIL — 4 failures (`three`, `four left`, `nine`, `4l`).

- [ ] **Step 3: Write minimal implementation**

In `atcdb/engine.py`, replace:

```python
_RUNWAY_RE = re.compile(r"^(\d{2})([lrc])?$")
```

with:

```python
_RUNWAY_RE = re.compile(r"^(\d{1,2})([lrc])?$")
```

In `atcdb/engine.py`, replace:

```python
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
```

with:

```python
    """'three one' -> '31', 'one six right' -> '16R', '16r' -> '16R', 'four left' -> '04L'. None if it is not a runway
    designator. A single digit is zero-padded: US controllers say "runway four left" where ICAO says "zero four left"."""
    words = (text or "").strip().lower().split()
    if not words:
        return None
    if words[0] in _DIGIT_WORD:
        if len(words) >= 2 and words[1] in _DIGIT_WORD:
            digits, rest = _DIGIT_WORD[words[0]] + _DIGIT_WORD[words[1]], words[2:]
        else:
            digits, rest = "0" + _DIGIT_WORD[words[0]], words[1:]
    else:
        m = _RUNWAY_RE.match(words[0])
        if not m:
            return None
        digits, rest = m.group(1).zfill(2), ([m.group(2)] if m.group(2) else []) + words[1:]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest -q`
Expected: PASS — 160 passed.

- [ ] **Step 5: Commit**

```bash
git add atcdb/engine.py tests/test_engine.py
git commit -m "feat: normalise single-digit runway designators"
```

---

### Task 2: Staleness per reservation kind

`STALE_S` becomes a dict keyed by kind, every kind at 300 s, so behaviour is unchanged and phase 3b can later shorten CROSS and LUAW against the false-alarm metric. `HOLD_SHORT` gets an entry now because Task 3 uses it. A test pins LAND at ≥ 284 s with Austin as the reason.

**Files:**
- Modify: `atcdb/engine.py` (`STALE_S`, `_expire`)
- Test: `tests/test_engine.py` (three existing lines use `STALE_S` as a number; two new tests)

**Interfaces:**
- Consumes: nothing new.
- Produces: `STALE_S: dict[str, float]` with keys `LAND`, `TAKEOFF`, `LUAW`, `CROSS`, `HOLD_SHORT`. Callers index it by kind: `STALE_S["LAND"]`.

- [ ] **Step 1: Write the failing tests**

In `tests/test_engine.py`, replace:

```python
import pytest

from atcdb.engine import (
```

with:

```python
import pytest

from atcdb import engine
from atcdb.engine import (
```

In `tests/test_engine.py`, replace:

```python
    _, c = fold([ClearToLand(callsign="a", runway="31", t=0.0), ClearToCross(callsign="b", runway="31", t=STALE_S + 1)])
```

with:

```python
    _, c = fold([ClearToLand(callsign="a", runway="31", t=0.0), ClearToCross(callsign="b", runway="31", t=STALE_S["LAND"] + 1)])
```

In `tests/test_engine.py`, replace:

```python
    state, _ = fold([NoOp(t=STALE_S + 101)], state)   # both the t=0 LAND and the t=100 CROSS are now stale
```

with:

```python
    state, _ = fold([NoOp(t=100 + max(STALE_S.values()) + 1)], state)   # both the t=0 LAND and the t=100 CROSS are now stale
```

In `tests/test_engine.py`, replace:

```python
    state, _ = fold([NoOp(t=STALE_S + 1)], state)
    assert state.runways == {}
```

with:

```python
    state, _ = fold([NoOp(t=STALE_S["LAND"] + 1)], state)
    assert state.runways == {}
```

Append to `tests/test_engine.py`:

```python


# --- phase 2.5 (spec addendum A.3) -------------------------------------------------------------

def test_staleness_is_per_kind(monkeypatch):
    assert set(STALE_S) == set(RESERVATION_KINDS) | {"HOLD_SHORT"}
    monkeypatch.setitem(engine.STALE_S, "CROSS", 30.0)
    _, c = fold([ClearToCross(callsign="a", runway="31", t=0.0), ClearToLand(callsign="b", runway="31", t=31.0)])
    assert c == []                                     # the crossing timed out after 30 s
    _, c = fold([ClearToLand(callsign="a", runway="31", t=0.0), ClearToCross(callsign="b", runway="31", t=31.0)])
    assert [x.severity for x in c] == ["alert"]        # the landing clearance did not


def test_landing_clearance_outlives_the_austin_gap():
    # Austin 2023: FedEx cleared to land 18L at 0634:14, Southwest cleared for takeoff on 18L at 0638:58, 284 s later.
    assert STALE_S["LAND"] >= 284
    _, c = fold([ClearToLand(callsign="fedex", runway="18L", t=0.0), ClearTakeoff(callsign="southwest", runway="18L", t=284.0)])
    assert [(x.type, x.severity, x.runway) for x in c] == [("RUNWAY", "alert", "18L")]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_engine.py -q`
Expected: FAIL — 4 failed: the three existing staleness tests with `TypeError: 'float' object is not subscriptable`, and `test_staleness_is_per_kind`.

- [ ] **Step 3: Write minimal implementation**

In `atcdb/engine.py`, replace:

```python
STALE_S = 300.0   # a reservation this old (transmission time) is dropped silently: we missed the release call
```

with:

```python
# A reservation (or hold-short) older than its kind's timeout, in transmission time, is dropped silently: we missed the
# release call. Per kind so that 3b can shorten CROSS and LUAW against the false-alarm metric (spec addendum A.3.6).
# LAND must stay >= 284 s: at Austin 2023 the landing and the conflicting takeoff clearance were 284 s apart.
STALE_S: dict[str, float] = {"LAND": 300.0, "TAKEOFF": 300.0, "LUAW": 300.0, "CROSS": 300.0, "HOLD_SHORT": 300.0}
```

In `atcdb/engine.py`, replace:

```python
    """Copy of the runway map and aircraft map with reservations older than STALE_S removed."""
    runways, aircraft = {}, dict(state.aircraft)
    for rwy, res in state.runways.items():
        keep = tuple(r for r in res if now - r.t <= STALE_S)
```

with:

```python
    """Copy of the runway map and aircraft map with reservations older than their kind's STALE_S removed."""
    runways, aircraft = {}, dict(state.aircraft)
    for rwy, res in state.runways.items():
        keep = tuple(r for r in res if now - r.t <= STALE_S[r.kind])
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest -q`
Expected: PASS — 162 passed.

- [ ] **Step 5: Commit**

```bash
git add atcdb/engine.py tests/test_engine.py
git commit -m "feat: per-kind staleness timeouts, LAND pinned above the Austin gap"
```

---

### Task 3: Holding-short lifecycle

Today a hold-short is set and never cleared except by the aircraft's next runway instruction, so 9 of 309 recordings end with a stale "holding short" line on a card. Three changes: a hold-short expires on its own `STALE_S["HOLD_SHORT"]` timeout; vacating the runway or a ground/departure handoff ends it; and "hold short runway 13" cancels that aircraft's own clearance *for runway 13* (spec A.3.2). A hold-short of another runway releases nothing — recording 528's controller clears Air France to cross 13 and, in the same breath, to "hold short of runway two four".

**Files:**
- Modify: `atcdb/engine.py` (`Aircraft`, `_expire`, `_release`, `apply`)
- Test: `tests/test_engine.py`

**Interfaces:**
- Consumes: `STALE_S["HOLD_SHORT"]` (Task 2).
- Produces: `Aircraft.holding_short_t: float | None` (transmission time of the hold-short). `_release(runways, callsign, kinds=RESERVATION_KINDS, runway=None)` — the new `runway` argument restricts the release to one runway. `atcdb/serialize.aircraft_list` does **not** expose `holding_short_t`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_engine.py`:

```python


def test_hold_short_expires():
    state, _ = fold([HoldShort(callsign="b", runway="13", t=0.0)])
    assert state.aircraft["b"].holding_short == "13"
    state, _ = fold([NoOp(t=STALE_S["HOLD_SHORT"] - 1)], state)
    assert state.aircraft["b"].holding_short == "13"
    state, _ = fold([NoOp(t=STALE_S["HOLD_SHORT"] + 1)], state)
    assert (state.aircraft["b"].holding_short, state.aircraft["b"].holding_short_t) == (None, None)


def test_vacating_or_leaving_the_frequency_ends_a_hold_short():
    for release in (RunwayVacated(callsign="b"), Handoff(callsign="b", to="ground"), Handoff(callsign="b", to="departure")):
        state, _ = fold([HoldShort(callsign="b", runway="13"), release])
        assert state.aircraft["b"].holding_short is None, release
    state, _ = fold([HoldShort(callsign="b", runway="13"), Handoff(callsign="b", to="tower")])
    assert state.aircraft["b"].holding_short == "13"


def test_hold_short_cancels_the_aircrafts_clearance_for_that_runway():
    state, _ = fold([ClearToCross(callsign="b", runway="13"), HoldShort(callsign="b", runway="13")])
    assert _kinds(state, "13") == []
    assert (state.aircraft["b"].runway, state.aircraft["b"].kind, state.aircraft["b"].holding_short) == (None, None, "13")
    _, c = fold([ClearToCross(callsign="b", runway="13"), HoldShort(callsign="b", runway="13"), ClearToLand(callsign="a", runway="13")])
    assert c == []


def test_hold_short_of_another_runway_keeps_the_crossing():
    # Recording 528: "air france one nine eight romeo ... cross runway one three continue via delta to hold short of runway
    # two four" parses to a CROSS on 13 followed by a HOLD_SHORT of 24. The crossing must survive the second event.
    state, c = fold([ClearToCross(callsign="af", runway="13"), HoldShort(callsign="af", runway="24"),
                     ClearToLand(callsign="csa", runway="13")])
    assert _kinds(state, "13") == [("af", "CROSS"), ("csa", "LAND")]
    assert [(x.type, x.severity, x.runway) for x in c] == [("RUNWAY", "alert", "13")]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_engine.py -q`
Expected: FAIL — 3 failures: `test_hold_short_expires` (`AttributeError: 'Aircraft' object has no attribute 'holding_short_t'` or the hold-short never clears), `test_vacating_or_leaving_the_frequency_ends_a_hold_short`, `test_hold_short_cancels_the_aircrafts_clearance_for_that_runway`. `test_hold_short_of_another_runway_keeps_the_crossing` already passes; it guards against over-releasing.

- [ ] **Step 3: Write minimal implementation**

In `atcdb/engine.py`, replace:

```python
    holding_short: str | None = None   # runway it was told to hold short of
```

with:

```python
    holding_short: str | None = None   # runway it was told to hold short of
    holding_short_t: float | None = None   # transmission time of that instruction; drives its staleness
```

In `atcdb/engine.py`, replace:

```python
    """Copy of the runway map and aircraft map with reservations older than their kind's STALE_S removed."""
    runways, aircraft = {}, dict(state.aircraft)
    for rwy, res in state.runways.items():
```

with:

```python
    """Copy of the runway map and aircraft map with reservations and hold-shorts older than their STALE_S removed."""
    runways, aircraft = {}, dict(state.aircraft)
    for cs, a in aircraft.items():
        if a.holding_short and a.holding_short_t is not None and now - a.holding_short_t > STALE_S["HOLD_SHORT"]:
            aircraft[cs] = replace(a, holding_short=None, holding_short_t=None)
    for rwy, res in state.runways.items():
```

In `atcdb/engine.py`, replace:

```python
def _release(runways: dict[str, tuple[Reservation, ...]], callsign: str,
             kinds: tuple[str, ...] = RESERVATION_KINDS) -> tuple[dict[str, tuple[Reservation, ...]], bool]:
    """Drop `callsign`'s reservations of the given kinds. Returns (new runways, whether anything was dropped)."""
    out, dropped = {}, False
    for rwy, res in runways.items():
        keep = tuple(r for r in res if not (r.callsign == callsign and r.kind in kinds))
```

with:

```python
def _release(runways: dict[str, tuple[Reservation, ...]], callsign: str, kinds: tuple[str, ...] = RESERVATION_KINDS,
             runway: str | None = None) -> tuple[dict[str, tuple[Reservation, ...]], bool]:
    """Drop `callsign`'s reservations of the given kinds (only on `runway`, if given). Returns (new runways, whether
    anything was dropped)."""
    out, dropped = {}, False
    for rwy, res in runways.items():
        keep = tuple(r for r in res if not (r.callsign == callsign and r.kind in kinds and runway in (None, rwy)))
```

In `atcdb/engine.py`, replace:

```python
            aircraft[cs] = replace(ac, runway=event.runway, kind=event.kind, holding_short=None,
                                   pending=event.text or ac.pending, last_seq=seq)
    elif isinstance(event, HoldShort):
        if cs:
            aircraft[cs] = replace(ac, holding_short=event.runway, pending=event.text or ac.pending, last_seq=seq)
    elif isinstance(event, RunwayVacated):
        runways, _ = _release(runways, cs) if cs else (runways, False)
        if cs:
            aircraft[cs] = replace(ac, runway=None, kind=None, last_seq=seq)
```

with:

```python
            aircraft[cs] = replace(ac, runway=event.runway, kind=event.kind, holding_short=None, holding_short_t=None,
                                   pending=event.text or ac.pending, last_seq=seq)
    elif isinstance(event, HoldShort):
        if cs:
            # "hold short runway 13" cancels this aircraft's clearance for 13; a hold-short of another runway releases
            # nothing (a crossing clearance for 13 often ends "... hold short of runway 24").
            runways, dropped = _release(runways, cs, runway=event.runway)
            aircraft[cs] = replace(ac, runway=None if dropped else ac.runway, kind=None if dropped else ac.kind,
                                   holding_short=event.runway, holding_short_t=event.t,
                                   pending=event.text or ac.pending, last_seq=seq)
    elif isinstance(event, RunwayVacated):
        runways, _ = _release(runways, cs) if cs else (runways, False)
        if cs:
            aircraft[cs] = replace(ac, runway=None, kind=None, holding_short=None, holding_short_t=None, last_seq=seq)
```

In `atcdb/engine.py`, replace:

```python
        kinds = {"ground": ("LAND", "CROSS"), "departure": ("TAKEOFF",)}.get(event.to, ())
        runways, dropped = _release(runways, cs, kinds) if cs and kinds else (runways, False)
        if cs:
            aircraft[cs] = replace(ac, runway=None if dropped else ac.runway, kind=None if dropped else ac.kind,
                                   pending=event.text or ac.pending, last_seq=seq)
```

with:

```python
        kinds = {"ground": ("LAND", "CROSS"), "departure": ("TAKEOFF",)}.get(event.to, ())
        runways, dropped = _release(runways, cs, kinds) if cs and kinds else (runways, False)
        if cs:
            leaving = event.to in ("ground", "departure")   # off the tower's runways: any hold-short no longer applies
            aircraft[cs] = replace(ac, runway=None if dropped else ac.runway, kind=None if dropped else ac.kind,
                                   holding_short=None if leaving else ac.holding_short,
                                   holding_short_t=None if leaving else ac.holding_short_t,
                                   pending=event.text or ac.pending, last_seq=seq)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest -q`
Expected: PASS — 166 passed.

- [ ] **Step 5: Commit**

```bash
git add atcdb/engine.py tests/test_engine.py
git commit -m "feat: hold-shorts expire, end on release, and cancel a clearance for the same runway"
```

---

### Task 4: Readback conflicts name a runway; handoff targets are validated

A READBACK conflict today carries `ac.runway`, which is `None` for an aircraft that is only holding short, so a runway-readback alert highlights no card. It now carries the missed runway item's own value, else the aircraft's reservation runway, else its hold-short runway. Separately, `Handoff.to` is checked against `HANDOFF_TARGETS`: an unknown target (an LLM typo such as `grund`) still releases nothing, as today, but is counted in a new `State.ignored`, which Task 5 surfaces.

**Files:**
- Modify: `atcdb/engine.py` (`HANDOFF_TARGETS`, `Handoff`, `State`, `apply`)
- Test: `tests/test_engine.py`

**Interfaces:**
- Consumes: `Aircraft.holding_short` (existing).
- Produces: `HANDOFF_TARGETS = ("ground", "departure", "tower", "approach")`; `State.ignored: int` — the cumulative number of events the engine received but could not act on. Task 5 reads it as a before/after difference per transmission.

- [ ] **Step 1: Write the failing tests**

In `tests/test_engine.py`, replace:

```python
from atcdb.engine import (ClearTakeoff, ClearToCross, ClearToLand, Event, GoAround, Handoff, HoldShort,
```

with:

```python
from atcdb.engine import (ClearTakeoff, ClearToCross, ClearToLand, Event, GoAround, Handoff, HANDOFF_TARGETS, HoldShort,
```

Append to `tests/test_engine.py`:

```python


def test_readback_conflict_names_the_runway_that_was_missed():
    hold = HoldShort(callsign="b", runway="13", text="b hold short of runway one three")
    _, c = fold([hold, ReadbackObserved(callsign="b", text="holding short runway three one b")])
    assert [(x.type, x.severity, x.runway) for x in c] == [("READBACK", "alert", "13")]   # was None before phase 2.5


def test_readback_conflict_falls_back_to_the_hold_short_runway():
    hold = HoldShort(callsign="b", runway="13", text="b hold short of runway one three contact ground one two one nine")
    _, c = fold([hold, ReadbackObserved(callsign="b", text="holding short runway one three one two one five b")])
    assert [(x.type, x.severity, x.runway) for x in c] == [("READBACK", "warning", "13")]


def test_unknown_handoff_target_releases_nothing_and_is_counted():
    assert HANDOFF_TARGETS == ("ground", "departure", "tower", "approach")
    state, c = fold([ClearToLand(callsign="a", runway="31"), Handoff(callsign="a", to="grund"), ClearToCross(callsign="b", runway="31")])
    assert [x.severity for x in c] == ["alert"] and state.ignored == 1
    state, _ = fold([ClearToLand(callsign="a", runway="31"), Handoff(callsign="a", to="ground")])
    assert state.ignored == 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_engine.py -q`
Expected: FAIL — `ImportError: cannot import name 'HANDOFF_TARGETS'` (the whole module fails to collect).

- [ ] **Step 3: Write minimal implementation**

In `atcdb/engine.py`, replace:

```python
@dataclass(frozen=True, kw_only=True)
class Handoff(Event):
    to: str              # ground | departure | tower | approach
```

with:

```python
HANDOFF_TARGETS = ("ground", "departure", "tower", "approach")


@dataclass(frozen=True, kw_only=True)
class Handoff(Event):
    to: str              # one of HANDOFF_TARGETS; anything else releases nothing and is counted in State.ignored
```

In `atcdb/engine.py`, replace:

```python
    aircraft: dict[str, Aircraft] = field(default_factory=dict)
```

with:

```python
    aircraft: dict[str, Aircraft] = field(default_factory=dict)
    ignored: int = 0     # events so far that the engine received but could not act on (unknown handoff target)
```

In `atcdb/engine.py`, replace:

```python
    conflicts: list[Conflict] = []
    cs = event.callsign
```

with:

```python
    conflicts: list[Conflict] = []
    ignored = state.ignored
    cs = event.callsign
```

In `atcdb/engine.py`, replace:

```python
        kinds = {"ground": ("LAND", "CROSS"), "departure": ("TAKEOFF",)}.get(event.to, ())
```

with:

```python
        if event.to not in HANDOFF_TARGETS:   # releases nothing, but the fold counts it (spec addendum A.3.4)
            ignored += 1
        kinds = {"ground": ("LAND", "CROSS"), "departure": ("TAKEOFF",)}.get(event.to, ())
```

In `atcdb/engine.py`, replace:

```python
                severity = "alert" if any(k == "runway" for k, _ in missing) else "warning"
                what = ", ".join(f"{k} {v}" for k, v in missing)
                conflicts.append(Conflict(
                    "READBACK", severity, ac.runway, (cs,), seq,
```

with:

```python
                severity = "alert" if any(k == "runway" for k, _ in missing) else "warning"
                what = ", ".join(f"{k} {v}" for k, v in missing)
                missed_runway = next((normalize_runway(v) for k, v in missing if k == "runway"), None)
                conflicts.append(Conflict(
                    "READBACK", severity, missed_runway or ac.runway or ac.holding_short, (cs,), seq,
```

In `atcdb/engine.py`, replace:

```python
    return State(seq=seq, runways=runways, aircraft=aircraft), conflicts
```

with:

```python
    return State(seq=seq, runways=runways, aircraft=aircraft, ignored=ignored), conflicts
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest -q`
Expected: PASS — 169 passed.

- [ ] **Step 5: Commit**

```bash
git add atcdb/engine.py tests/test_engine.py
git commit -m "feat: readback conflicts name their runway; unknown handoff targets are counted"
```

---

### Task 5: Dropped-instruction counter

Spec A.3.5 wants each replay step to report instructions that were lost: ones the parser recognised but could not place on a runway, plus events the engine ignored (Task 4). The parser-side count cannot live inside `parse` — the rules parser is frozen at v1 — so it is a separate diagnostic, `count_unresolved(tx, ctx)`, that re-runs the same instruction patterns without changing what `parse` returns. `replay.py` looks it up per parser in `DROP_COUNTERS` (a parser with no entry counts 0; phase 3a registers the Claude parser's own), adds the engine's `State.ignored` delta, and stores the total on `Step.dropped`. It is computed on every replay, cache hit or not, because it is not stored in the `events` cache. On the corpus in `window` mode it totals 3 across 2,035 events: snapping to the one active runway rescues most runway-less clearances.

**Files:**
- Modify: `atcdb/parse_rules.py` (new `count_unresolved` directly above `parse`), `atcdb/replay.py`, `atcdb/serialize.py`
- Test: `tests/test_parse_rules.py`, `tests/test_replay.py`, `tests/test_serialize.py`

**Interfaces:**
- Consumes: `State.ignored` (Task 4).
- Produces: `parse_rules.count_unresolved(tx: Transmission, ctx: Context) -> int`; `replay.DROP_COUNTERS: dict[str, Callable[[Transmission, Context], int]]`; `Step.dropped: int = 0`; `Timeline.dropped` (property, the sum over steps); `step_dict(...)["dropped"]` and `timeline_dict(...)["dropped"]`.

- [ ] **Step 1: Write the failing tests**

In `tests/test_parse_rules.py`, replace:

```python
from atcdb.parse_rules import VERSION, blank_values, parse, pilot_callsign, snap_callsign, take_prefix, take_suffix
```

with:

```python
from atcdb.parse_rules import (VERSION, blank_values, count_unresolved, parse, pilot_callsign, snap_callsign, take_prefix,
                               take_suffix)
```

Append to `tests/test_parse_rules.py`:

```python


def test_count_unresolved_counts_instructions_with_no_runway():
    # Austin 2023, 0634:14: the landing clearance carries no "runway" token, so v1 cannot place it.
    austin = _tx("fedex fourteen thirty-two heavy austin tower one eight left cleared to land")
    assert parse(austin, CTL) == [NoOp(t=0.0, text=austin.text)]
    assert count_unresolved(austin, CTL) == 1
    assert count_unresolved(_tx("csa one two three runway three one cleared to land"), CTL) == 0
    assert count_unresolved(_tx("csa one two three cleared to land"), PLT) == 0              # pilots issue no instructions
    assert count_unresolved(_tx("csa one two three line up and wait cleared for takeoff"), CTL) == 2


def test_count_unresolved_follows_window_snapping():
    # With exactly one active runway, window mode places the clearance, so nothing is dropped.
    tx = _tx("fedex fourteen thirty-two heavy one eight left cleared to land")
    window = Context(mode="window", role="controller", active_runways=("18L",))
    assert _kinds(parse(tx, window)) == [("ClearToLand", "", "18L")]   # placed; the US callsign is a known v1 gap
    assert count_unresolved(tx, window) == 0
```

In `tests/test_replay.py`, replace:

```python
from atcdb.engine import ClearToLand, NoOp, ReadbackObserved, State, fold
```

with:

```python
from atcdb.engine import ClearToLand, Handoff, NoOp, ReadbackObserved, State, fold
```

Append to `tests/test_replay.py`:

```python


def test_build_timeline_counts_dropped_instructions(tmp_path):
    conn = init_db(tmp_path / "t.sqlite")
    rid = _seed(conn, [("controller", "csa one two three cleared to land"),                  # no runway anywhere: dropped
                       ("controller", "lufthansa four five six runway three one cleared for takeoff")])
    tl = build_timeline(conn, rid, context="role")
    assert [s.dropped for s in tl.steps] == [1, 0] and tl.dropped == 1


def test_build_timeline_counts_events_the_engine_ignored(tmp_path, monkeypatch):
    conn = init_db(tmp_path / "t.sqlite")
    rid = _seed(conn, [("controller", "a contact grund one two one nine")])
    monkeypatch.setitem(PARSERS, "rule", _fake_parser({"a contact grund one two one nine": [Handoff(callsign="a", to="grund")]}, []))
    tl = build_timeline(conn, rid, context="role")
    assert tl.steps[0].dropped == 1
```

In `tests/test_serialize.py`, replace:

```python
    assert d["index"] == 3 and d["error"] is None
```

with:

```python
    assert d["index"] == 3 and d["error"] is None and d["dropped"] == 0
```

In `tests/test_serialize.py`, replace:

```python
        "transcript_kind": "gold", "transcript_model": "human", "runways": ["24", "31"]}
```

with:

```python
        "transcript_kind": "gold", "transcript_model": "human", "runways": ["24", "31"], "dropped": 0}
```

Append to `tests/test_serialize.py`:

```python


def test_dropped_counts_are_serialised_per_step_and_in_total():
    tl = Timeline(recording_id=5, parser="rule", model="rules", model_version="v1", context="window", transcript_kind="gold",
                  steps=(Step(tx=TX, events=(), conflicts=(), state=State(), dropped=1),
                         Step(tx=TX, events=(), conflicts=(), state=State(), dropped=2)))
    d = timeline_dict(tl, {"id": 5}, "human")
    assert [s["dropped"] for s in d["steps"]] == [1, 2] and d["dropped"] == 3
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_parse_rules.py tests/test_replay.py tests/test_serialize.py -q`
Expected: FAIL — `ImportError: cannot import name 'count_unresolved'`, and `TypeError: Step.__init__() got an unexpected keyword argument 'dropped'`.

- [ ] **Step 3: Write minimal implementation**

In `atcdb/parse_rules.py`, replace:

```python
def parse(tx: Transmission, ctx: Context) -> list[Event]:
```

with:

```python
def count_unresolved(tx: Transmission, ctx: Context) -> int:
    """How many instruction kinds `parse` recognised in this transmission but dropped because no runway could be placed
    on them (spec addendum A.3.5). A diagnostic beside `parse`, not part of it: `parse`'s output is unchanged, so VERSION
    stays v1 and the frozen baseline is untouched. Pilot transmissions never yield instructions, so they count 0."""
    role = ctx.role if ctx.mode != "none" else "unknown"
    if role == "pilot":
        return 0
    placed, unplaced = set(), set()
    for kind, rx in INSTRUCTION_RES:
        for m in rx.finditer(tx.text):
            (placed if _runway_for(tx.text, m, kind, ctx) else unplaced).add(kind)
    return len(unplaced - placed)


def parse(tx: Transmission, ctx: Context) -> list[Event]:
```

In `atcdb/replay.py`, replace:

```python
import sqlite3
from dataclasses import dataclass
```

with:

```python
import sqlite3
from dataclasses import dataclass
from typing import Callable
```

In `atcdb/replay.py`, replace:

```python
PARSER_MODELS: dict[str, tuple[str, str]] = {"rule": ("rules", parse_rules.VERSION)}   # parser -> (model, model_version)
```

with:

```python
PARSER_MODELS: dict[str, tuple[str, str]] = {"rule": ("rules", parse_rules.VERSION)}   # parser -> (model, model_version)
# parser -> instructions it recognised but could not place on a runway, for one transmission (spec addendum A.3.5)
DROP_COUNTERS: dict[str, Callable[[Transmission, Context], int]] = {"rule": parse_rules.count_unresolved}
```

In `atcdb/replay.py`, replace:

```python
    error: str | None = None          # parser failure: events are empty and the fold simply continued
```

with:

```python
    error: str | None = None          # parser failure: events are empty and the fold simply continued
    dropped: int = 0                  # instructions lost at this step: unplaceable runway, or ignored by the engine
```

In `atcdb/replay.py`, replace:

```python
    transcript_kind: str
    steps: tuple[Step, ...]
```

with:

```python
    transcript_kind: str
    steps: tuple[Step, ...]

    @property
    def dropped(self) -> int:
        return sum(s.dropped for s in self.steps)
```

In `atcdb/replay.py`, replace:

```python
        conflicts: list[Conflict] = []
        for e in events:
            state, new = apply(state, e)
            conflicts.extend(new)
        steps.append(Step(tx=tx, events=tuple(events), conflicts=tuple(conflicts), state=state, error=error))
```

with:

```python
        conflicts: list[Conflict] = []
        ignored_before = state.ignored
        for e in events:
            state, new = apply(state, e)
            conflicts.extend(new)
        dropped = DROP_COUNTERS.get(parser, lambda tx, ctx: 0)(tx, ctx) + state.ignored - ignored_before
        steps.append(Step(tx=tx, events=tuple(events), conflicts=tuple(conflicts), state=state, error=error, dropped=dropped))
```

In `atcdb/serialize.py`, replace:

```python
            "conflicts": [conflict_dict(c) for c in step.conflicts], "error": step.error,
```

with:

```python
            "conflicts": [conflict_dict(c) for c in step.conflicts], "error": step.error, "dropped": step.dropped,
```

In `atcdb/serialize.py`, replace:

```python
            "runways": runways_named(tl), "steps": [step_dict(i, s) for i, s in enumerate(tl.steps)]}
```

with:

```python
            "runways": runways_named(tl), "dropped": tl.dropped, "steps": [step_dict(i, s) for i, s in enumerate(tl.steps)]}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest -q`
Expected: PASS — 174 passed.

- [ ] **Step 5: Commit**

```bash
git add atcdb/parse_rules.py atcdb/replay.py atcdb/serialize.py tests/test_parse_rules.py tests/test_replay.py tests/test_serialize.py
git commit -m "feat: count dropped instructions per replay step"
```

---

### Task 6: The ICAO basis for each rule

`phraseology_rules` exists in the schema and has always been empty. It is now seeded by `init_db` from a new data-only module, `atcdb/doctrine.py`: one row per rule the engine applies, citing the ICAO Doc 4444 (PANS-ATM, 16th edition, Chapter 7) paragraph it derives from, or marked an engineering heuristic with no regulatory basis. The paragraph wording in the descriptions is quoted from Doc 4444; do not paraphrase it further. Each RUNWAY conflict carries `basis`, the id of the row its matrix cell rests on, where one exists; the explanation strings are unchanged. Only cells with a verified citation get one.

**Files:**
- Create: `atcdb/doctrine.py`, `tests/test_doctrine.py`
- Modify: `atcdb/schema.py` (`init_db`), `atcdb/engine.py` (`Conflict`, `MATRIX_BASIS`, RUNWAY conflict construction), `atcdb/serialize.py` (`conflict_dict`)
- Test: `tests/test_engine.py`, `tests/test_serialize.py`

**Interfaces:**
- Consumes: the `phraseology_rules` table (columns `id, document, section, category, pattern, description`).
- Produces: `doctrine.RULES: list[dict]`, `doctrine.DOC_4444`, `doctrine.HEURISTIC`, `doctrine.seed(conn) -> None`; `engine.MATRIX_BASIS: dict[tuple[str, str], str]`; `Conflict.basis: str | None = None`; `conflict_dict(...)["basis"]`. Task 7's Austin test asserts `basis == "icao-4444-7.10.1"`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_doctrine.py`:

```python
from atcdb import doctrine
from atcdb.engine import MATRIX, MATRIX_BASIS
from atcdb.schema import init_db


def test_every_rule_has_the_schema_columns_and_a_unique_id():
    assert len({r["id"] for r in doctrine.RULES}) == len(doctrine.RULES)
    for r in doctrine.RULES:
        assert set(r) == {"id", "document", "section", "category", "pattern", "description"}
        assert (r["section"] is None) == (r["document"] == doctrine.HEURISTIC)   # a heuristic cites no paragraph


def test_every_matrix_citation_names_a_rule_and_a_real_cell():
    ids = {r["id"] for r in doctrine.RULES}
    assert set(MATRIX_BASIS) <= set(MATRIX)
    assert set(MATRIX_BASIS.values()) <= ids


def test_init_db_seeds_phraseology_rules_idempotently(tmp_path):
    conn = init_db(tmp_path / "t.sqlite")
    conn = init_db(tmp_path / "t.sqlite")   # a second open must not duplicate or fail
    rows = conn.execute("SELECT id, document, section FROM phraseology_rules ORDER BY id").fetchall()
    assert len(rows) == len(doctrine.RULES)
    assert ("icao-4444-7.9.2", doctrine.DOC_4444, "7.9.2") in [tuple(r) for r in rows]
```

Append to `tests/test_engine.py`:

```python


def test_runway_conflicts_carry_their_doctrine_basis():
    _, c = fold([ClearToLand(callsign="fedex", runway="18L"), ClearTakeoff(callsign="southwest", runway="18L")])
    assert [x.basis for x in c] == ["icao-4444-7.9.2"]
    _, c = fold([ClearTakeoff(callsign="southwest", runway="18L"), ClearToLand(callsign="fedex", runway="18L")])
    assert [x.basis for x in c] == ["icao-4444-7.10.1"]
    _, c = fold([ClearToLand(callsign="a", runway="31"), ClearToCross(callsign="b", runway="31")])
    assert [x.basis for x in c] == [None]   # no verified citation for this cell yet
```

In `tests/test_serialize.py`, replace:

```python
    assert "runway 31" in d["conflicts"][0]["explanation"]
```

with:

```python
    assert "runway 31" in d["conflicts"][0]["explanation"]
    assert d["conflicts"][0]["basis"] is None   # LAND against a held LUAW has no verified ICAO citation
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_doctrine.py tests/test_engine.py tests/test_serialize.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'atcdb.doctrine'` and `ImportError: cannot import name 'MATRIX_BASIS'`.

- [ ] **Step 3: Write minimal implementation**

Create `atcdb/doctrine.py`:

```python
"""The regulatory basis for the engine's rules, stored in `phraseology_rules` (spec addendum A.3.8).

Each rule the engine applies either cites the ICAO Doc 4444 (PANS-ATM) paragraph it encodes or is marked an
engineering heuristic with no regulatory basis. The engine detects incompatible clearances, a proxy for the physical
separation Doc 4444 actually governs, so citations say what a rule is derived from, not that the engine enforces it.
Wording is quoted from Doc 4444, 16th edition, Chapter 7.
"""
import sqlite3

DOC_4444 = "ICAO Doc 4444 (PANS-ATM)"
HEURISTIC = "engineering heuristic"

RULES: list[dict] = [
    {"id": "icao-4444-7.10.2", "document": DOC_4444, "section": "7.10.2", "category": "reservation", "pattern": "LAND",
     "description": "An aircraft may be cleared to land when there is reasonable assurance that the separation in 7.10.1 "
                    "will exist when the aircraft crosses the runway threshold. Basis for: a landing clearance reserves "
                    "the runway."},
    {"id": "icao-4444-7.9.3.1", "document": DOC_4444, "section": "7.9.3.1", "category": "reservation", "pattern": "TAKEOFF",
     "description": "Take-off clearance may be issued when there is reasonable assurance that the separation in 7.9.2 "
                    "will exist when the aircraft commences take-off. Basis for: a take-off clearance reserves the runway."},
    {"id": "icao-4444-7.10.2-proviso", "document": DOC_4444, "section": "7.10.2", "category": "compatibility",
     "pattern": "LAND/LAND",
     "description": "A clearance to land shall not be issued until a preceding landing aircraft has crossed the runway "
                    "threshold, so successive landing clearances are lawful. Basis for: LAND after LAND is not a conflict."},
    {"id": "icao-4444-7.9.2", "document": DOC_4444, "section": "7.9.2", "category": "compatibility", "pattern": "TAKEOFF/LAND",
     "description": "A departing aircraft will not normally be permitted to commence take-off until the preceding departing "
                    "aircraft has crossed the end of the runway-in-use or has started a turn or until all preceding "
                    "landing aircraft are clear of the runway-in-use. Basis for: a take-off clearance against a held "
                    "landing clearance is an alert."},
    {"id": "icao-4444-7.10.1", "document": DOC_4444, "section": "7.10.1", "category": "compatibility", "pattern": "LAND/TAKEOFF",
     "description": "A landing aircraft will not normally be permitted to cross the runway threshold on its final approach "
                    "until the preceding departing aircraft has crossed the end of the runway-in-use, or has started a "
                    "turn, or until all preceding landing aircraft are clear of the runway-in-use. Basis for: a landing "
                    "clearance against a held take-off clearance is an alert."},
    {"id": "heuristic-handoff-release", "document": HEURISTIC, "section": None, "category": "release", "pattern": "HANDOFF",
     "description": "A handoff to ground releases LAND and CROSS; a handoff to departure releases TAKEOFF. No ICAO basis: "
                    "7.9.2 and 7.10.1 turn on the preceding aircraft being clear of the runway-in-use, which the "
                    "controller observes and never transmits. The handoff is the transmitted proxy."},
    {"id": "heuristic-staleness", "document": HEURISTIC, "section": None, "category": "release", "pattern": "STALE_S",
     "description": "A reservation older than its kind's timeout is dropped silently. No ICAO basis: a fallback for release "
                    "calls that were never transmitted."},
]


def seed(conn: sqlite3.Connection) -> None:
    """Write RULES into `phraseology_rules`. Idempotent: rows are replaced by id."""
    conn.executemany("INSERT OR REPLACE INTO phraseology_rules (id, document, section, category, pattern, description) "
                     "VALUES (:id, :document, :section, :category, :pattern, :description)", RULES)
    conn.commit()
```

In `atcdb/schema.py`, replace:

```python
import sqlite3
from pathlib import Path
```

with:

```python
import sqlite3
from pathlib import Path

from atcdb import doctrine
```

In `atcdb/schema.py`, replace:

```python
    conn = connect(path)
    conn.executescript(SCHEMA_SQL)
    conn.commit()
    return conn
```

with:

```python
    conn = connect(path)
    conn.executescript(SCHEMA_SQL)
    conn.commit()
    doctrine.seed(conn)
    return conn
```

In `atcdb/engine.py`, replace:

```python
    seq: int                     # seq of the triggering event
    explanation: str             # what the app displays
```

with:

```python
    seq: int                     # seq of the triggering event
    explanation: str             # what the app displays
    basis: str | None = None     # id of the phraseology_rules row this conflict rests on (atcdb/doctrine.py), if any
```

In `atcdb/engine.py`, replace:

```python
_PHRASE = {"LAND": "a landing clearance",
```

with:

```python
# (new_kind, active_kind) -> the atcdb/doctrine.py rule that cell encodes. Cells without an entry have no verified citation.
MATRIX_BASIS: dict[tuple[str, str], str] = {
    ("LAND", "LAND"): "icao-4444-7.10.2-proviso",
    ("TAKEOFF", "LAND"): "icao-4444-7.9.2",
    ("LAND", "TAKEOFF"): "icao-4444-7.10.1",
}

_PHRASE = {"LAND": "a landing clearance",
```

In `atcdb/engine.py`, replace:

```python
                f"{_name(r.callsign)} still holds {_PHRASE[r.kind]} on runway {event.runway}"))
```

with:

```python
                f"{_name(r.callsign)} still holds {_PHRASE[r.kind]} on runway {event.runway}",
                MATRIX_BASIS.get((event.kind, r.kind))))
```

In `atcdb/serialize.py`, replace:

```python
            "explanation": c.explanation}
```

with:

```python
            "explanation": c.explanation, "basis": c.basis}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest -q`
Expected: PASS — 178 passed.

- [ ] **Step 5: Commit**

```bash
git add atcdb/doctrine.py atcdb/schema.py atcdb/engine.py atcdb/serialize.py tests/test_doctrine.py tests/test_engine.py tests/test_serialize.py
git commit -m "feat: cite the ICAO Doc 4444 basis for each engine rule"
```

---

### Task 7: Real incidents as regression fixtures

Two incidents pin the frozen rules-parser baseline (spec A.2, A.3.9). **Austin 2023** is the NTSB's verbatim tower transcript, committed as a fixture: the engine models the incursion, but v1 drops the 0634:14 landing clearance (no "runway" token), raises nothing at 0638:58 when the conflicting takeoff clearance is issued, and fires only at the 0639:34 re-confirmation, capped at warning because the US callsign does not parse. **Corpus recording 528** is a correct parse that raises a false alert (Air France has finished crossing 13, but nobody says so). These are characterisation tests: they record findings the evaluation reports, and they pass as soon as they are written.

The fixture was generated from the PDF's text layer (`pdftotext -raw` on NTSB DCA23FA149, Attachment 1), with page footers removed, wrapped lines rejoined and curly quotes normalised; its 94 transmissions were checked against the source. Copy it exactly.

**Files:**
- Create: `tests/fixtures/austin_dca23fa149.txt`, `tests/test_incidents.py`

**Interfaces:**
- Consumes: `parse_rules.parse`, `parse_rules.count_unresolved` (Task 5), `replay.build_context`, `replay.load_recording`, `engine.apply`, `Conflict.basis` (Task 6).
- Produces: nothing other tasks use.

- [ ] **Step 1: Create the Austin fixture**

Create `tests/fixtures/austin_dca23fa149.txt`:

```text
# NTSB DCA23FA149, Group Chair's Factual Report, Attachment 1: ATC Audio Transcript (partial), transcribed 5 June 2023.
# Runway incursion at Austin-Bergstrom (KAUS), 4 February 2023: FedEx 1432 (FDX1432) cleared to land runway 18L,
# Southwest 708 (SWA708) then cleared for takeoff on 18L. US government public record.
# Generated from the PDF's text layer (pdftotext -raw); page footers removed, wrapped lines rejoined, curly quotes
# and dashes normalised to ASCII. Format: time|ident|transmission. Times are CST (HHMM:SS); a blank time is a line the
# NTSB left untimed. AUS-LC / AUS-LCR are the local controller and the controller being relieved; UNK is unidentified.
0545:12|AUS-LCR|[intrafacility] alright
|AUS-LC|[intrafacility] hello
|AUS-LCR|[intrafacility] lets see here [indiscernible] i-l-s is one eight left and one eight right south flow very low visibility quarter mile but it's it's kinda like it's obscured at two hundred so yeah you can see like right down here but yeah whatever um so we need pireps all that good stuff the lights are all cranked up the rabbit and all that stuff um there's r-v-rs there's no special things and traffic is uh there's nothing for local that's it
|AUS-LC|[intrafacility] no questions
0545:44|AUS-LCR|[intrafacility] [indiscernible]
0547:52|AAL1913|tower american nineteen thirteens ready for takeoff one eight left
0547:59|AUS-LC|american nineteen thirteen austin tower fly heading one seven zero runway one eight left cleared for takeoff
0548:05|AAL1913|k heading one seven zero cleared for takeoff one eight left ya got the r-v-rs
0548:23|AAL1913|tower american nineteen thirteen ya have r-v-rs one eight left
0548:28|AUS-LC|i'm sorry who's that calling local
0548:31|AAL1913|american nineteen thirteen's asking for the r-v-rs on one eight left
0548:36|AUS-LC|american nineteen thirteen runway one eight left r-v-r is touchdown a thousand midpoint one thousand four hundred and rollout is one thousand eight hundred
0548:47|AAL1913|thank you american nineteen thirteen
0550:35|AUS-LC|american nineteen thirteen contact departure
0550:38|AAL1913|american nineteen thirteen good morning
0553:44|DAL1344|tower delta thirteen forty-four holding short runway one eight left ready for departure
0553:50|AUS-LC|delta thirteen forty-four austin tower runway one eight left r-v-r touchdown one thousand two hundred midpoint one thousand two hundred rollout one thousand two hundred fly heading one seven zero runway one eight left cleared for takeoff
0554:02|DAL1344|runway one eight left cleared for takeoff heading one seven zero delta thirteen forty-four
0556:01|SWA1881|tower southwest eighteen eighty-one we're uh one eight left ready
0556:06|AUS-LC|southwest eighteen eighty-one roger hold short
0556:09|SWA1881|holding short one eight left southwest eighteen eighty-one
0556:11|AUS-LC|delta thirteen forty-four contact departure
0556:14|DAL1344|departure delta thirteen forty-four good day
0556:17|AUS-LC|southwest eighteen eighty-one austin tower runway one eight left r-v-r touchdown one thousand eight hundred midpoint one thousand two hundred rollout one thousand two hundred fly heading one seven zero runway one eight left cleared for takeoff
0556:29|SWA1881|one seven zero heading on departure cleared for takeoff one eight left southwest eighteen eighty-one
0558:33|AUS-LC|southwest eighteen eighty-one contact departure have a good flight
0558:37|SWA1881|goin to departure southwest eighteen eighty-one good day
0559:17|SWA785|seven eighty-five we're all set at the end we're holding short one eight left
0559:21|AUS-LC|southwest eighteen eighty-one contact departure
0559:30|AUS-LC|southwest seven eighty-five austin tower runway one eight left r-v-r one thousand six hundred midpoint one thousand six hundred rollout one thousand two hundred fly heading one niner zero runway one eight left cleared for takeoff
0559:43|SWA785|alright copy all heading one ninety cleared for takeoff one eight left southwest seven eighty-five
0601:36|AUS-LC|southwest seven eighty-five contact departure
0601:39|SWA785|southwest seven eighty-five we'll see ya
0608:52|SKW4635|uh tower skywest forty-six thirty-five good morning approaching one eight right at charlie
0609:04|AUS-LC|skywest forty-six thirty-five austin tower runway one eight right r-v-r one thousand six hundred rollout two thousand fly heading one niner zero runway one eight right cleared for takeoff
0609:15|SKW4635|fly heading one niner zero one eight right cleared for takeoff skywest forty-six thirty-five
0611:07|AUS-LC|skywest forty-six thirty-five contact departure
0611:11|SKW4635|[indiscernible] skywest forty-six thirty-five [indiscernible]
0611:28|AAL2327|and tower american uh twenty-three twenty-seven holding short one eight left at bravo
0611:35|AUS-LC|american twenty-three twenty-seven austin tower one eight left r-v-r touchdown one thousand two hundred midpoint two thousand rollout one thousand four hundred fly heading one niner zero runway one eight left cleared for takeoff
0611:49|AAL2327|cleared for takeoff one eight left fly heading one nine zero copy r-v-rs american thirt uh twenty-three twenty-seven
0612:53|DAL422|tower delta four twenty-two uh what's the r-v-r for one eight right
0613:00|AUS-LC|runway one eight right r-v-r touchdown two thousand eight hundred rollout one thousand six hundred
0613:06|DAL422|thank you
0614:17|AUS-LC|american twenty-three twenty-seven contact departure
0614:20|AAL2327|departure american twenty-three twenty-seven
0615:26|AUS-LC|delta four twenty-two austin tower one eight right r-v-r touchdown two thousand four hundred rollout one thousand six hundred fly heading one niner zero runway one eight right cleared for takeoff
0615:37|DAL422|heading one niner zero one eight right cleared for takeoff delta four twenty-two
0616:51|AAL2549|hey good morning tower american twenty-five forty-nine we'll be ready at one eight left
0616:57|AUS-LC|roger
0617:01|AUS-LC|american twenty-five forty-nine austin tower one eight left r-v-r one touchdown one thousand two hundred rollout midpoint also one thousand two hundred fly heading one seven zero runway one eight left cleared for takeoff
0617:15|AAL2549|heading one seven zero one eight left cleared for takeoff american twenty-five forty-nine
0617:19|AUS-LC|delta four twenty-two contact departure
0617:21|DAL422|departure good day
0618:02|AUS-LC|delta four twenty-two contact departure
0619:08|AUS-LC|american twenty-five forty-nine contact departure
0619:11|AAL2549|departure american twenty-five forty-nine good morning
0622:44|SWA1542|tower southwest fifteen forty-twos ready at eighteen left
0622:54|AUS-LC|southwest fifteen forty-two austin tower runway one eight left r-v-r touchdown two thousand four hundred midpoint eight hundred rollout one thousand six hundred fly heading one seven zero runway one eight left cleared for takeoff
0623:08|SWA1542|[indiscernible] one seven zero degrees one eight left cleared for takeoff southwest fifteen forty-two
0624:37|AUS-LC|southwest fifteen forty-two contact departure
0624:40|SWA1542|departure fifteen forty-two see ya
0628:26|NKS1145|and tower spirit wings eleven forty-five uh on charlie gonna be holding short one eight right we're ready to go
0628:41|AUS-LC|spirit wings eleven forty-five austin tower one eight right r-v-r touchdown one thousand two hundred rollout one thousand six hundred fly heading one niner zero runway one eight right cleared for takeoff
0628:51|NKS1145|alright fly heading one nine zero one eight right cleared for takeoff spirit wings eleven forty-five
0631:36|NKS1145|[indiscernible] departure spirit uh eleven forty-five
0631:42|AUS-LC|spirit eleven forty-five contact departure have a good mornin
0631:45|NKS1145|good morning
0631:46|UNK|how far out for you do you want me to push this just a few feet
0631:50|AUS-LC|you're on local
0634:02|FDX1432|austin tower fedex fourteen thirty-two heavy passing five point four [break in transmission] [indiscernible] cat three i-l-s runway one eight left
0634:14|AUS-LC|fedex fourteen thirty-two heavy austin tower one eight left r-v-r touchdown one thousand four hundred midpoint six hundred rollout one thousand eight hundred one eight left cleared to land
0634:25|FDX1432|cleared to land one eight left fedex fourteen thirty-two heavy
0638:47|SWA708|tower southwest seven o eight we're short of one eight left we're ready
0638:58|AUS-LC|southwest seven zero eight austin tower runway one eight left r-v-r one thousand two hundred midpoint six hundred rollout one thousand six hundred fly heading one seven zero runway one eight left cleared for takeoff traffic three mile final is a heavy seven sixty-seven
0639:13|SWA708|okay that's one seven zero cleared for takeoff one eight left copy the traffic southwest seven zero eight
0639:29|FDX1432|tower confirm uh fedex fourteen thirty-two heavy's cleared to land on the one eight left
0639:34|AUS-LC|fedex fourteen thirty-two heavy that is affirmative one eight left you are cleared to land traffic departing prior to your arrival's a seven thirty-seven
0639:40|FDX1432|roger
0640:10|AUS-LC|southwest seven zero eight confirm on the roll
0640:13|SWA708|rollin now
0640:31|FDX1432|southwest abort
0640:34|FDX1432|fedex is on the go
0640:44|AUS-LC|southwest seven zero eight roger you can turn right when able
0640:49|SWA708|negative
0641:06|AUS-LC|fedex fourteen thirty-two climb maintain three thousand when able you can turn left heading zero eight zero
0641:12|FDX1432|we're in the turn to zero eight zero three thousand fedex fourteen thirty-two heavy
0641:39|AUS-LC|southwest seven zero eight you can turn uh left heading one seven zero
0641:42|SWA708|one seventy southwest seven o eight
0641:44|AUS-LC|fedex fourteen thirty-two turn left heading three six zero contact approach on one two five point three two
0641:55|FDX1432|twenty-five thirty-two left three six zero fedex fourteen thirty-two heavy
0642:00|AUS-LC|i'm sorry who was that
0642:12|AUS-LC|southwest seven zero eight you can contact departure
0642:14|SWA708|seven o eight
```

- [ ] **Step 2: Write the incident tests**

Create `tests/test_incidents.py`:

```python
"""Real incidents replayed through the rules parser and the engine (spec addendum A.3.9).

Austin is NTSB public record and is committed as a fixture. Recording 528 comes from the UWB-ATCC corpus (CC BY-NC-ND),
which is not redistributed, so its test reads the local corpus DB read-only and skips without it. Both pin the frozen
rules-parser baseline (parse_rules v1, spec addendum A.7): these are findings the evaluation reports, not bugs to fix.
"""
import re
import sqlite3
from pathlib import Path

import pytest

from atcdb import parse_rules
from atcdb.engine import Conflict, State, apply
from atcdb.parsing import Transmission
from atcdb.replay import build_context, load_recording

FIXTURES = Path(__file__).parent / "fixtures"
CORPUS = Path(__file__).resolve().parents[1] / "data" / "atc.sqlite"


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


def fold_rules(txs: list[Transmission]) -> list[tuple[list[Conflict], int]]:
    """Per transmission: the conflicts it raised and the instructions the rules parser dropped, in `window` mode."""
    state, out = State(), []
    for k, tx in enumerate(txs):
        ctx = build_context("window", tx, txs[:k], state)
        conflicts = []
        for e in parse_rules.parse(tx, ctx):
            state, new = apply(state, e)
            conflicts.extend(new)
        out.append((conflicts, parse_rules.count_unresolved(tx, ctx)))
    return out


def test_austin_fixture_is_the_full_on_frequency_transcript():
    rows = load_ntsb_transcript(FIXTURES / "austin_dca23fa149.txt")
    assert len(rows) == 89   # 94 NTSB lines less 5 intrafacility
    assert (rows[0][0], rows[-1][0]) == ("0547:52", "0642:14")


def test_austin_rules_baseline():
    rows = load_ntsb_transcript(FIXTURES / "austin_dca23fa149.txt")
    at = {hhmm: i for i, (hhmm, _) in enumerate(rows)}
    result = fold_rules([tx for _, tx in rows])
    runway = [(hhmm, c) for (hhmm, _), (cs, _) in zip(rows, result) for c in cs if c.type == "RUNWAY" and c.runway == "18L"]
    # The engine models the incident: a RUNWAY conflict on 18L between FedEx's landing and Southwest's takeoff.
    assert any("southwest seven zero eight" in c.callsigns for _, c in runway)
    # v1 findings (spec addendum A.2): the 0634:14 landing clearance has no "runway" token and is dropped ...
    assert result[at["0634:14"]] == ([], 1)
    # ... so nothing fires at 0638:58, when the conflicting takeoff clearance is issued ...
    assert result[at["0638:58"]][0] == []
    # ... and the conflict fires at the 0639:34 re-confirmation instead, capped at warning by the unparsed US callsign.
    hhmm, c = runway[-1]
    assert (hhmm, c.severity, c.callsigns, c.basis) == ("0639:34", "warning", ("", "southwest seven zero eight"),
                                                        "icao-4444-7.10.1")


@pytest.mark.skipif(not CORPUS.exists(), reason="corpus DB not present (UWB-ATCC is not redistributed)")
def test_recording_528_keeps_its_known_false_alert():
    # Air France 198R is cleared to cross 13, then CSA 38W is cleared to land 13. The crossing is complete (Air France is
    # next told to hold short of 24) but nobody says so on frequency. Extraction is correct; the release is not in the audio.
    conn = sqlite3.connect(f"file:{CORPUS}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    txs = load_recording(conn, 528, "gold", "human")
    result = fold_rules(txs)
    raised = [(k + 1, c.type, c.severity, c.runway, c.callsigns) for k, (cs, _) in enumerate(result) for c in cs if c.type == "RUNWAY"]
    assert raised == [(17, "RUNWAY", "alert", "13", ("csa three eight whiskey", "air france one nine eight romeo"))]
```

- [ ] **Step 3: Run the incident tests**

Run: `.venv/bin/python -m pytest tests/test_incidents.py -v`
Expected: PASS — 3 passed on a machine with `data/atc.sqlite`; 2 passed, 1 skipped without it. If `test_recording_528_keeps_its_known_false_alert` fails, the engine changes in Tasks 3–4 have altered recording 528's behaviour: stop and report, do not edit the expectation.

- [ ] **Step 4: Run the whole suite**

Run: `.venv/bin/python -m pytest -q`
Expected: PASS — 181 passed (180 passed, 1 skipped without the corpus).

- [ ] **Step 5: Commit**

```bash
git add tests/fixtures/austin_dca23fa149.txt tests/test_incidents.py
git commit -m "test: Austin 2023 and corpus recording 528 as rules-baseline regression fixtures"
```

---

### Task 8: Corpus check and README

Confirm on the real corpus that the rules parser's output is untouched (the v1 freeze) and that the conflict totals are the ones measured while this plan was prototyped, then update the README's test count. No code changes; the corpus DB is opened read-only and nothing is cached.

**Files:**
- Modify: `README.md` (test count)

**Interfaces:**
- Consumes: everything above.
- Produces: nothing.

- [ ] **Step 1: Check the corpus totals**

Run:

```bash
PYTHONPATH=. .venv/bin/python - <<'EOF'
import sqlite3
from collections import Counter
from atcdb import parse_rules
from atcdb.engine import State, apply
from atcdb.replay import build_context, list_recordings, load_recording
conn = sqlite3.connect("file:data/atc.sqlite?mode=ro", uri=True); conn.row_factory = sqlite3.Row
kinds, events, drops = Counter(), 0, 0
for rec in list_recordings(conn):
    txs, state = load_recording(conn, rec["id"], "gold", "human"), State()
    for k, tx in enumerate(txs):
        ctx = build_context("window", tx, txs[:k], state)
        evs = parse_rules.parse(tx, ctx); events += len(evs); drops += parse_rules.count_unresolved(tx, ctx)
        for e in evs:
            state, cs = apply(state, e)
            kinds.update(f"{c.type}/{c.severity}" for c in cs)
print(f"events={events} dropped={drops} conflicts={sum(kinds.values())} {dict(sorted(kinds.items()))}")
EOF
```

Expected: `events=2035 dropped=3 conflicts=85 {'READBACK/alert': 27, 'READBACK/warning': 8, 'RUNWAY/alert': 12, 'RUNWAY/warning': 38}`. If `events` differs from 2035 the rules parser's output has changed, which the freeze forbids: stop and report. Skip this step if `data/atc.sqlite` is absent.

- [ ] **Step 2: Update the README test count**

In `README.md`, replace:

```text
pytest   # 153 tests
```

with:

```text
pytest   # 181 tests
```

- [ ] **Step 3: Commit**

```bash
git add README.md
git commit -m "docs: README test count after phase 2.5"
```

---

## Out of scope for this plan

- Phase 3a (spec addendum A.4): the Claude parser, `PARSER_MODELS` as a list, the validated `model` parameter, capabilities `available` flags, lazy registration, per-recording transcript pinning, the `get_events` re-raise, the `app.js` request token, and `ENGINE_VERSION` in the cache key (A.7.2).
- Phase 3b (A.5): choosing CROSS and LUAW staleness values, labelling, conflict injection, evaluation scripts.
- Fixing the rules parser's `runway`-token, US-callsign and elliptical-handoff gaps: frozen at v1 by decision (A.7.1).
- Showing `dropped` and `basis` in the replay UI: the API carries both; the page can surface them when phase 3a touches `app.js`.
