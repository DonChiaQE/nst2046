# Level 2 Evaluation (Phase 3b-1) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build everything Level 2 of the evaluation needs without event labels: synthetic conflicts injected into real tower recordings and checked by a person, a runner that replays every arm (rules, Haiku, Sonnet × three context modes × human and ASR transcripts, plus an LLM judge), pooled alert adjudication with Cohen's kappa, a CROSS/LUAW staleness sweep, and the results doc; plus the Level 1 labelling sheet so labelling can start whenever the team is ready.

**Architecture:** Four new modules, each testable alone. `atcdb/inject.py` finds clearance sites with its own regexes (no parser) and builds positives by text edits or by splicing two real recordings, stored under a `synthetic-conflicts` source. `atcdb/evaluate.py` replays recordings through the existing `replay.build_timeline` (so parses use the `events` cache exactly as in the app), writes one JSONL row per recording per arm, and scores those rows with pure functions. `atcdb/judge.py` is the whole-transcript LLM baseline with its own `judgments` cache. `atcdb/eval_report.py` renders the results doc. `scripts/eval_conflicts.py` drives them through `run`, `adjudicate`, `sweep` and `report` subcommands.

**Tech Stack:** Python 3.14, sqlite3, pytest, `anthropic` 1.8.0 (already a requirement).

**Spec:** `docs/superpowers/specs/2026-09-29-evaluation-3b1-design.md` (it amends Section 4 and Addendum A.5 of `2026-09-12-conflict-engine-design.md`). Phases 2.5 and 3a are done (PRs #3, #4).

## Global Constraints

- The rules parser is **frozen at v1** (spec A.7.1): `atcdb/parse_rules.py` is not modified. `atcdb/engine.py` and `atcdb/parse_llm.py` are not modified either; the sweep overrides `engine.STALE_S` in place and restores it.
- UWB-ATCC is CC BY-NC-ND and is **not redistributed**: no corpus transcript text goes into a test, a fixture or a prompt. Tests use invented text; the recorded judge fixture uses invented sequences. The labelling and check sheets under `data/labels/` follow the existing readback sheets there (the repo is private).
- Nothing in the plan writes to `data/atc.sqlite`. Corpus checks run on a copy under `/tmp`. Injecting into the real database, ASR on the train split and every paid run are operational steps after the plan (see the end).
- No paid API call is made by the plan's tests except the live smoke test, which skips without `ANTHROPIC_API_KEY` (as in 3a). Every paid run is dry-run first.
- The judge uses exactly the Sonnet parser arm's settings: `claude-sonnet-5`, `thinking: {"type": "disabled"}`, `output_config: {"effort": "low"}`, strict tool, forced `tool_choice`.
- Results-doc text contains no em dashes (report material).
- Tests follow the repo's style: plain pytest functions, real SQLite files under `tmp_path`, `monkeypatch` only, a small fake Anthropic client, no mock framework. Run with `.venv/bin/python -m pytest`.
- Commit after every task; `feat:` subjects ending with the attribution lines the session provides.

## Decisions taken while planning (user-approved 2026-09-29)

- **Splicing** is a fifth injection kind. Text edits find only about ten candidates in the 309 recordings (only 34 hold two clearances); a splice joins a real recording X that ends holding a reservation to a real recording Y, from the same airport, that clears a conflicting use of the same runway within the reservation's staleness timeout. Nothing is edited, so the ASR arm is fully valid for splices.
- **`real_recordings`** separates the real corpus from synthetic recordings everywhere the evaluation reads the corpus; the page keeps listing both.
- **Scored rows need complete transcripts:** a row counts only when every transmission with a gold transcript also has one of the arm's kind, so a partial ASR run can never be scored as if complete.
- **Subcommands** (`run`, `adjudicate`, `sweep`, `report`) replace the spec's flags on `eval_conflicts.py`.
- **Event cell syntax** puts the runway before the callsign (`land 31 csa one two three`), since callsigns are several words.
- The engine treats `13` and `31` (the two ends of one strip) as unrelated runways. Recorded as a caveat in the results doc, not changed.

## File structure

| File | Responsibility |
|---|---|
| `atcdb/replay.py` (modify) | `SYNTHETIC_SOURCE`, `real_recordings` |
| `atcdb/event_labels.py` (create) | Level 1 sheet sampling (test split only) and the `events` cell parser |
| `atcdb/inject.py` (create) | site scan, the five injection kinds, selection, storage, the human check sheet |
| `atcdb/evaluate.py` (create) | arms, running, JSONL rows, scoring, false alarms, bootstrap, kappa, adjudication, sweep |
| `atcdb/judge.py` (create) | the whole-transcript judge: prompt, tool, response mapping, `judgments` cache |
| `atcdb/eval_report.py` (create) | summary numbers and the Markdown results doc |
| `atcdb/schema.py` (modify) | the `judgments` table |
| `scripts/make_event_sheet.py`, `scripts/inject_conflicts.py`, `scripts/eval_conflicts.py`, `scripts/record_judge_fixtures.py` (create) | command-line drivers |
| `tests/test_event_labels.py`, `tests/test_inject.py`, `tests/test_evaluate.py`, `tests/test_judge.py`, `tests/test_eval_report.py`, `tests/fixtures/judge_responses.json` (create); `tests/test_replay.py`, `tests/test_schema.py` (modify) | |
| `README.md` (modify) | the evaluation steps, test count |

Domain vocabulary for the engineer: a **recording** is a clip of tower frequency (median 23 s); a **transmission** is one radio call in it, with a **transcript** (gold = human, or ASR = Whisper). A parser turns a transcript into **events** (LAND, TAKEOFF, LUAW = line up and wait, CROSS, HOLD_SHORT, VACATED, HANDOFF, READBACK, ...); the engine folds events into runway **reservations** and raises **conflicts** (`RUNWAY` or `READBACK`, severity `alert` or `warning`) using a compatibility matrix (`engine.MATRIX`). A **release** (vacated, handed to ground or radar) ends a reservation; a reservation older than its **staleness** timeout (`engine.STALE_S`, 300 s) is dropped. **Context** is what a parser sees besides the text: `none`, `role`, or `window` (role, last 4 transmissions, what the engine tracks). Parses are cached in `events`, keyed by transcript, parser, model, version and context. A **positive** is a synthetic recording containing one known conflict (runway R, raised by trigger transmission B); a **negative** is a real recording, where genuine conflicts are about zero, so alerts there are false alarms unless a person finds them genuine.

---

### Task 1: The Level 1 event labelling sheet, and `real_recordings`

Labelling blocks Level 1 (3b-2) and the team will label later, so the sheet generator lands first: whoever
labels can start as soon as this task merges. The sheet samples **test-split** transmissions only (spec section 3:
the Whisper model saw the train split, so Level 1's ASR factor stays clean) and carries no parser output. The same
task adds `replay.real_recordings`, because synthetic-conflict recordings (Task 2) are Tower recordings too and every
consumer here (this sheet, the injector, the evaluation's negatives) must see only the real corpus. The page still
lists synthetic recordings, since they double as replay demos.

**Files:**
- Modify: `atcdb/replay.py` (a constant and one function)
- Create: `atcdb/event_labels.py`
- Create: `scripts/make_event_sheet.py`
- Test: `tests/test_event_labels.py` (create), `tests/test_replay.py` (modify)

**Interfaces:**
- Produces: `replay.SYNTHETIC_SOURCE = "synthetic-conflicts"`; `replay.real_recordings(conn, **kwargs) -> list[dict]`
  (the rows of `list_recordings(conn, **kwargs)` whose `source` is not `SYNTHETIC_SOURCE`).
- Produces: `event_labels.COLUMNS: list[str]`; `event_labels.sample_event_sheet(conn, n=200, seed=0) -> list[dict]`;
  `event_labels.parse_event_cell(cell: str) -> list[Event]` (raises `ValueError`).

- [ ] **Step 1: Write the failing tests**

In `tests/test_replay.py`, replace:

```python
                          list_recordings, load_recording, transcript_models, uncached_parses)
```

with:

```python
                          list_recordings, load_recording, real_recordings, transcript_models, uncached_parses)
```

Append to `tests/test_replay.py`:

```python


def test_real_recordings_leaves_out_the_synthetic_conflicts(tmp_path):
    conn = init_db(tmp_path / "t.sqlite")
    real = _seed(conn, SEQUENCE, external_id="real")
    fake = _seed(conn, SEQUENCE, external_id="fake")
    conn.execute("INSERT INTO sources (id, name, kind) VALUES (2, 'synthetic-conflicts', 'corpus')")
    conn.execute("UPDATE recordings SET source_id = 2 WHERE id = ?", (fake,))
    assert {r["id"] for r in list_recordings(conn)} == {real, fake}   # both replay in the app
    assert [r["id"] for r in real_recordings(conn)] == [real]
    assert real_recordings(conn, min_transmissions=99) == []
```

Create `tests/test_event_labels.py`:

```python
import pytest

from atcdb.engine import ClearToLand, GoAround, Handoff, HoldShort, ReadbackObserved, RunwayVacated
from atcdb.event_labels import COLUMNS, parse_event_cell, sample_event_sheet
from atcdb.schema import init_db


def _seed(conn, turns, external_id="r1"):
    """One tower recording; `turns` = [(role, text, split), ...] at 10 s spacing, gold transcripts by 'human'."""
    conn.execute("INSERT OR IGNORE INTO sources (id, name, kind) VALUES (1, 'test', 'corpus')")
    rid = conn.execute("INSERT INTO recordings (source_id, external_id, facility) VALUES (1, ?, 'Tower')",
                       (external_id,)).lastrowid
    for i, (role, text, split) in enumerate(turns):
        xid = conn.execute(
            """INSERT INTO transmissions (recording_id, external_id, start_s, end_s, speaker_role, split, clip_path)
               VALUES (?, ?, ?, ?, ?, ?, ?)""", (rid, f"x{i}", 10.0 * i, 10.0 * i + 3, role, split, f"clips/{external_id}-{i}.wav")).lastrowid
        conn.execute("INSERT INTO transcripts (transmission_id, kind, model, raw_text, normalized_text) VALUES (?, 'gold', 'human', ?, ?)",
                     (xid, text, text))
    conn.commit()
    return rid


TURNS = [
    ("controller", "csa one two three runway three one cleared to land", "train"),
    ("pilot", "cleared to land three one csa one two three", "test"),
    ("controller", "lufthansa four five six hold short runway three one", "test"),
    ("pilot", "holding short lufthansa four five six", "train"),
    ("controller", "csa one two three contact ground one two one nine", "test"),
]


def test_the_sheet_samples_only_test_split_transmissions_with_their_context(tmp_path):
    conn = init_db(tmp_path / "t.sqlite")
    _seed(conn, TURNS)
    rows = sample_event_sheet(conn, n=10, seed=0)
    assert sorted(r["text"] for r in rows) == sorted(t for _, t, split in TURNS if split == "test")
    assert [r["row_id"] for r in rows] == [1, 2, 3]
    third = next(r for r in rows if r["text"] == TURNS[2][1])
    assert third["context"] == f"[controller] {TURNS[0][1]}\n[pilot] {TURNS[1][1]}"
    assert third["role"] == "controller" and third["clip_path"] == "clips/r1-2.wav"
    assert (third["events"], third["notes"]) == ("", "")
    assert list(third) == COLUMNS


def test_the_sheet_is_seeded_and_capped_at_n(tmp_path):
    conn = init_db(tmp_path / "t.sqlite")
    _seed(conn, TURNS)
    _seed(conn, TURNS, external_id="r2")
    first = sample_event_sheet(conn, n=4, seed=1)
    assert len(first) == 4
    assert first == sample_event_sheet(conn, n=4, seed=1)
    assert [r["transmission_id"] for r in first] != [r["transmission_id"] for r in sample_event_sheet(conn, n=4, seed=2)]


def test_the_sheet_carries_no_parser_output(tmp_path):
    conn = init_db(tmp_path / "t.sqlite")
    _seed(conn, TURNS)
    assert not {"kind", "parser", "rule", "predicted", "llm"} & set(COLUMNS)


def test_parse_event_cell_reads_every_kind():
    cell = ("land 31 csa one two three\nhold_short 4L lufthansa four five six\nhandoff ground csa one two three\n"
            "vacated csa one two three\ngo_around\nreadback lufthansa four five six")
    assert parse_event_cell(cell) == [
        ClearToLand(runway="31", callsign="csa one two three"),
        HoldShort(runway="04L", callsign="lufthansa four five six"),
        Handoff(to="ground", callsign="csa one two three"),
        RunwayVacated(callsign="csa one two three"),
        GoAround(callsign=""),
        ReadbackObserved(callsign="lufthansa four five six", text=""),
    ]
    assert parse_event_cell(" NOOP \n") == []


@pytest.mark.parametrize("cell, message", [
    ("", "empty cell"),
    ("land csa one two three", "needs a runway"),
    ("cross 99 csa", "needs a runway"),
    ("handoff tower_two csa", "needs a target"),
    ("taxi 31 csa", "unknown kind"),
    ("land 31 csa\nnoop", "only line"),
])
def test_parse_event_cell_rejects_bad_cells(cell, message):
    with pytest.raises(ValueError, match=message):
        parse_event_cell(cell)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_event_labels.py tests/test_replay.py -q`
Expected: FAIL at collection with `ImportError: cannot import name 'real_recordings'`.

- [ ] **Step 3: Write the implementation**

In `atcdb/replay.py`, replace:

```python
# parser -> instructions it recognised
```

with:

```python
# the source atcdb/inject.py stores synthetic-conflict recordings under; they replay like any other recording
SYNTHETIC_SOURCE = "synthetic-conflicts"
# parser -> instructions it recognised
```

In `atcdb/replay.py`, replace:

```python
def get_recording(
```

with:

```python
def real_recordings(conn: sqlite3.Connection, **kwargs) -> list[dict]:
    """`list_recordings` without the recordings conflict injection wrote (atcdb/inject.py): the real corpus, which the
    evaluation's negatives, the labelling sheet and the injector itself draw from."""
    return [r for r in list_recordings(conn, **kwargs) if r["source"] != SYNTHETIC_SOURCE]


def get_recording(
```

Create `atcdb/event_labels.py`:

```python
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
```

Create `scripts/make_event_sheet.py`:

```python
#!/usr/bin/env python3
"""Write the Level 1 event labelling sheets (spec 2026-09-29-evaluation-3b1-design.md, section 8).

Usage:
    python scripts/make_event_sheet.py [--out data/labels] [--n 200] [--overlap 50] [--seed 0] [--db data/atc.sqlite]
    python scripts/make_event_sheet.py --check data/labels/event_sheet_A.csv

Produces:
  <out>/event_sheet_A.csv   full sheet (annotator A)
  <out>/event_sheet_B.csv   first <overlap> rows of A (annotator B), for Cohen's kappa
Fill `events` with one event per line (see atcdb/event_labels.py), or `noop`. `--check` reads a filled sheet back and
lists every cell that does not parse; unfilled rows are counted, not errors.
"""
import argparse
import csv
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from atcdb.event_labels import COLUMNS, parse_event_cell, sample_event_sheet  # noqa: E402
from atcdb.schema import connect  # noqa: E402


def check(path: Path) -> int:
    """Print the unparseable cells of a filled sheet; returns how many there are."""
    bad = blank = 0
    with path.open(newline="") as fh:
        for row in csv.DictReader(fh):
            if not row["events"].strip():
                blank += 1
                continue
            try:
                parse_event_cell(row["events"])
            except ValueError as e:
                bad += 1
                print(f"row {row['row_id']}: {e}")
    print(f"{path}: {bad} unparseable cells, {blank} rows not yet labelled")
    return bad


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", type=Path, default=ROOT / "data/atc.sqlite")
    ap.add_argument("--out", type=Path, default=ROOT / "data/labels")
    ap.add_argument("--n", type=int, default=200)
    ap.add_argument("--overlap", type=int, default=50)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--check", type=Path, help="validate a filled sheet instead of writing new ones")
    args = ap.parse_args()
    if args.check:
        sys.exit(1 if check(args.check) else 0)
    existing = [p for p in (args.out / "event_sheet_A.csv", args.out / "event_sheet_B.csv") if p.exists()]
    if existing:
        sys.exit(f"{existing[0]} exists; it may hold labels. Move it away first.")
    rows = sample_event_sheet(connect(args.db), n=args.n, seed=args.seed)
    args.out.mkdir(parents=True, exist_ok=True)
    for name, subset in (("A", rows), ("B", rows[:args.overlap])):
        path = args.out / f"event_sheet_{name}.csv"
        with path.open("w", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=COLUMNS)
            w.writeheader()
            w.writerows(subset)
        print(f"wrote {path} ({len(subset)} rows)")


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_event_labels.py tests/test_replay.py -q` then `.venv/bin/python -m pytest -q`
Expected: PASS; the whole suite is 226 passed with `ANTHROPIC_API_KEY` set (225 passed and 1 skipped without it).

- [ ] **Step 5: Check the script on the corpus (skip if `data/atc.sqlite` is absent)**

Run: `.venv/bin/python scripts/make_event_sheet.py --out /tmp/event-sheet-check && .venv/bin/python scripts/make_event_sheet.py --check /tmp/event-sheet-check/event_sheet_A.csv`
Expected: `wrote .../event_sheet_A.csv (200 rows)`, `wrote .../event_sheet_B.csv (50 rows)`, then
`0 unparseable cells, 200 rows not yet labelled`. Running the first command again must refuse (`... exists; it may
hold labels`). Delete `/tmp/event-sheet-check`; the real sheets are written into `data/labels/` only when the team is
ready to label (it is not part of this plan).

- [ ] **Step 6: Commit**

```bash
git add atcdb/replay.py atcdb/event_labels.py scripts/make_event_sheet.py tests/test_event_labels.py tests/test_replay.py
git commit -m "feat: Level 1 event labelling sheet and real_recordings"
```
End the message with the attribution lines the session provides.

---

### Task 2: Conflict injection and its human check

The positives for Level 2. A scan that uses no parser finds clearance, hold-short and release sites in the
human gold text. Four text edits make a later transmission B conflict with an earlier reservation A, and a fifth
kind, `splice`, joins two real recordings from the same airport: X ends holding A, Y then clears B on the same runway.
Splicing exists because text edits find only about ten candidates on this corpus (few clips hold two clearances); on
the corpus copy the generator finds 1, 6, 1, 2 and 8,141 candidates for the five kinds and selects 100. Each injection
is stored as a new recording under `synthetic-conflicts`, and a human says yes or no to each on a check sheet before
it is scored.

Corpus facts the regexes encode (checked on the 309 recordings): Prague says `line up runway X` without `and wait`,
often as `line up runway X cleared for takeoff` (a takeoff, one site); handoffs are `contact ruzyne ground/radar/tower`
and `departure` never occurs, so radar counts as the departure release; `31` and `13` carry almost all traffic.

**Files:**
- Create: `atcdb/inject.py`
- Create: `scripts/inject_conflicts.py`
- Test: `tests/test_inject.py`

**Interfaces:**
- Consumes: `replay.SYNTHETIC_SOURCE`, `replay.real_recordings` (Task 1); `engine.MATRIX`, `engine.RESERVATION_KINDS`,
  `engine.STALE_S`, `engine.normalize_runway`; `replay.load_recording`, `replay.default_transcript_model`.
- Produces: `inject.EDIT_KINDS` (`runway_swap`, `holdshort_to_cross`, `verb_upgrade`, `release_delete`, `splice`);
  `Site`, `Injection` dataclasses; `scan`, `candidates`, `splice_anchor`, `splice_candidate`, `select`, `pool`,
  `generate`, `write_injection(conn, inj, seed, ordinal) -> int`;
  `synthetic_recordings(conn, valid_only=False) -> list[dict]`, each `{"recording_id", "external_id", "edit_kind",
  "runway", "anchor_tx", "trigger_tx", ...}` (transmission ids are the synthetic recording's own);
  `CHECK_COLUMNS`, `check_rows(conn)`, `apply_check(conn, rows) -> {"yes", "no", ""}` counts.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_inject.py`:

```python
import json
from pathlib import Path

import pytest

from atcdb.inject import (EDIT_KINDS, SPLICE_GAP_S, Injection, apply_check, candidates, check_rows, generate, pool, scan,
                          select, splice_anchor, splice_candidate, synthetic_recordings, write_injection)
from atcdb.parsing import Transmission
from atcdb.replay import build_timeline, default_transcript_model, load_recording
from atcdb.schema import init_db

DB = Path(__file__).resolve().parents[1] / "data/atc.sqlite"


def _txs(*turns):
    return [Transmission(id=i + 1, transcript_id=i + 1, text=text, role=role, start_s=10.0 * i)
            for i, (role, text) in enumerate(turns)]


def _seed(conn, turns, external_id="r1", asr=False, airport="LKPR"):
    """One tower recording with human gold transcripts (and, with `asr`, a Whisper transcript of each). Returns its id."""
    conn.execute("INSERT OR IGNORE INTO sources (id, name, kind) VALUES (1, 'test', 'corpus')")
    rid = conn.execute("INSERT INTO recordings (source_id, external_id, facility, airport_icao) VALUES (1, ?, 'Tower', ?)",
                       (external_id, airport)).lastrowid
    for i, (role, text) in enumerate(turns):
        xid = conn.execute(
            """INSERT INTO transmissions (recording_id, external_id, start_s, end_s, speaker_role, clip_path, pcm_sha1, split)
               VALUES (?, ?, ?, ?, ?, ?, ?, 'test')""",
            (rid, f"x{i}", 10.0 * i, 10.0 * i + 3, role, f"clips/{external_id}-{i}.wav", f"sha-{external_id}-{i}")).lastrowid
        conn.execute("INSERT INTO transcripts (transmission_id, kind, model, raw_text, normalized_text) VALUES (?, 'gold', 'human', ?, ?)",
                     (xid, text, text))
        if asr:
            conn.execute("""INSERT INTO transcripts (transmission_id, kind, model, model_version, raw_text, normalized_text)
                            VALUES (?, 'asr', 'whisper', 'v', ?, ?)""", (xid, f"asr {text}", f"asr {text}"))
    conn.commit()
    return rid


LAND_31 = ("controller", "csa one two three runway three one cleared to land wind calm")
LINEUP_13 = ("controller", "lufthansa four five six line up runway one three")
LINEUP_31 = ("controller", "lufthansa four five six line up runway three one")
HOLD_13 = ("controller", "lufthansa four five six hold short of runway one three")
TO_31 = ("controller", "lufthansa four five six runway three one cleared for takeoff")
GROUND = ("controller", "csa one two three contact ruzyne ground one two one nine")
READBACK = ("pilot", "cleared to land runway three one csa one two three")


def test_scan_finds_clearances_hold_shorts_and_releases():
    sites = scan(_txs(LAND_31, READBACK, LINEUP_13, HOLD_13, GROUND,
                      ("controller", "jet one line up runway three one cleared for takeoff"),
                      ("controller", "fedex one four heavy one eight left cleared to land"),
                      ("pilot", "runway vacated csa one two three")))
    assert [(s.index, s.kind, s.runway) for s in sites] == [
        (0, "LAND", "31"), (2, "LUAW", "13"), (3, "HOLD_SHORT", "13"), (4, "RELEASE", None),
        (5, "TAKEOFF", "31"), (6, "LAND", "18L"), (7, "RELEASE", None)]
    assert sites[0].words == "three one" and sites[2].released == ()
    assert sites[3].released == ("LAND", "CROSS") and sites[6].released == ("LAND", "TAKEOFF", "LUAW", "CROSS")


def test_a_repeated_clearance_in_one_transmission_is_one_site():
    sites = scan(_txs(("mixed", "air france one nine eight cross runway one three cross runway one three")))
    assert [(s.index, s.kind, s.runway) for s in sites] == [(0, "CROSS", "13")]


def test_scan_ignores_pilot_clearances_and_bare_numbers_without_a_side():
    assert scan(_txs(READBACK, ("controller", "csa one two three cleared to land"))) == []


def test_runway_swap_moves_a_later_clearance_onto_the_anchor_runway():
    txs = _txs(LAND_31, READBACK, LINEUP_13)
    [inj] = [c for c in candidates(7, txs) if c.edit_kind == "runway_swap"]
    assert inj == Injection(7, "runway_swap", 0, 2, "31", "lufthansa four five six line up runway three one")


def test_holdshort_to_cross_turns_a_hold_short_into_a_crossing_of_the_anchor_runway():
    txs = _txs(LAND_31, HOLD_13)
    [inj] = [c for c in candidates(7, txs) if c.edit_kind == "holdshort_to_cross"]
    assert inj.after == "lufthansa four five six cross runway three one" and (inj.anchor, inj.trigger) == (0, 1)


def test_verb_upgrade_turns_a_line_up_behind_a_landing_into_a_takeoff():
    txs = _txs(LAND_31, LINEUP_31, ("controller", "jet two line up and wait runway three one"))
    ups = [c for c in candidates(7, txs) if c.edit_kind == "verb_upgrade"]
    assert [(c.trigger, c.after, c.runway) for c in ups] == [
        (1, "lufthansa four five six cleared for takeoff runway three one", "31"),
        (2, "jet two cleared for takeoff runway three one", "31")]


def test_release_delete_removes_the_one_release_before_a_conflicting_clearance():
    txs = _txs(LAND_31, GROUND, TO_31)
    kinds = [c.edit_kind for c in candidates(7, txs)]
    [inj] = [c for c in candidates(7, txs) if c.edit_kind == "release_delete"]
    assert (inj.anchor, inj.deleted, inj.trigger, inj.after) == (0, 1, 2, TO_31[1])
    assert "runway_swap" not in kinds   # the takeoff is already on 31


def test_the_runway_is_the_one_closest_to_the_verb():
    [site] = scan(_txs(("controller", "klm one you can use runway two two and line up runway three one")))
    assert (site.kind, site.runway) == ("LUAW", "31")


def test_a_release_between_anchor_and_trigger_blocks_the_edits():
    txs = _txs(LAND_31, GROUND, LINEUP_13)
    assert [c.edit_kind for c in candidates(7, txs)] == []


def test_no_candidate_means_no_injection():
    assert candidates(7, _txs(READBACK, GROUND)) == []
    assert select([], 10, seed=0) == []


def test_select_is_seeded_stratified_and_takes_one_per_recording_and_kind():
    pool = [Injection(r, k, 0, 1, "31", f"{r}{k}{i}") for r in range(6) for k in EDIT_KINDS[:2] for i in range(2)]
    chosen = select(pool, 5, seed=0)
    assert len(chosen) == 5 and chosen == select(pool, 5, seed=0)
    assert [c.edit_kind for c in chosen] == ["runway_swap", "holdshort_to_cross"] * 2 + ["runway_swap"]
    assert len({(c.recording_id, c.edit_kind) for c in chosen}) == 5
    assert len(select(pool, 100, seed=0)) == 12   # six recordings x two kinds, one each
    assert select(pool, 5, seed=0) != select(pool, 5, seed=1)


def test_a_stored_injection_differs_from_its_original_only_at_the_trigger(tmp_path):
    conn = init_db(tmp_path / "t.sqlite")
    rid = _seed(conn, [LAND_31, READBACK, LINEUP_13, ("pilot", "lining up one three lufthansa four five six")], asr=True)
    [inj] = [c for c in generate(conn, [rid], n=10, seed=3) if c.edit_kind == "runway_swap"]
    sid = write_injection(conn, inj, seed=3, ordinal=0)
    assert write_injection(conn, inj, seed=3, ordinal=0) == sid   # idempotent
    rec = conn.execute("SELECT r.*, s.name FROM recordings r JOIN sources s ON s.id = r.source_id WHERE r.id = ?", (sid,)).fetchone()
    assert (rec["name"], rec["external_id"], rec["facility"], rec["airport_icao"]) == ("synthetic-conflicts", f"{rid}-runway_swap-3-0", "Tower", "LKPR")
    assert default_transcript_model(conn, "gold", sid) == "synthetic"
    orig, synth = load_recording(conn, rid), load_recording(conn, sid, "gold", "synthetic")
    assert [t.text for t in synth] == [t.text for t in orig[:2]] + [inj.after] + [orig[3].text]
    assert [(t.role, t.start_s) for t in synth] == [(t.role, t.start_s) for t in orig]
    xs = conn.execute("SELECT clip_path, pcm_sha1, split FROM transmissions WHERE recording_id = ? ORDER BY start_s", (sid,)).fetchall()
    assert [tuple(x) for x in xs] == [(f"clips/r1-{i}.wav", None, "test") for i in range(4)]
    asr = load_recording(conn, sid, "asr", "whisper")
    assert [t.text for t in asr] == [f"asr {t.text}" for t in orig[:2]] + [inj.after] + [f"asr {orig[3].text}"]
    edited = conn.execute("SELECT model_version FROM transcripts WHERE id = ?", (asr[2].transcript_id,)).fetchone()[0]
    assert edited == "synthetic"
    [meta] = synthetic_recordings(conn)
    assert (meta["recording_id"], meta["edit_kind"], meta["runway"], meta["before"], meta["after"]) == (
        sid, "runway_swap", "31", LINEUP_13[1], inj.after)
    assert (meta["anchor_tx"], meta["trigger_tx"]) == (synth[0].id, synth[2].id) and meta["deleted"] is None


def test_release_delete_drops_the_release_transmission(tmp_path):
    conn = init_db(tmp_path / "t.sqlite")
    rid = _seed(conn, [LAND_31, GROUND, TO_31, READBACK])
    [inj] = [c for c in generate(conn, [rid], n=10, seed=0) if c.edit_kind == "release_delete"]
    sid = write_injection(conn, inj, seed=0, ordinal=0)
    assert [t.text for t in load_recording(conn, sid, "gold", "synthetic")] == [LAND_31[1], TO_31[1], READBACK[1]]
    assert synthetic_recordings(conn)[0]["deleted"] == GROUND[1]


def test_the_injected_conflict_is_what_the_rules_parser_then_sees(tmp_path):
    conn = init_db(tmp_path / "t.sqlite")
    rid = _seed(conn, [LAND_31, READBACK, ("controller", "lufthansa four five six cross runway one three")])
    [inj] = [c for c in generate(conn, [rid], n=10, seed=0) if c.edit_kind == "runway_swap"]
    sid = write_injection(conn, inj, seed=0, ordinal=0)
    assert not [c for s in build_timeline(conn, rid).steps for c in s.conflicts]
    tl = build_timeline(conn, sid, transcript_model="synthetic")
    assert [(k, c.type, c.severity, c.runway) for k, s in enumerate(tl.steps) for c in s.conflicts] == [(2, "RUNWAY", "alert", "31")]


def test_a_splice_needs_x_to_end_holding_a_and_y_to_clear_the_same_runway_against_it():
    x = _txs(LAND_31, READBACK)
    y = _txs(("pilot", "ruzyne tower lufthansa four five six ready"), TO_31)
    inj = splice_candidate(1, x, 13.0, 2, y)
    assert inj == Injection(1, "splice", 0, 3, "31", TO_31[1], second=2, offset=13.0 + SPLICE_GAP_S - 0.0)
    assert splice_anchor(_txs(LAND_31, GROUND)) is None                       # released before X ends
    assert splice_candidate(1, x, 13.0, 2, _txs(LINEUP_13)) is None          # another runway
    assert splice_candidate(1, x, 13.0, 2, _txs(("controller", "jet one runway three one cleared to land"))) is None  # LAND after LAND is lawful
    assert splice_candidate(1, x, 290.0, 2, y) is None                       # A would be stale by the time B arrives


def test_splices_pair_recordings_from_one_airport_and_store_both_halves(tmp_path):
    conn = init_db(tmp_path / "t.sqlite")
    x = _seed(conn, [LAND_31, READBACK], external_id="x", asr=True)
    y = _seed(conn, [("pilot", "tower lufthansa four five six ready"), TO_31], external_id="y", asr=True)
    _seed(conn, [TO_31], external_id="z", airport="EDDF")
    splices = [c for c in pool(conn, [x, y, 3]) if c.edit_kind == "splice"]
    # both orders conflict (Y ends holding a takeoff that X's landing clearance meets); Z is at another airport
    assert [(c.recording_id, c.second) for c in splices] == [(x, y), (y, x)]
    sid = write_injection(conn, splices[0], seed=0, ordinal=0)
    synth = load_recording(conn, sid, "gold", "synthetic")
    assert [t.text for t in synth] == [LAND_31[1], READBACK[1], "tower lufthansa four five six ready", TO_31[1]]
    assert [t.start_s for t in synth] == [0.0, 10.0, 13.0 + SPLICE_GAP_S, 23.0 + SPLICE_GAP_S]
    ext = [r[0] for r in conn.execute("SELECT external_id FROM transmissions WHERE recording_id = ? ORDER BY start_s", (sid,))]
    assert ext == ["x0", "x1", "b:x0", "b:x1"]
    assert [t.text for t in load_recording(conn, sid, "asr", "whisper")] == [f"asr {t.text}" for t in synth]   # nothing edited
    [meta] = synthetic_recordings(conn)
    assert (meta["second_recording_id"], meta["splice_tx"], meta["trigger_tx"]) == (y, synth[2].id, synth[3].id)
    tl = build_timeline(conn, sid, transcript_model="synthetic")
    assert [(k, c.runway, c.severity) for k, s in enumerate(tl.steps) for c in s.conflicts] == [(3, "31", "alert")]
    assert "--- recording" in check_rows(conn)[0]["context"]


def test_the_check_sheet_round_trips_verdicts(tmp_path):
    conn = init_db(tmp_path / "t.sqlite")
    rid = _seed(conn, [LAND_31, READBACK, LINEUP_13, HOLD_13])
    for i, inj in enumerate(generate(conn, [rid], n=10, seed=0)):
        write_injection(conn, inj, seed=0, ordinal=i)
    rows = check_rows(conn)
    assert len(rows) == 2 and {r["edit_kind"] for r in rows} == {"runway_swap", "holdshort_to_cross"}
    swap = next(r for r in rows if r["edit_kind"] == "runway_swap")
    assert swap["context"].splitlines()[0] == f"A> [controller] {LAND_31[1]}"
    assert swap["context"].splitlines()[2].startswith("B> [controller] ") and swap["valid"] == ""
    swap["valid"], swap["notes"] = "YES", "fine"
    assert apply_check(conn, rows) == {"yes": 1, "no": 0, "": 1}
    [positive] = synthetic_recordings(conn, valid_only=True)
    assert positive["recording_id"] == swap["recording_id"]
    again = next(r for r in check_rows(conn) if r["edit_kind"] == "runway_swap")
    assert (again["valid"], again["notes"]) == ("yes", "fine")
    swap["valid"] = "maybe"
    with pytest.raises(ValueError, match="yes, no or blank"):
        apply_check(conn, rows)


@pytest.mark.skipif(not DB.exists(), reason="needs the UWB-ATCC corpus in data/atc.sqlite (not redistributed)")
def test_recording_528_yields_injections_on_the_real_corpus():
    from atcdb.schema import connect
    conn = connect(DB)
    pool = candidates(528, load_recording(conn, 528, "gold", "human"))
    # the crossing (steps 11, 13) and the landing clearance (16) on 13; the release in between (15) is another
    # aircraft's handoff, which is exactly what the human check must reject
    assert sorted((c.edit_kind, c.anchor, c.trigger) for c in pool) == [
        ("holdshort_to_cross", 16, 18), ("release_delete", 11, 16), ("release_delete", 13, 16)]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_inject.py -q`
Expected: FAIL at collection with `ModuleNotFoundError: No module named 'atcdb.inject'`.

- [ ] **Step 3: Write the implementation**

Create `atcdb/inject.py`:

```python
"""Conflict injection (spec 2026-09-29-evaluation-3b1-design.md, section 4).

A scan that uses no parser finds clearance *sites* in a recording's human gold text. A seeded generator then builds a
sequence in which a later transmission B conflicts with an earlier reservation A on runway R, either by editing real text
or by splicing two real recordings. Each sequence is stored as a new recording under the `synthetic-conflicts` source,
and a human says yes or no to each before it counts as a positive. The scan's regexes are deliberately broader than the
rules parser's (`atcdb/parse_rules` stays frozen): no `runway` token is needed before a designator that carries a side,
and a single digit is a runway.

Kinds (A = anchor site, B = trigger site, R = A's runway):
- runway_swap:        B is a clearance to another runway; its designator becomes R's.
- holdshort_to_cross: B is `hold short (of) (runway) X`; it becomes `cross runway R`.
- verb_upgrade:       A is a landing clearance on R and B a line-up or landing clearance on R; B's verb becomes
                      `cleared for takeoff`.
- release_delete:     a release between A and a later clearance B on R that conflicts with A is deleted.
- splice:             nothing is edited. Recording X ends holding A (no release of it follows) and a different recording
                      Y, from the same airport, contains a clearance B on R that conflicts with A; the sequence is X
                      followed by Y, shifted to start SPLICE_GAP_S after X ends. Only a splice whose B falls within A's
                      staleness timeout is kept, so the engine still holds A when B arrives. The four text edits yield
                      about ten candidates on this corpus (few clips hold two clearances); splicing supplies the rest.
"""
import json
import random
import re
import sqlite3
from dataclasses import dataclass

from atcdb.engine import MATRIX, RESERVATION_KINDS, STALE_S, normalize_runway
from atcdb.parsing import Transmission
from atcdb.replay import SYNTHETIC_SOURCE, default_transcript_model, load_recording

SOURCE = SYNTHETIC_SOURCE
TRANSCRIPT_MODEL = "synthetic"   # gold transcripts of synthetic recordings
ASR_VERSION = "synthetic"        # model_version of an edited trigger's ASR row, which holds the edited gold text
EDIT_KINDS = ("runway_swap", "holdshort_to_cross", "verb_upgrade", "release_delete", "splice")
ANCHOR_ROLES = ("controller", "mixed")
SPLICE_GAP_S = 5.0               # silence between the end of X and the start of Y in a splice

_D = r"(?:zero|one|two|three|four|five|six|seven|eight|nine)"
_SIDE = r"(?:left|right|centre|center)"
_DESIG = rf"{_D}(?: {_D})?(?: {_SIDE})?"
_RUNWAY_RE = re.compile(rf"\brunway (?P<rwy>{_DESIG})\b|\b(?P<bare>{_D}(?: {_D})? {_SIDE})\b")
_HOLD_RE = re.compile(rf"\bhold(?:ing)? short (?:of )?(?:runway )?(?P<rwy>{_DESIG})\b")
_CROSS_RE = re.compile(rf"\bcross (?:runway )?(?P<rwy>{_DESIG})\b")
_VERB_RE = {"TAKEOFF": re.compile(r"\bcleared for take ?off\b"), "LAND": re.compile(r"\bcleared to land\b"),
            "LUAW": re.compile(r"\bline up(?: and wait)?\b")}
_RELEASE_RE = re.compile(r"\bcontact (?:ruzyne |praha |prague )?(?P<to>ground|apron|radar|director|departure)\b"
                         r"|\b(?P<vacated>vacated)\b")
# which reservation kinds a release frees (engine.apply: ground frees LAND and CROSS, departure frees TAKEOFF)
_RELEASES = {"ground": ("LAND", "CROSS"), "departure": ("TAKEOFF",), "vacated": RESERVATION_KINDS}


@dataclass(frozen=True)
class Site:
    index: int                 # position of the transmission in the recording
    kind: str                  # LAND | TAKEOFF | LUAW | CROSS | HOLD_SHORT | RELEASE
    runway: str | None         # normalized designator; None for RELEASE
    words: str = ""            # the designator as spoken, e.g. "three one"
    rwy_span: tuple[int, int] = (0, 0)    # character span of the designator in the text
    edit_span: tuple[int, int] = (0, 0)   # character span an edit replaces: the verb, or the whole hold-short phrase
    released: tuple[str, ...] = ()        # RELEASE only: reservation kinds it frees


@dataclass(frozen=True)
class Injection:
    recording_id: int          # the original recording (X, for a splice)
    edit_kind: str
    anchor: int                # index of A in the sequence (X's transmissions, then Y's for a splice)
    trigger: int               # index of B in the same sequence
    runway: str                # R, normalized
    after: str                 # B's text as stored (unchanged for release_delete and splice)
    deleted: int | None = None # index of the deleted release (release_delete only)
    second: int | None = None  # Y (splice only)
    offset: float = 0.0        # seconds added to Y's start times (splice only)


def _runway_near(text: str, verb: tuple[int, int]) -> tuple[str, str, tuple[int, int]] | None:
    """The runway designator closest to the verb at character span `verb`, measured as the gap between the verb and the
    whole `runway X` phrase on either side: (normalized, spoken words, designator span), or None."""
    best = None
    for m in _RUNWAY_RE.finditer(text):
        group = "rwy" if m.group("rwy") else "bare"
        rwy = normalize_runway(m.group(group))
        if rwy is None:
            continue
        dist = m.start() - verb[1] if m.start() >= verb[1] else verb[0] - m.end()
        if best is None or dist < best[0]:
            best = (dist, rwy, m.group(group), m.span(group))
    return best[1:] if best else None


def scan(txs: list[Transmission]) -> list[Site]:
    """Every clearance, hold-short and release site in a recording, in transmission order. Clearances and hold-shorts
    count only from controller (or mixed) transmissions; a release counts from anyone (pilots report `vacated`)."""
    sites: list[Site] = []
    for k, tx in enumerate(txs):
        text = tx.text
        if tx.role in ANCHOR_ROLES:
            for kind, rx in (("HOLD_SHORT", _HOLD_RE), ("CROSS", _CROSS_RE)):
                for m in rx.finditer(text):
                    rwy = normalize_runway(m.group("rwy"))
                    if rwy:
                        sites.append(Site(k, kind, rwy, m.group("rwy"), m.span("rwy"), m.span()))
            verbs = ("TAKEOFF", "LAND") if _VERB_RE["TAKEOFF"].search(text) else ("TAKEOFF", "LAND", "LUAW")
            for kind in verbs:   # `line up runway 31 cleared for takeoff` is one takeoff clearance, not two sites
                m = _VERB_RE[kind].search(text)
                near = _runway_near(text, m.span()) if m else None
                if near:
                    sites.append(Site(k, kind, near[0], near[1], near[2], m.span()))
        for m in _RELEASE_RE.finditer(text):
            to = "vacated" if m.group("vacated") else ("ground" if m.group("to") in ("ground", "apron") else "departure")
            sites.append(Site(k, "RELEASE", None, released=_RELEASES[to]))
    seen, unique = set(), []
    for s in sorted(sites, key=lambda s: (s.index, s.edit_span)):   # "cross runway 13 cross runway 13" is one site
        if s.kind == "RELEASE" or (s.index, s.kind, s.runway) not in seen:
            seen.add((s.index, s.kind, s.runway))
            unique.append(s)
    return unique


def _replace(text: str, span: tuple[int, int], new: str) -> str:
    return text[:span[0]] + new + text[span[1]:]


def _releases(sites: list[Site], kind: str, lo: int, hi: int) -> list[Site]:
    """Release sites strictly between transmissions `lo` and `hi` that free a reservation of `kind`."""
    return [s for s in sites if s.kind == "RELEASE" and lo < s.index < hi and kind in s.released]


def candidates(recording_id: int, txs: list[Transmission]) -> list[Injection]:
    """Every text edit the first four kinds allow in one recording. A and B are in different transmissions, and no
    release of A's kind lies between them (except the one release_delete removes)."""
    sites = scan(txs)
    out: list[Injection] = []
    for a in (s for s in sites if s.kind in RESERVATION_KINDS):
        for b in sites:
            if b.index <= a.index:
                continue
            text = txs[b.index].text
            between = _releases(sites, a.kind, a.index, b.index)
            if not between and b.kind in RESERVATION_KINDS and b.runway != a.runway and MATRIX[(b.kind, a.kind)] == "alert":
                out.append(Injection(recording_id, "runway_swap", a.index, b.index, a.runway,
                                     _replace(text, b.rwy_span, a.words)))
            if not between and b.kind == "HOLD_SHORT" and MATRIX[("CROSS", a.kind)] == "alert":
                out.append(Injection(recording_id, "holdshort_to_cross", a.index, b.index, a.runway,
                                     _replace(text, b.edit_span, f"cross runway {a.words}")))
            if not between and a.kind == "LAND" and b.kind in ("LUAW", "LAND") and b.runway == a.runway:
                upgraded = _replace(text, b.edit_span, "cleared for takeoff")
                out.append(Injection(recording_id, "verb_upgrade", a.index, b.index, a.runway,
                                     re.sub(r" and wait\b", "", upgraded, count=1)))
            if len(between) == 1 and b.kind in RESERVATION_KINDS and b.runway == a.runway \
                    and MATRIX[(b.kind, a.kind)] == "alert":
                out.append(Injection(recording_id, "release_delete", a.index, b.index, a.runway, text,
                                     deleted=between[0].index))
    return list(dict.fromkeys(out))   # two sites of one transmission can yield the same edit


def splice_anchor(txs: list[Transmission]) -> Site | None:
    """The reservation a recording ends holding: its last reservation site with no release of that kind after it."""
    sites = scan(txs)
    held = [a for a in sites if a.kind in RESERVATION_KINDS and not _releases(sites, a.kind, a.index, len(txs))]
    return held[-1] if held else None


def splice_candidate(x_id: int, x_txs: list[Transmission], x_end: float,
                     y_id: int, y_txs: list[Transmission]) -> Injection | None:
    """X followed by Y, if X ends holding A and Y's first clearance on A's runway conflicts with A within A's staleness
    timeout. None otherwise."""
    a = splice_anchor(x_txs)
    if a is None:
        return None
    b = next((s for s in scan(y_txs) if s.kind in RESERVATION_KINDS and s.runway == a.runway), None)
    if b is None or MATRIX[(b.kind, a.kind)] != "alert":
        return None
    offset = x_end + SPLICE_GAP_S - y_txs[0].start_s
    if y_txs[b.index].start_s + offset - x_txs[a.index].start_s > STALE_S[a.kind]:
        return None
    return Injection(x_id, "splice", a.index, len(x_txs) + b.index, a.runway, y_txs[b.index].text,
                     second=y_id, offset=offset)


def select(found: list[Injection], n: int, seed: int) -> list[Injection]:
    """Up to `n` injections, stratified across EDIT_KINDS by round robin (a kind that runs out leaves its share to the
    others), at most one per (original recording, kind), chosen with `seed`."""
    rng = random.Random(seed)
    by_kind: dict[str, list[Injection]] = {}
    for kind in EDIT_KINDS:
        per_recording: dict[int, list[Injection]] = {}
        for inj in found:
            if inj.edit_kind == kind:
                per_recording.setdefault(inj.recording_id, []).append(inj)
        picks = [rng.choice(v) for _, v in sorted(per_recording.items())]
        rng.shuffle(picks)
        by_kind[kind] = picks
    chosen: list[Injection] = []
    while len(chosen) < n and any(by_kind.values()):
        for kind in EDIT_KINDS:
            if by_kind[kind] and len(chosen) < n:
                chosen.append(by_kind[kind].pop())
    return chosen


def _gold(conn: sqlite3.Connection, recording_id: int) -> list[Transmission]:
    return load_recording(conn, recording_id, "gold", default_transcript_model(conn, "gold", recording_id))


def pool(conn: sqlite3.Connection, recording_ids: list[int]) -> list[Injection]:
    """Every candidate of every kind over the given recordings' gold text; splices pair recordings from one airport."""
    txs = {rid: _gold(conn, rid) for rid in recording_ids}
    meta = {r["id"]: r for r in conn.execute(
        f"""SELECT r.id, r.airport_icao, MAX(x.end_s) AS end_s FROM recordings r JOIN transmissions x ON x.recording_id = r.id
            WHERE r.id IN ({','.join('?' * len(recording_ids))}) GROUP BY r.id""", recording_ids)}
    out = [c for rid in recording_ids for c in candidates(rid, txs[rid])]
    for x in recording_ids:
        if splice_anchor(txs[x]) is None:
            continue
        for y in recording_ids:
            if y != x and txs[y] and meta[y]["airport_icao"] == meta[x]["airport_icao"]:
                c = splice_candidate(x, txs[x], meta[x]["end_s"] or txs[x][-1].start_s, y, txs[y])
                if c:
                    out.append(c)
    return out


def generate(conn: sqlite3.Connection, recording_ids: list[int], n: int = 100, seed: int = 0) -> list[Injection]:
    """`select` over `pool`."""
    return select(pool(conn, recording_ids), n, seed)


def _source_id(conn: sqlite3.Connection) -> int:
    conn.execute("INSERT OR IGNORE INTO sources (name, kind, notes) VALUES (?, 'corpus', ?)",
                 (SOURCE, "conflicts injected into real gold transcripts by atcdb/inject.py; same licence as the originals"))
    return conn.execute("SELECT id FROM sources WHERE name = ?", (SOURCE,)).fetchone()[0]


def write_injection(conn: sqlite3.Connection, inj: Injection, seed: int, ordinal: int) -> int:
    """Store one injection as a new recording and return its id. Idempotent: an injection already stored under the same
    external id (`<original id>-<kind>-<seed>-<ordinal>`) is returned as is. Transmissions are copied with their timing
    (a splice's second recording shifted by `offset`, its external ids prefixed `b:`), role and clip path, with
    `pcm_sha1` NULL. Gold transcripts are model `synthetic`, and only an edited trigger's text differs. ASR transcripts
    are copied too, except an edited trigger's, which holds the edited gold text under model_version `synthetic`, since
    its audio does not contain the edit."""
    source = _source_id(conn)
    external_id = f"{inj.recording_id}-{inj.edit_kind}-{seed}-{ordinal}"
    row = conn.execute("SELECT id FROM recordings WHERE source_id = ? AND external_id = ?", (source, external_id)).fetchone()
    if row:
        return row[0]
    parts = [(inj.recording_id, 0.0, "")] + ([(inj.second, inj.offset, "b:")] if inj.second is not None else [])
    txs = [tx for rid, _, _ in parts for tx in _gold(conn, rid)]
    deleted_id = txs[inj.deleted].id if inj.deleted is not None else None
    edited_id = txs[inj.trigger].id if inj.after != txs[inj.trigger].text else None
    rid = conn.execute(
        """INSERT INTO recordings (source_id, external_id, airport_icao, facility, frequency_mhz, started_at_utc, path)
           SELECT ?, ?, airport_icao, facility, frequency_mhz, started_at_utc, path FROM recordings WHERE id = ?""",
        (source, external_id, inj.recording_id)).lastrowid
    new_ids: dict[int, int] = {}
    for part, offset, prefix in parts:
        for x in conn.execute("SELECT * FROM transmissions WHERE recording_id = ? ORDER BY start_s, id", (part,)).fetchall():
            if x["id"] == deleted_id:
                continue
            new_ids[x["id"]] = conn.execute(
                """INSERT INTO transmissions (recording_id, external_id, start_s, end_s, duration_s, speaker_role,
                                              speaker_label, pilot_callsign, clip_path, sample_rate, pcm_sha1, split)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, ?)""",
                (rid, prefix + x["external_id"], None if x["start_s"] is None else x["start_s"] + offset,
                 None if x["end_s"] is None else x["end_s"] + offset, x["duration_s"], x["speaker_role"],
                 x["speaker_label"], x["pilot_callsign"], x["clip_path"], x["sample_rate"], x["split"])).lastrowid
    for tx in txs:
        if tx.id == deleted_id:
            continue
        text = inj.after if tx.id == edited_id else tx.text
        conn.execute("""INSERT INTO transcripts (transmission_id, kind, model, raw_text, normalized_text)
                        VALUES (?, 'gold', ?, ?, ?)""", (new_ids[tx.id], TRANSCRIPT_MODEL, text, text))
    for t in conn.execute(
            f"""SELECT * FROM transcripts WHERE kind = 'asr'
                AND transmission_id IN ({','.join('?' * len(new_ids))}) ORDER BY id""", list(new_ids)).fetchall():
        edited = t["transmission_id"] == edited_id
        conn.execute(
            """INSERT INTO transcripts (transmission_id, kind, model, model_version, raw_text, normalized_text, confidence, words_json)
               VALUES (?, 'asr', ?, ?, ?, ?, ?, ?)""",
            (new_ids[t["transmission_id"]], t["model"], ASR_VERSION if edited else t["model_version"],
             inj.after if edited else t["raw_text"], inj.after if edited else t["normalized_text"],
             None if edited else t["confidence"], None if edited else t["words_json"]))
    first_of_y = next((tx.id for tx in _gold(conn, inj.second)), None) if inj.second is not None else None
    notes = {"original_recording_id": inj.recording_id, "second_recording_id": inj.second, "edit_kind": inj.edit_kind,
             "anchor_tx": new_ids[txs[inj.anchor].id], "trigger_tx": new_ids[txs[inj.trigger].id],
             "splice_tx": new_ids[first_of_y] if first_of_y else None, "runway": inj.runway, "seed": seed,
             "before": txs[inj.trigger].text, "after": inj.after,
             "deleted": txs[inj.deleted].text if inj.deleted is not None else None}
    conn.execute("UPDATE recordings SET notes = ? WHERE id = ?", (json.dumps(notes), rid))
    conn.commit()
    return rid


def synthetic_recordings(conn: sqlite3.Connection, valid_only: bool = False) -> list[dict]:
    """Every stored injection: {"recording_id", "external_id", **notes}. With `valid_only`, only those a human marked
    `valid: yes` (the positive set)."""
    rows = conn.execute(
        """SELECT r.id, r.external_id, r.notes FROM recordings r JOIN sources s ON s.id = r.source_id
           WHERE s.name = ? ORDER BY r.id""", (SOURCE,)).fetchall()
    out = [{"recording_id": r["id"], "external_id": r["external_id"], **json.loads(r["notes"])} for r in rows]
    return [o for o in out if o.get("valid") == "yes"] if valid_only else out


CHECK_COLUMNS = ["recording_id", "external_id", "edit_kind", "runway", "context", "before", "after", "valid", "notes"]


def check_rows(conn: sqlite3.Connection) -> list[dict]:
    """The human check sheet: one row per injection, with the lines from just before A to just after B (A and B
    marked, a splice's join shown), B before and after the edit, and any verdict already recorded."""
    rows = []
    for inj in synthetic_recordings(conn):
        txs = load_recording(conn, inj["recording_id"], "gold", TRANSCRIPT_MODEL)
        ids = [tx.id for tx in txs]
        a, b = ids.index(inj["anchor_tx"]), ids.index(inj["trigger_tx"])
        lines = []
        for k in range(max(0, a - 1), min(len(txs), b + 2)):
            if txs[k].id == inj.get("splice_tx"):
                lines.append(f"--- recording {inj['second_recording_id']} follows ---")
            mark = "A>" if k == a else "B>" if k == b else "  "
            lines.append(f"{mark} [{txs[k].role}] {txs[k].text}")
        if inj["deleted"]:
            lines.append(f"(deleted release: {inj['deleted']})")
        rows.append({"recording_id": inj["recording_id"], "external_id": inj["external_id"], "edit_kind": inj["edit_kind"],
                     "runway": inj["runway"], "context": "\n".join(lines), "before": inj["before"], "after": inj["after"],
                     "valid": inj.get("valid", ""), "notes": inj.get("check_notes", "")})
    return rows


def apply_check(conn: sqlite3.Connection, rows: list[dict]) -> dict[str, int]:
    """Record each row's `valid` (yes | no; blank = not checked yet) and `notes` in the injection's recording notes.
    Returns counts of yes, no and blank. Raises ValueError on any other value, before writing anything."""
    counts = {"yes": 0, "no": 0, "": 0}
    for r in rows:
        v = (r.get("valid") or "").strip().lower()
        if v not in counts:
            raise ValueError(f"recording {r['recording_id']}: valid must be yes, no or blank, not {r['valid']!r}")
        counts[v] += 1
    for r in rows:
        notes = json.loads(conn.execute("SELECT notes FROM recordings WHERE id = ?", (int(r["recording_id"]),)).fetchone()[0])
        v = (r.get("valid") or "").strip().lower()
        if v:
            notes["valid"] = v
        else:
            notes.pop("valid", None)
        notes["check_notes"] = r.get("notes") or ""
        conn.execute("UPDATE recordings SET notes = ? WHERE id = ?", (json.dumps(notes), int(r["recording_id"])))
    conn.commit()
    return counts
```

Create `scripts/inject_conflicts.py`:

```python
#!/usr/bin/env python3
"""Inject synthetic runway conflicts into real tower recordings (spec 2026-09-29-evaluation-3b1-design.md, section 4).

Usage:
    python scripts/inject_conflicts.py [--n 100] [--seed 0] [--dry-run] [--db data/atc.sqlite]
    python scripts/inject_conflicts.py --sheet data/labels/injection_check.csv
    python scripts/inject_conflicts.py --apply-sheet data/labels/injection_check.csv

The first form stores up to N injections under the `synthetic-conflicts` source (re-running with the same seed changes
nothing); run ASR on the originals first, since each synthetic recording copies their ASR transcripts. `--dry-run`
prints the candidates per edit kind and what would be chosen, and writes nothing. `--sheet` writes the human check
sheet (verdicts already recorded are kept); fill `valid` with yes or no:

    yes = B is addressed to a different aircraft from A, A has not been released or cancelled before B (for
          release_delete: the deleted transmission was A's own release; for splice: nothing at the end of the first
          recording lets A's aircraft off the runway), and B still reads as plausible phraseology.

`--apply-sheet` records the verdicts; only `valid=yes` injections are scored as positives.
"""
import argparse
import csv
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from atcdb.inject import CHECK_COLUMNS, EDIT_KINDS, apply_check, check_rows, pool, select, write_injection  # noqa: E402
from atcdb.replay import real_recordings  # noqa: E402
from atcdb.schema import init_db  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", type=Path, default=ROOT / "data/atc.sqlite")
    ap.add_argument("--n", type=int, default=100)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--dry-run", action="store_true", help="count candidates and the selection, write nothing")
    ap.add_argument("--sheet", type=Path, help="write the human check sheet to this CSV")
    ap.add_argument("--apply-sheet", type=Path, help="record the verdicts in this filled check sheet")
    args = ap.parse_args()
    conn = init_db(args.db)

    if args.sheet:
        rows = check_rows(conn)
        args.sheet.parent.mkdir(parents=True, exist_ok=True)
        with args.sheet.open("w", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=CHECK_COLUMNS)
            w.writeheader()
            w.writerows(rows)
        print(f"wrote {args.sheet} ({len(rows)} injections)")
        return
    if args.apply_sheet:
        with args.apply_sheet.open(newline="") as fh:
            counts = apply_check(conn, list(csv.DictReader(fh)))
        print(f"recorded: {counts['yes']} valid, {counts['no']} rejected, {counts['']} not yet checked")
        return

    candidates = pool(conn, [r["id"] for r in real_recordings(conn)])
    chosen = select(candidates, args.n, args.seed)
    available = Counter(c.edit_kind for c in candidates)
    picked = Counter(c.edit_kind for c in chosen)
    for kind in EDIT_KINDS:
        print(f"  {kind:<20} {available[kind]:>4} candidates, {picked[kind]:>3} chosen")
    if args.dry_run:
        print(f"dry run: {len(chosen)} injections would be stored")
        return
    ids = [write_injection(conn, inj, args.seed, i) for i, inj in enumerate(chosen)]
    print(f"stored {len(ids)} synthetic recordings (source synthetic-conflicts); next: --sheet")


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_inject.py -q` then `.venv/bin/python -m pytest -q`
Expected: PASS; the whole suite is 244 passed with `ANTHROPIC_API_KEY` set (243 passed and 1 skipped without it).

- [ ] **Step 5: Check the generator on a copy of the corpus (skip if `data/atc.sqlite` is absent)**

Never write synthetic recordings into `data/atc.sqlite` during the plan: that is an operational step after it.

Run: `cp data/atc.sqlite /tmp/inject-check.sqlite && .venv/bin/python scripts/inject_conflicts.py --db /tmp/inject-check.sqlite --dry-run`
Expected (the corpus as of 2026-09-29):
```
  runway_swap             1 candidates,   1 chosen
  holdshort_to_cross      6 candidates,   5 chosen
  verb_upgrade            1 candidates,   1 chosen
  release_delete          2 candidates,   1 chosen
  splice               8141 candidates,  92 chosen
dry run: 100 injections would be stored
```
Then run it without `--dry-run`, twice (the second run stores nothing new), and
`.venv/bin/python scripts/inject_conflicts.py --db /tmp/inject-check.sqlite --sheet /tmp/injection_check.csv`, and read
a few rows: A and B are marked and a splice shows `--- recording N follows ---`. Delete both files.

- [ ] **Step 6: Commit**

```bash
git add atcdb/inject.py scripts/inject_conflicts.py tests/test_inject.py
git commit -m "feat: synthetic conflict injection with a human check sheet"
```
End the message with the attribution lines the session provides.

---

### Task 3: Running arms and scoring them

An *arm* is one (parser, model, context, transcript) configuration; there are 18. `run_arm` replays every
recording of the evaluation sets through the existing `build_timeline`, so parses come from and go to the `events`
cache exactly as in the app, and keeps one JSON row per recording. Scoring is pure and reads only rows: a positive is
a strict hit when an alert on the injected runway is raised by the trigger transmission, a lenient hit when it is
raised at or after it (Austin fired late, at a re-confirmation), partial when only a warning is. False alarms per hour
need adjudication verdicts (Task 4); without a verdict for every alert the rate raises `Pending` rather than guess. A
row is scored only when its replay finished and every gold-transcribed transmission has a transcript of the arm's kind
(ASR covers only the test split until the `train` ASR run, an operational step).

**Files:**
- Create: `atcdb/evaluate.py`
- Create: `scripts/eval_conflicts.py` (the `run` subcommand)
- Test: `tests/test_evaluate.py`

**Interfaces:**
- Consumes: `inject.synthetic_recordings`, `inject.generate`, `inject.write_injection`, `inject.check_rows`,
  `inject.apply_check` (Task 2); `replay.real_recordings` (Task 1); `replay.build_timeline`, `replay.uncached_parses`,
  `parse_llm.estimate_cost`, `parse_llm.render_prompt`.
- Produces: `Arm(parser, model, context, transcript)` with `.name`; `ARMS` (18), `PRIMARY` (rules vs Sonnet, window,
  gold); `evaluation_sets(conn) -> list[(recording_id, set, truth)]`; `recording_row`, `run_arm(db, arm, items,
  workers=1)`, `uncached(conn, arm, ids) -> (calls, usd)`, `write_rows`, `read_rows`; `usable`, `detection`, `recall`;
  `Pending`, `alert_key`, `alert_keys`, `false_alarm_units`, `per_hour`; `bootstrap`, `paired_bootstrap`, `rate`,
  `cohen_kappa`. A row is `{"recording_id", "set", "truth", "span_s", "all_test", "missing_transcripts",
  "incomplete", "dropped", "tx_ids", "t", "events", "conflicts"}`; a conflict is `{"type", "severity", "runway",
  "callsigns", "tx_id", "step"}`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_evaluate.py`:

```python
import pytest

from atcdb.evaluate import (ARMS, PRIMARY, Arm, Pending, alert_key, alert_keys, bootstrap, cohen_kappa, detection,
                            evaluation_sets, false_alarm_units, paired_bootstrap, per_hour, rate, read_rows, recall,
                            recording_row, run_arm, uncached, usable, write_rows)
from atcdb.inject import apply_check, check_rows, generate, write_injection
from atcdb.schema import init_db


def _seed(conn, turns, external_id="r1", split="test"):
    """One tower recording with human gold transcripts at 10 s spacing (each 3 s long). Returns its id."""
    conn.execute("INSERT OR IGNORE INTO sources (id, name, kind) VALUES (1, 'test', 'corpus')")
    rid = conn.execute("INSERT INTO recordings (source_id, external_id, facility, airport_icao) VALUES (1, ?, 'Tower', 'LKPR')",
                       (external_id,)).lastrowid
    for i, (role, text) in enumerate(turns):
        xid = conn.execute(
            """INSERT INTO transmissions (recording_id, external_id, start_s, end_s, speaker_role, split)
               VALUES (?, ?, ?, ?, ?, ?)""", (rid, f"x{i}", 10.0 * i, 10.0 * i + 3, role, split)).lastrowid
        conn.execute("INSERT INTO transcripts (transmission_id, kind, model, raw_text, normalized_text) VALUES (?, 'gold', 'human', ?, ?)",
                     (xid, text, text))
    conn.commit()
    return rid


CONFLICT = [
    ("controller", "csa one two three runway three one cleared to land wind calm"),
    ("pilot", "cleared to land runway three one csa one two three"),
    ("controller", "lufthansa four five six cross runway three one"),
    ("pilot", "crossing runway three one lufthansa four five six"),
]
QUIET = [
    ("controller", "csa one two three runway three one cleared to land wind calm"),
    ("pilot", "cleared to land runway three one csa one two three"),
    ("controller", "lufthansa four five six hold short of runway one three"),
    ("pilot", "holding short one three lufthansa four five six"),
]


def test_the_arms_cover_every_extractor_context_and_transcript():
    assert len(ARMS) == 18 and len(set(ARMS)) == 18
    assert {a.parser for a in ARMS} == {"rule", "llm"} and {a.transcript for a in ARMS} == {"gold", "asr"}
    assert PRIMARY == (Arm("rule", "rules", "window", "gold"), Arm("llm", "claude-sonnet-5", "window", "gold"))
    assert PRIMARY[1].name == "llm-claude-sonnet-5-window-gold"


def test_evaluation_sets_are_real_recordings_plus_valid_injections(tmp_path):
    conn = init_db(tmp_path / "t.sqlite")
    rid = _seed(conn, QUIET + [("controller", "jet one line up runway one three")])
    for i, inj in enumerate(generate(conn, [rid], n=10, seed=0)):
        write_injection(conn, inj, seed=0, ordinal=i)
    rows = check_rows(conn)
    rows[0]["valid"] = "yes"
    apply_check(conn, rows)
    sets = evaluation_sets(conn)
    assert sets[0] == (rid, "negatives", None) and len(sets) == 2
    sid, name, truth = sets[1]
    assert name == "positives" and set(truth) == {"runway", "trigger_tx", "edit_kind"}


def test_recording_row_keeps_steps_conflicts_and_span(tmp_path):
    conn = init_db(tmp_path / "t.sqlite")
    rid = _seed(conn, CONFLICT)
    row = recording_row(conn, PRIMARY[0], rid, "negatives", None)
    assert row["span_s"] == 33.0 and row["all_test"] is True and row["incomplete"] is False
    assert len(row["tx_ids"]) == 4 and row["t"] == [0.0, 10.0, 20.0, 30.0]
    assert row["events"][0] == [["LAND", "csa one two three", "31", None]]
    [c] = row["conflicts"]
    assert (c["type"], c["severity"], c["runway"], c["step"], c["tx_id"]) == ("RUNWAY", "alert", "31", 2, row["tx_ids"][2])
    assert c["callsigns"] == ["lufthansa four five six", "csa one two three"]
    assert row["missing_transcripts"] == 0 and usable(row)
    asr_arm = Arm("rule", "rules", "window", "asr")
    asr = recording_row(conn, asr_arm, rid, "negatives", None)
    assert asr["tx_ids"] == [] and asr["span_s"] == 33.0 and not usable(asr)   # no ASR yet: same span, not scored
    conn.execute("""INSERT INTO transcripts (transmission_id, kind, model, raw_text, normalized_text)
                    VALUES (?, 'asr', 'whisper', 'x', 'x')""", (row["tx_ids"][0],))
    partial = recording_row(conn, asr_arm, rid, "negatives", None)
    assert partial["missing_transcripts"] == 3 and not usable(partial)        # an ASR run that has not finished


def test_run_arm_is_the_same_serial_and_threaded_and_round_trips_through_jsonl(tmp_path):
    db = tmp_path / "t.sqlite"
    conn = init_db(db)
    items = [(_seed(conn, CONFLICT, external_id=f"r{i}"), "negatives", None) for i in range(4)]
    serial = run_arm(db, PRIMARY[0], items)
    assert run_arm(db, PRIMARY[0], items, workers=3) == serial
    write_rows(tmp_path / "out" / "a.jsonl", serial)
    assert read_rows(tmp_path / "out" / "a.jsonl") == serial


def test_uncached_counts_what_an_arm_still_has_to_parse(tmp_path):
    db = tmp_path / "t.sqlite"
    conn = init_db(db)
    rid = _seed(conn, CONFLICT)
    assert uncached(conn, PRIMARY[0], [rid]) == (4, 0.0)
    run_arm(db, PRIMARY[0], [(rid, "negatives", None)])
    assert uncached(conn, PRIMARY[0], [rid]) == (0, 0.0)
    n, cost = uncached(conn, PRIMARY[1], [rid])
    assert n == 4 and cost > 0


def _row(conflicts, tx_ids=(1, 2, 3, 4), truth=None, span=36.0, incomplete=False, rid=7, missing=0):
    return {"recording_id": rid, "set": "positives" if truth else "negatives", "truth": truth, "span_s": span,
            "incomplete": incomplete, "missing_transcripts": missing, "tx_ids": list(tx_ids), "conflicts": conflicts}


def _c(step, severity="alert", runway="31", type_="RUNWAY", tx=None):
    return {"type": type_, "severity": severity, "runway": runway, "callsigns": ["a", "b"], "step": step,
            "tx_id": tx if tx is not None else step + 1}


TRUTH = {"runway": "31", "trigger_tx": 3, "edit_kind": "splice"}


@pytest.mark.parametrize("conflicts, expected", [
    ([_c(2)], "strict"),
    ([_c(3)], "lenient"),                          # fired late, at a re-confirmation
    ([_c(2, severity="warning")], "partial"),
    ([_c(1)], "miss"),                             # before the trigger: not the injected conflict
    ([_c(2, runway="13")], "miss"),
    ([_c(2, type_="READBACK")], "miss"),
    ([], "miss"),
])
def test_detection(conflicts, expected):
    assert detection(_row(conflicts, truth=TRUTH)) == expected


def test_detection_of_a_trigger_without_a_transcript_is_unscorable():
    assert detection(_row([_c(1)], tx_ids=(1, 2), truth=TRUTH)) == "unscorable"


def test_recall_counts_strict_inside_lenient_and_skips_what_cannot_be_scored():
    rows = [_row([_c(2)], truth=TRUTH), _row([_c(3)], truth=TRUTH), _row([_c(2, severity="warning")], truth=TRUTH),
            _row([], truth=TRUTH), _row([_c(2)], truth=TRUTH, incomplete=True), _row([], tx_ids=(1,), truth=TRUTH),
            _row([_c(2)], truth=TRUTH, missing=1)]
    assert recall(rows) == {"n": 4, "strict": 1, "lenient": 2, "partial": 1, "miss": 1}


def test_alert_keys_ignore_callsigns_and_warnings():
    row = _row([_c(2), {**_c(2), "callsigns": ["", "b"]}, _c(3, severity="warning"), _c(1, type_="READBACK")])
    assert alert_keys(row) == {"7:RUNWAY:31:3", "7:READBACK:31:2"}
    assert alert_keys(row, "RUNWAY") == {"7:RUNWAY:31:3"}
    assert alert_key(7, _c(0, runway=None)) == "7:RUNWAY:-:1"


def test_false_alarms_per_hour_use_verdicts_and_refuse_to_guess():
    rows = [_row([_c(2)], span=1800.0, rid=1), _row([_c(0), _c(3)], span=1800.0, rid=2), _row([], span=3600.0, rid=3),
            _row([_c(2)], span=3600.0, rid=4, incomplete=True)]
    verdicts = {"1:RUNWAY:31:3": "parse_error", "2:RUNWAY:31:1": "genuine", "2:RUNWAY:31:4": "missing_info"}
    units = false_alarm_units(rows, verdicts)
    assert units == [(1.0, 1800.0), (1.0, 1800.0), (0.0, 3600.0)]
    assert per_hour(units) == 1.0                  # two false alarms over two hours; the genuine one does not count
    with pytest.raises(Pending, match="1 alerts"):
        false_alarm_units(rows, {k: v for k, v in verdicts.items() if k != "2:RUNWAY:31:4"})
    assert false_alarm_units(rows, {}, conflict_type="READBACK") == [(0.0, 1800.0), (0.0, 1800.0), (0.0, 3600.0)]


def test_bootstrap_is_seeded_and_brackets_the_point_estimate():
    units = [1.0] * 30 + [0.0] * 70
    lo, hi = bootstrap(units, rate, seed=0)
    assert (lo, hi) == bootstrap(units, rate, seed=0)
    assert lo < 0.3 < hi and 0.15 < lo and hi < 0.45
    assert bootstrap([], rate) == (0.0, 0.0)
    assert bootstrap([1.0] * 5, rate) == (1.0, 1.0)


def test_paired_bootstrap_of_a_difference():
    pairs = [(1.0, 0.0)] * 20 + [(1.0, 1.0)] * 20 + [(0.0, 0.0)] * 60
    point, lo, hi = paired_bootstrap(pairs, rate, seed=0)
    assert point == pytest.approx(0.2) and lo > 0 and lo < 0.2 < hi
    same = [(1.0, 1.0)] * 10 + [(0.0, 0.0)] * 10
    assert paired_bootstrap(same, rate) == (0.0, 0.0, 0.0)   # paired draws: identical arms never differ


def test_cohen_kappa():
    assert cohen_kappa(["a", "b", "a", "b"], ["a", "b", "a", "b"]) == 1.0
    assert cohen_kappa(["a", "a"], ["a", "a"]) == 1.0
    assert cohen_kappa(["a", "a", "b", "b"], ["a", "b", "a", "b"]) == 0.0
    assert cohen_kappa(["a", "a", "a", "b"], ["a", "a", "b", "b"]) == pytest.approx(0.5)
    with pytest.raises(ValueError):
        cohen_kappa(["a"], [])
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_evaluate.py -q`
Expected: FAIL at collection with `ModuleNotFoundError: No module named 'atcdb.evaluate'`.

- [ ] **Step 3: Write the implementation**

Create `atcdb/evaluate.py`:

```python
"""Level 2 evaluation: run arms over recordings, then score (spec 2026-09-29-evaluation-3b1-design.md, sections 5 to 9).

An *arm* is one (parser, model, context, transcript) configuration. `run_arm` replays every recording of a set through
`build_timeline` (so parses come from, and go to, the `events` cache exactly as in the app) and returns one row per
recording; `write_rows`/`read_rows` keep them as JSONL. Everything below `read_rows` is pure: scoring reads rows, the
injection truth carried on positive rows, and the adjudication verdicts, and never touches the database.
"""
import json
import random
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable

from atcdb import parse_llm
from atcdb.inject import synthetic_recordings
from atcdb.parsing import CONTEXT_MODES, event_to_row
from atcdb.replay import build_timeline, default_transcript_model, load_recording, real_recordings, uncached_parses
from atcdb.schema import connect

TRANSCRIPTS = ("gold", "asr")


@dataclass(frozen=True)
class Arm:
    parser: str       # rule | llm
    model: str        # "rules", or a Claude model id
    context: str      # none | role | window
    transcript: str   # gold | asr

    @property
    def name(self) -> str:
        return f"{self.parser}-{self.model}-{self.context}-{self.transcript}"


ARMS: tuple[Arm, ...] = tuple(Arm(p, m, c, t) for p, models in (("rule", ("rules",)), ("llm", parse_llm.MODELS))
                              for m in models for c in CONTEXT_MODES for t in TRANSCRIPTS)
# the pre-registered primary comparison (spec addendum A.5): rules vs Sonnet, window context, human transcripts
PRIMARY = (Arm("rule", "rules", "window", "gold"), Arm("llm", "claude-sonnet-5", "window", "gold"))


# --- sets and running ---------------------------------------------------------------------------------------------

def evaluation_sets(conn: sqlite3.Connection) -> list[tuple[int, str, dict | None]]:
    """(recording_id, set, truth) for every recording scored: `negatives` are the real replayable tower recordings (by
    their gold transcripts, so both transcript arms score the same recordings); `positives` are the injections a human
    marked valid, each with its truth (runway, trigger transmission, kind)."""
    out: list[tuple[int, str, dict | None]] = [(r["id"], "negatives", None) for r in real_recordings(conn)]
    for inj in synthetic_recordings(conn, valid_only=True):
        out.append((inj["recording_id"], "positives", {"runway": inj["runway"], "trigger_tx": inj["trigger_tx"],
                                                       "edit_kind": inj["edit_kind"]}))
    return out


def recording_row(conn: sqlite3.Connection, arm: Arm, recording_id: int, set_name: str, truth: dict | None) -> dict:
    """Replay one recording under one arm and keep what scoring needs: per step the transmission, its time and events,
    and every conflict with the step that raised it. `span_s` covers all the recording's transmissions (first start to
    last end), whatever the transcript kind, so both transcript arms share a denominator. `missing_transcripts` counts
    transmissions with a gold transcript but none of the arm's kind (an ASR run that has not reached them); such a row
    is not scored. `all_test` says whether every transmission is in the ASR model's `test` split (spec section 3: the
    clean ASR headline)."""
    tl = build_timeline(conn, recording_id, parser=arm.parser, transcript_kind=arm.transcript, context=arm.context,
                        model=arm.model, transcript_model=default_transcript_model(conn, arm.transcript, recording_id))
    span, all_test = conn.execute(
        """SELECT MAX(end_s) - MIN(start_s), MIN(CASE WHEN split = 'test' THEN 1 ELSE 0 END)
           FROM transmissions WHERE recording_id = ?""", (recording_id,)).fetchone()
    gold = {tx.id for tx in load_recording(conn, recording_id, "gold", default_transcript_model(conn, "gold", recording_id))}
    return {"recording_id": recording_id, "set": set_name, "truth": truth, "span_s": span or 0.0,
            "all_test": bool(all_test), "missing_transcripts": len(gold - {s.tx.id for s in tl.steps}),
            "incomplete": any(s.error for s in tl.steps), "dropped": tl.dropped,
            "tx_ids": [s.tx.id for s in tl.steps], "t": [s.tx.start_s for s in tl.steps],
            "events": [[list(event_to_row(e)) for e in s.events] for s in tl.steps],
            "conflicts": [{"type": c.type, "severity": c.severity, "runway": c.runway, "callsigns": list(c.callsigns),
                           "tx_id": s.tx.id, "step": k} for k, s in enumerate(tl.steps) for c in s.conflicts]}


def run_arm(db: Path, arm: Arm, recordings: list[tuple[int, str, dict | None]], workers: int = 1) -> list[dict]:
    """`recording_row` for every recording, in order. With `workers` > 1, recordings run on a thread pool, each thread
    with its own connection (a `window` replay stays sequential inside its recording; `get_events` settles two threads
    racing to cache the same transcript)."""
    def one(item: tuple[int, str, dict | None]) -> dict:
        conn = connect(db)
        try:
            return recording_row(conn, arm, *item)
        finally:
            conn.close()

    if workers <= 1:
        return [one(item) for item in recordings]
    with ThreadPoolExecutor(max_workers=workers) as pool:
        return list(pool.map(one, recordings))


def uncached(conn: sqlite3.Connection, arm: Arm, recording_ids: Iterable[int]) -> tuple[int, float]:
    """(transmissions still to parse, rough USD) for one arm over the given recordings; parses and stores nothing."""
    misses = [m for rid in recording_ids for m in uncached_parses(
        conn, rid, parser=arm.parser, transcript_kind=arm.transcript, context=arm.context, model=arm.model,
        transcript_model=default_transcript_model(conn, arm.transcript, rid))]
    cost = parse_llm.estimate_cost(arm.model, [parse_llm.render_prompt(tx, ctx) for tx, ctx in misses]) \
        if arm.parser == "llm" else 0.0
    return len(misses), cost


def write_rows(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w") as fh:
        for r in rows:
            fh.write(json.dumps(r) + "\n")


def read_rows(path: Path) -> list[dict]:
    with path.open() as fh:
        return [json.loads(line) for line in fh if line.strip()]


# --- positives ------------------------------------------------------------------------------------------------------

def usable(row: dict) -> bool:
    """A row that can be scored: its replay finished (no parse failure) and every transmission had a transcript of the
    arm's kind."""
    return not row["incomplete"] and bool(row["tx_ids"]) and not row["missing_transcripts"]


def detection(row: dict) -> str:
    """How an arm did on one positive: `strict` (an alert on the injected runway raised by the trigger transmission),
    `lenient` (an alert on that runway at or after the trigger, but not at it), `partial` (only a warning there),
    `miss`, or `unscorable` (the trigger has no transcript of this arm's kind)."""
    truth = row["truth"]
    if truth["trigger_tx"] not in row["tx_ids"]:
        return "unscorable"
    k = row["tx_ids"].index(truth["trigger_tx"])
    hits = [c for c in row["conflicts"] if c["type"] == "RUNWAY" and c["runway"] == truth["runway"] and c["step"] >= k]
    alerts = [c for c in hits if c["severity"] == "alert"]
    if any(c["step"] == k for c in alerts):
        return "strict"
    if alerts:
        return "lenient"
    return "partial" if hits else "miss"


def recall(rows: list[dict]) -> dict[str, int]:
    """Counts over usable, scorable positives: `n`, `strict`, `lenient` (strict included), `partial`, `miss`."""
    out = {"n": 0, "strict": 0, "lenient": 0, "partial": 0, "miss": 0}
    for row in rows:
        d = detection(row) if usable(row) else "unscorable"
        if d == "unscorable":
            continue
        out["n"] += 1
        out[d] += 1
        if d == "strict":
            out["lenient"] += 1
    return out


# --- negatives -------------------------------------------------------------------------------------------------------

class Pending(Exception):
    """A false-alarm rate was asked for while some of its alerts have no adjudication verdict yet."""


def alert_key(recording_id: int, conflict: dict) -> str:
    """The adjudication key: one alert per (recording, type, runway, triggering transmission), whichever arm raised it
    and whichever callsigns it extracted (the rules parser often extracts none)."""
    return f"{recording_id}:{conflict['type']}:{conflict['runway'] or '-'}:{conflict['tx_id']}"


def alert_keys(row: dict, conflict_type: str | None = None) -> set[str]:
    """The distinct alert-severity conflicts in one row (optionally of one type), as adjudication keys."""
    return {alert_key(row["recording_id"], c) for c in row["conflicts"]
            if c["severity"] == "alert" and conflict_type in (None, c["type"])}


def false_alarm_units(rows: list[dict], verdicts: dict[str, str], conflict_type: str = "RUNWAY") -> list[tuple[float, float]]:
    """(false alarms, span_s) per usable negative row; a false alarm is an alert whose verdict is not `genuine`. Raises
    Pending if any alert has no verdict."""
    units, missing = [], 0
    for row in rows:
        if not usable(row):
            continue
        keys = alert_keys(row, conflict_type)
        missing += sum(k not in verdicts for k in keys)
        units.append((float(sum(verdicts.get(k) != "genuine" for k in keys)), row["span_s"]))
    if missing:
        raise Pending(f"{missing} alerts have no adjudication verdict")
    return units


def per_hour(units: list[tuple[float, float]]) -> float:
    """Sum of counts over hours of span."""
    hours = sum(span for _, span in units) / 3600
    return sum(n for n, _ in units) / hours if hours else 0.0


# --- statistics ------------------------------------------------------------------------------------------------------

def bootstrap(units: list, stat: Callable[[list], float], n: int = 2000, seed: int = 0) -> tuple[float, float]:
    """95% percentile interval of `stat` over `n` resamples (with replacement) of `units`."""
    if not units:
        return (0.0, 0.0)
    rng = random.Random(seed)
    values = sorted(stat([units[rng.randrange(len(units))] for _ in units]) for _ in range(n))
    return values[int(0.025 * n)], values[int(0.975 * n) - 1]


def paired_bootstrap(pairs: list[tuple], stat: Callable[[list], float], n: int = 2000,
                     seed: int = 0) -> tuple[float, float, float]:
    """(point, low, high) of stat(first) - stat(second) over `pairs` of units, both arms resampled with the same draws."""
    def diff(sample: list[tuple]) -> float:
        return stat([a for a, _ in sample]) - stat([b for _, b in sample])
    lo, hi = bootstrap(pairs, diff, n, seed)
    return diff(pairs), lo, hi


def rate(units: list[float]) -> float:
    """Mean of 0/1 units: a recall."""
    return sum(units) / len(units) if units else 0.0


def cohen_kappa(a: list[str], b: list[str]) -> float:
    """Cohen's kappa for two raters' labels of the same items, in order. 1.0 when both agree and use one label."""
    if len(a) != len(b) or not a:
        raise ValueError("kappa needs two equally long, non-empty label lists")
    labels = sorted(set(a) | set(b))
    n = len(a)
    observed = sum(x == y for x, y in zip(a, b)) / n
    expected = sum((a.count(lab) / n) * (b.count(lab) / n) for lab in labels)
    return 1.0 if expected == 1 else (observed - expected) / (1 - expected)
```

Create `scripts/eval_conflicts.py`:

```python
#!/usr/bin/env python3
"""Level 2 conflict evaluation (spec 2026-09-29-evaluation-3b1-design.md, sections 5 to 10).

Usage:
    python scripts/eval_conflicts.py run [--parser rule|llm] [--model M] [--context C] [--transcript gold|asr]
                                         [--set negatives|positives] [--workers N] [--dry-run]

`run` replays every recording of the evaluation sets under each selected arm (all 18 by default) and writes one JSONL
per arm to data/eval/conflicts/. Parses come from the events cache, so a re-run is free; always `--dry-run` first, which
prints the uncached calls and a rough cost per arm and spends nothing.
"""
import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from atcdb.evaluate import ARMS, evaluation_sets, run_arm, uncached, write_rows  # noqa: E402
from atcdb.schema import init_db  # noqa: E402

OUT = ROOT / "data/eval/conflicts"


def selected_arms(args: argparse.Namespace) -> list:
    return [a for a in ARMS if all(getattr(args, f) in (None, getattr(a, f)) for f in ("parser", "model", "context", "transcript"))]


def cmd_run(args: argparse.Namespace) -> None:
    conn = init_db(args.db)
    items = [it for it in evaluation_sets(conn) if args.set in (None, it[1])]
    arms = selected_arms(args)
    if not arms:
        sys.exit("no arm matches the filters")
    if args.dry_run:
        total = 0.0
        for arm in arms:
            n, cost = uncached(conn, arm, [rid for rid, _, _ in items])
            total += cost
            print(f"  {arm.name:<40} {n:>5} uncached calls  ${cost:.2f}")
        print(f"dry run: {len(items)} recordings, {len(arms)} arms, estimated ${total:.2f}")
        return
    for arm in arms:
        rows = run_arm(args.db, arm, items, workers=args.workers)
        write_rows(args.out / f"{arm.name}.jsonl", rows)
        incomplete = sum(r["incomplete"] for r in rows)
        print(f"  {arm.name:<40} {len(rows)} recordings, {incomplete} incomplete", flush=True)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", type=Path, default=ROOT / "data/atc.sqlite")
    ap.add_argument("--out", type=Path, default=OUT)
    sub = ap.add_subparsers(dest="command", required=True)
    run = sub.add_parser("run", help="replay the evaluation sets under each arm")
    run.add_argument("--parser", choices=["rule", "llm"])
    run.add_argument("--model")
    run.add_argument("--context", choices=["none", "role", "window"])
    run.add_argument("--transcript", choices=["gold", "asr"])
    run.add_argument("--set", choices=["negatives", "positives"])
    run.add_argument("--workers", type=int, default=4)
    run.add_argument("--dry-run", action="store_true")
    run.set_defaults(func=cmd_run)
    args = ap.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_evaluate.py -q` then `.venv/bin/python -m pytest -q`
Expected: PASS; the whole suite is 263 passed with `ANTHROPIC_API_KEY` set (262 passed and 1 skipped without it).

- [ ] **Step 5: Check the runner on a copy of the corpus (skip if `data/atc.sqlite` is absent)**

Run: `cp data/atc.sqlite /tmp/eval-check.sqlite && .venv/bin/python scripts/eval_conflicts.py --db /tmp/eval-check.sqlite --out /tmp/eval-check run --dry-run --transcript gold`
Expected: nine arms; the rules arms cost `$0.00`, the Claude arms show a few dollars each; no call is made. Then
`.venv/bin/python scripts/eval_conflicts.py --db /tmp/eval-check.sqlite --out /tmp/eval-check run --parser rule`
(free, about ten seconds) prints `309 recordings, 0 incomplete` for each of the six rules arms (there are no positives
in the real corpus yet). Delete `/tmp/eval-check*`.

- [ ] **Step 6: Commit**

```bash
git add atcdb/evaluate.py scripts/eval_conflicts.py tests/test_evaluate.py
git commit -m "feat: Level 2 arm runner and scoring"
```
End the message with the attribution lines the session provides.

---

### Task 4: Alert adjudication and agreement

Every alert on a real recording is a candidate false alarm until a person classifies it. Alerts from all arms
(and later the judge) are pooled on `(recording, type, runway, trigger transmission)` so each is judged once;
callsigns are left out of the key because the rules parser often extracts none. The second adjudicator's sheet holds a
fixed pseudo-random 30% of keys, decided per key from a hash so the overlap does not shift as more arms run. Verdicts
already given are kept whenever the sheets are regenerated.

**Files:**
- Modify: `atcdb/evaluate.py` (append the adjudication section)
- Modify: `scripts/eval_conflicts.py` (the `adjudicate` subcommand)
- Test: `tests/test_evaluate.py`

**Interfaces:**
- Produces: `evaluate.VERDICTS` (`genuine`, `parse_error`, `missing_info`, `engine_rule`), `ADJUDICATION_COLUMNS`,
  `adjudication_rows(conn, rows_by_arm, existing=()) -> list[dict]`, `in_overlap(key, fraction=0.3, seed=0) -> bool`,
  `overlap_rows(sheet_a, existing_b=(), ...)`, `read_verdicts(sheet) -> {key: verdict}` (raises `ValueError`),
  `adjudication_kappa(sheet_a, sheet_b) -> (kappa, n)`.

- [ ] **Step 1: Write the failing tests**

In `tests/test_evaluate.py`, replace:

```python
from atcdb.evaluate import (ARMS, PRIMARY, Arm, Pending, alert_key, alert_keys, bootstrap, cohen_kappa, detection,
                            evaluation_sets, false_alarm_units, paired_bootstrap, per_hour, rate, read_rows, recall,
                            recording_row, run_arm, uncached, usable, write_rows)
```

with:

```python
from atcdb.evaluate import (ARMS, PRIMARY, Arm, Pending, adjudication_kappa, adjudication_rows, alert_key, alert_keys,
                            bootstrap, cohen_kappa, detection, evaluation_sets, false_alarm_units, in_overlap, overlap_rows,
                            paired_bootstrap, per_hour, rate, read_rows, read_verdicts, recall, recording_row, run_arm,
                            uncached, usable, write_rows)
```

Append to `tests/test_evaluate.py`:

```python


def test_the_adjudication_sheet_pools_alerts_across_arms_and_keeps_verdicts(tmp_path):
    db = tmp_path / "t.sqlite"
    conn = init_db(db)
    rid = _seed(conn, CONFLICT)
    quiet = _seed(conn, QUIET, external_id="quiet")
    rules = run_arm(db, PRIMARY[0], [(rid, "negatives", None), (quiet, "negatives", None)])
    other = [{**r, "conflicts": [{**c, "callsigns": ["", c["callsigns"][1]]} for c in r["conflicts"]]} for r in rules]
    positive = [{**rules[0], "set": "positives"}]
    sheet = adjudication_rows(conn, {"rule-a": rules, "rule-b": other, "rule-c": positive})
    [row] = sheet
    tx = rules[0]["tx_ids"][2]
    assert row["key"] == f"{rid}:RUNWAY:31:{tx}" and row["arms"] == "rule-a; rule-b"
    assert row["callsigns"] == "lufthansa four five six / csa one two three; ? / csa one two three"
    assert row["context"].splitlines()[-1] == f">> [controller] {CONFLICT[2][1]}"
    assert len(row["context"].splitlines()) == 3 and row["verdict"] == ""
    row["verdict"], row["notes"] = "parse_error", "x"
    stale = {**row, "key": "999:RUNWAY:31:1", "recording_id": "999", "tx_id": "1", "verdict": "genuine"}
    again = adjudication_rows(conn, {"rule-a": rules}, existing=[row, stale])
    assert [(r["key"], r["verdict"]) for r in again] == [(row["key"], "parse_error"), (stale["key"], "genuine")]
    assert read_verdicts(again) == {row["key"]: "parse_error", stale["key"]: "genuine"}


def test_read_verdicts_rejects_unknown_labels():
    assert read_verdicts([{"key": "k", "verdict": " Genuine "}, {"key": "j", "verdict": ""}]) == {"k": "genuine"}
    with pytest.raises(ValueError, match="verdict must be one of"):
        read_verdicts([{"key": "k", "verdict": "false"}])


def test_the_overlap_sheet_is_a_stable_share_that_hides_the_first_verdicts():
    keys = [f"{i}:RUNWAY:31:{i}" for i in range(1000)]
    share = sum(in_overlap(k) for k in keys) / len(keys)
    assert 0.25 < share < 0.35 and in_overlap(keys[0]) == in_overlap(keys[0])
    sheet_a = [{"key": k, "verdict": "genuine", "notes": "a"} for k in keys[:20]]
    b = overlap_rows(sheet_a)
    assert [r["key"] for r in b] == [k for k in keys[:20] if in_overlap(k)] and all(r["verdict"] == "" for r in b)
    b[0]["verdict"] = "engine_rule"
    assert overlap_rows(sheet_a + [{"key": "new", "verdict": ""}], existing_b=b)[0]["verdict"] == "engine_rule"


def test_adjudication_kappa_uses_the_alerts_both_adjudicated():
    a = [{"key": "1", "verdict": "genuine"}, {"key": "2", "verdict": "parse_error"}, {"key": "3", "verdict": "parse_error"}]
    b = [{"key": "1", "verdict": "genuine"}, {"key": "2", "verdict": "parse_error"}, {"key": "3", "verdict": ""}]
    assert adjudication_kappa(a, b) == (1.0, 2)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_evaluate.py -q`
Expected: FAIL at collection with `ImportError: cannot import name 'adjudication_kappa'`.

- [ ] **Step 3: Write the implementation**

In `atcdb/evaluate.py`, replace:

```python
import json
import random

```

with:

```python
import hashlib
import json
import random

```

Append to `atcdb/evaluate.py`:

```python


# --- adjudication (spec section 6) -----------------------------------------------------------------------------------

VERDICTS = ("genuine", "parse_error", "missing_info", "engine_rule")
ADJUDICATION_COLUMNS = ["key", "recording_id", "type", "runway", "tx_id", "arms", "callsigns", "context", "verdict", "notes"]
CONTEXT_LINES = 6   # transmissions shown up to and including the trigger


def adjudication_rows(conn: sqlite3.Connection, rows_by_arm: dict[str, list[dict]],
                      existing: Iterable[dict] = ()) -> list[dict]:
    """The adjudication sheet: every alert raised on a usable negative by any arm, pooled on `alert_key`, with the arms
    that raised it, the callsigns each extracted and the human transcript up to the trigger. Verdicts and notes already
    in `existing` are kept, and existing rows no longer raised by any arm stay on the sheet. Sorted by recording, then
    transmission."""
    pooled: dict[str, dict] = {}
    for arm_name, rows in sorted(rows_by_arm.items()):
        for row in rows:
            if row["set"] != "negatives" or not usable(row):
                continue
            for c in row["conflicts"]:
                if c["severity"] != "alert":
                    continue
                key = alert_key(row["recording_id"], c)
                entry = pooled.setdefault(key, {"key": key, "recording_id": row["recording_id"], "type": c["type"],
                                                "runway": c["runway"] or "", "tx_id": c["tx_id"], "arms": [], "callsigns": []})
                if arm_name not in entry["arms"]:
                    entry["arms"].append(arm_name)
                names = " / ".join(cs or "?" for cs in c["callsigns"])
                if names not in entry["callsigns"]:
                    entry["callsigns"].append(names)
    old = {r["key"]: r for r in existing}
    out = []
    for key, entry in pooled.items():
        txs = load_recording(conn, entry["recording_id"], "gold", default_transcript_model(conn, "gold", entry["recording_id"]))
        k = next(i for i, tx in enumerate(txs) if tx.id == entry["tx_id"])
        context = "\n".join(f"{'>>' if i == k else '  '} [{tx.role}] {tx.text}"
                            for i, tx in enumerate(txs) if k - CONTEXT_LINES < i <= k)
        out.append({**entry, "arms": "; ".join(entry["arms"]), "callsigns": "; ".join(entry["callsigns"]),
                    "context": context, "verdict": old.get(key, {}).get("verdict", ""),
                    "notes": old.get(key, {}).get("notes", "")})
    out += [r for key, r in old.items() if key not in pooled]
    return sorted(out, key=lambda r: (int(r["recording_id"]), int(r["tx_id"]), r["key"]))


def in_overlap(key: str, fraction: float = 0.3, seed: int = 0) -> bool:
    """Whether an alert belongs on the second adjudicator's sheet: a fixed pseudo-random share of keys, decided per key,
    so the overlap stays the same as more arms add alerts."""
    digest = hashlib.sha1(f"{seed}:{key}".encode()).digest()
    return int.from_bytes(digest[:8], "big") / 2 ** 64 < fraction


def overlap_rows(sheet_a: list[dict], existing_b: Iterable[dict] = (), fraction: float = 0.3, seed: int = 0) -> list[dict]:
    """Sheet B: the overlap share of sheet A's rows with A's verdicts removed, keeping B's own verdicts already given."""
    old = {r["key"]: r for r in existing_b}
    return [{**r, "verdict": old.get(r["key"], {}).get("verdict", ""), "notes": old.get(r["key"], {}).get("notes", "")}
            for r in sheet_a if in_overlap(r["key"], fraction, seed)]


def read_verdicts(sheet: Iterable[dict]) -> dict[str, str]:
    """key -> verdict for every row with a verdict. Raises ValueError on a verdict outside VERDICTS."""
    out = {}
    for r in sheet:
        v = (r.get("verdict") or "").strip().lower()
        if not v:
            continue
        if v not in VERDICTS:
            raise ValueError(f"{r['key']}: verdict must be one of {', '.join(VERDICTS)}, not {r['verdict']!r}")
        out[r["key"]] = v
    return out


def adjudication_kappa(sheet_a: Iterable[dict], sheet_b: Iterable[dict]) -> tuple[float, int]:
    """(Cohen's kappa, items) over the alerts both adjudicators gave a verdict."""
    a, b = read_verdicts(sheet_a), read_verdicts(sheet_b)
    both = sorted(set(a) & set(b))
    return cohen_kappa([a[k] for k in both], [b[k] for k in both]), len(both)
```

In `scripts/eval_conflicts.py`, replace:

```python
                                         [--set negatives|positives] [--workers N] [--dry-run]

```

with:

```python
                                         [--set negatives|positives] [--workers N] [--dry-run]
    python scripts/eval_conflicts.py adjudicate [--kappa]

```

In `scripts/eval_conflicts.py`, replace:

```python
prints the uncached calls and a rough cost per arm and spends nothing.

```

with:

```python
prints the uncached calls and a rough cost per arm and spends nothing.

`adjudicate` pools every alert the arms raised on the negatives into data/labels/adjudication_A.csv (verdicts already
given are kept) and writes the second adjudicator's overlap, adjudication_B.csv. Fill `verdict` with genuine,
parse_error (the extraction was wrong), missing_info (extraction right, the release was never spoken) or engine_rule
(extraction right, the matrix is too strict). Re-run it after new arms have run. `--kappa` reports agreement instead.

```

In `scripts/eval_conflicts.py`, replace:

```python
import argparse
import sys

```

with:

```python
import argparse
import csv
import sys

```

In `scripts/eval_conflicts.py`, replace:

```python
from atcdb.evaluate import ARMS, evaluation_sets, run_arm, uncached, write_rows  # noqa: E402
from atcdb.schema import init_db  # noqa: E402
```

with:

```python
from atcdb.evaluate import (ADJUDICATION_COLUMNS, ARMS, adjudication_kappa, adjudication_rows, evaluation_sets,  # noqa: E402
                            overlap_rows, read_rows, run_arm, uncached, write_rows)
from atcdb.schema import init_db  # noqa: E402
```

In `scripts/eval_conflicts.py`, replace:

```python
OUT = ROOT / "data/eval/conflicts"

```

with:

```python
OUT = ROOT / "data/eval/conflicts"
SHEET_A = ROOT / "data/labels/adjudication_A.csv"
SHEET_B = ROOT / "data/labels/adjudication_B.csv"


def read_sheet(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with path.open(newline="") as fh:
        return list(csv.DictReader(fh))


def write_sheet(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=ADJUDICATION_COLUMNS)
        w.writeheader()
        w.writerows(rows)


def arm_rows(out: Path) -> dict[str, list[dict]]:
    """Every arm's rows that `run` (or the judge) has written, by arm name."""
    return {p.stem: read_rows(p) for p in sorted(out.glob("*.jsonl"))}

```

In `scripts/eval_conflicts.py`, replace:

```python
def main() -> None:
```

with:

```python
def cmd_adjudicate(args: argparse.Namespace) -> None:
    sheet_a, sheet_b = read_sheet(args.sheet_a), read_sheet(args.sheet_b)
    if args.kappa:
        kappa, n = adjudication_kappa(sheet_a, sheet_b)
        print(f"Cohen's kappa {kappa:.2f} over {n} alerts both adjudicators labelled")
        return
    sheet_a = adjudication_rows(init_db(args.db), arm_rows(args.out), existing=sheet_a)
    sheet_b = overlap_rows(sheet_a, existing_b=sheet_b)
    write_sheet(args.sheet_a, sheet_a)
    write_sheet(args.sheet_b, sheet_b)
    todo = sum(not r["verdict"] for r in sheet_a)
    print(f"wrote {args.sheet_a} ({len(sheet_a)} alerts, {todo} without a verdict) and {args.sheet_b} ({len(sheet_b)} alerts)")


def main() -> None:
```

In `scripts/eval_conflicts.py`, replace:

```python
    run.set_defaults(func=cmd_run)

```

with:

```python
    run.set_defaults(func=cmd_run)
    adj = sub.add_parser("adjudicate", help="write or update the alert adjudication sheets")
    adj.add_argument("--sheet-a", type=Path, default=SHEET_A)
    adj.add_argument("--sheet-b", type=Path, default=SHEET_B)
    adj.add_argument("--kappa", action="store_true", help="report agreement between the two sheets")
    adj.set_defaults(func=cmd_adjudicate)

```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_evaluate.py -q` then `.venv/bin/python -m pytest -q`
Expected: PASS; the whole suite is 267 passed with `ANTHROPIC_API_KEY` set (266 passed and 1 skipped without it).

- [ ] **Step 5: Commit**

```bash
git add atcdb/evaluate.py scripts/eval_conflicts.py tests/test_evaluate.py
git commit -m "feat: pooled alert adjudication sheets and kappa"
```
End the message with the attribution lines the session provides.

---

### Task 5: The LLM judge

The ablation arm (spec section 7): the whole transcript of a recording goes to Sonnet 5 in one call, and a
strict, forced `report_conflicts` tool lists the conflicting clearances. The request settings are the parser's Sonnet
settings (thinking disabled, effort `low`, imported from `parse_llm.MODEL_SETTINGS`), so the comparison is about
structure, not reasoning budget. Judgments are cached in a new `judgments` table with the same contract as parses: an
API error or an unusable reply stores nothing. In `evaluate.py` the judge becomes two more arms (`parser="judge"`,
`context="sequence"`), whose rows have the same shape as the others, every reported conflict being an alert.

**Load the `claude-api` skill before writing `atcdb/judge.py`.** Sonnet 5 accepts `thinking: {"type": "disabled"}`
and a forced `tool_choice`; it rejects `temperature`. The recorded fixture below is two real Sonnet replies to
invented sequences (never corpus text), recorded with `scripts/record_judge_fixtures.py`, which this task also adds.

**Files:**
- Modify: `atcdb/schema.py` (the `judgments` table)
- Create: `atcdb/judge.py`
- Modify: `atcdb/evaluate.py` (judge arms)
- Modify: `scripts/eval_conflicts.py` (judge arms in `run`)
- Create: `scripts/record_judge_fixtures.py`
- Create: `tests/fixtures/judge_responses.json`
- Test: `tests/test_judge.py` (create), `tests/test_schema.py` (modify)

**Interfaces:**
- Consumes: `parse_llm.MODEL_SETTINGS`, `parse_llm.PRICES_PER_MTOK`, `parse_llm._default_client` (the cached default
  Anthropic client; tests monkeypatch `judge._default_client`).
- Produces: `judge.VERSION = "j1"`, `judge.MODELS = ("claude-sonnet-5",)`, `SYSTEM`, `TOOL`, `JudgeError`,
  `render_sequence(txs)`, `request(model, txs)`, `conflicts_from_response(response, n) -> (conflicts, dropped)` with
  each conflict `{"type", "runway", "step", "callsigns"}` (`step` 0-based), `judge(conn, recording_id, txs,
  transcript_kind, transcript_model, model=..., client=None) -> (conflicts, dropped)`, `estimate_cost`, `is_cached`.
- Produces: `evaluate.JUDGE_ARMS` (one per transcript kind); `recording_row` and `uncached` handle them.

- [ ] **Step 1: Write the failing tests**

In `tests/test_schema.py`, replace:

```python
            "readback_pairs", "events"} == set(TABLES)
```

with:

```python
            "readback_pairs", "events", "judgments"} == set(TABLES)
```

Append to `tests/test_schema.py`:

```python


def test_judgments_are_unique_per_recording_transcript_and_judge(tmp_path):
    conn = init_db(tmp_path / "t.sqlite")
    _seed_transcript(conn)
    row = (1, "gold", "human", "claude-sonnet-5", "j1", "[]")
    sql = ("INSERT INTO judgments (recording_id, transcript_kind, transcript_model, judge_model, judge_version, "
           "conflicts_json) VALUES (?,?,?,?,?,?)")
    conn.execute(sql, row)
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(sql, row)
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(sql, (1, "llm", "human", "claude-sonnet-5", "j1", "[]"))
```

Create `tests/fixtures/judge_responses.json`:

```json
[
 {
  "case": "crossing_against_a_landing",
  "model": "claude-sonnet-5",
  "version": "j1",
  "turns": [
   [
    "controller",
    "csa one two three runway three one cleared to land wind calm"
   ],
   [
    "pilot",
    "cleared to land runway three one csa one two three"
   ],
   [
    "controller",
    "lufthansa four five six cross runway three one"
   ],
   [
    "pilot",
    "crossing runway three one lufthansa four five six"
   ]
  ],
  "stop_reason": "tool_use",
  "content": [
   {
    "id": "toolu_01EVQBM352BLPECS59mNnZKf",
    "caller": {
     "type": "direct"
    },
    "input": {
     "conflicts": [
      {
       "type": "RUNWAY",
       "runway": "31",
       "callsigns": [
        "lufthansa four five six"
       ],
       "trigger_index": 3
      }
     ]
    },
    "name": "report_conflicts",
    "type": "tool_use"
   }
  ]
 },
 {
  "case": "released_before_the_takeoff",
  "model": "claude-sonnet-5",
  "version": "j1",
  "turns": [
   [
    "controller",
    "csa one two three runway three one cleared to land wind calm"
   ],
   [
    "pilot",
    "cleared to land runway three one csa one two three"
   ],
   [
    "pilot",
    "runway vacated csa one two three"
   ],
   [
    "controller",
    "csa one two three contact ground one two one decimal nine"
   ],
   [
    "controller",
    "lufthansa four five six runway three one cleared for takeoff"
   ],
   [
    "pilot",
    "cleared for takeoff runway three one lufthansa four five six"
   ]
  ],
  "stop_reason": "tool_use",
  "content": [
   {
    "id": "toolu_01HjCbSYAvxGMsj1NT2dwjvS",
    "caller": {
     "type": "direct"
    },
    "input": {
     "conflicts": []
    },
    "name": "report_conflicts",
    "type": "tool_use"
   }
  ]
 }
]
```

Create `tests/test_judge.py`:

```python
import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from atcdb import judge
from atcdb.evaluate import JUDGE_ARMS, detection, recording_row, uncached
from atcdb.judge import (MODELS, SYSTEM, TOOL, JudgeError, conflicts_from_response, estimate_cost, is_cached, render_sequence,
                         request)
from atcdb.parse_llm import MODEL_SETTINGS
from atcdb.parsing import Transmission
from atcdb.schema import init_db

ROOT = Path(__file__).resolve().parents[1]
TURNS = [("controller", "csa one two three runway three one cleared to land wind calm"),
         ("pilot", "cleared to land runway three one csa one two three"),
         ("controller", "lufthansa four five six cross runway three one")]
TXS = [Transmission(id=i + 1, transcript_id=i + 1, text=t, role=r, start_s=10.0 * i) for i, (r, t) in enumerate(TURNS)]


class FakeMessages:
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


def reply(conflicts, stop_reason="tool_use"):
    return SimpleNamespace(stop_reason=stop_reason,
                           content=[SimpleNamespace(type="tool_use", name="report_conflicts", input={"conflicts": conflicts})])


def item(runway="31", index=3, type_="RUNWAY", callsigns=("lufthansa four five six",)):
    return {"type": type_, "runway": runway, "callsigns": list(callsigns), "trigger_index": index}


def _seed(conn, turns=TURNS, external_id="r1"):
    conn.execute("INSERT OR IGNORE INTO sources (id, name, kind) VALUES (1, 'test', 'corpus')")
    rid = conn.execute("INSERT INTO recordings (source_id, external_id, facility) VALUES (1, ?, 'Tower')", (external_id,)).lastrowid
    for i, (role, text) in enumerate(turns):
        xid = conn.execute("INSERT INTO transmissions (recording_id, external_id, start_s, end_s, speaker_role) VALUES (?, ?, ?, ?, ?)",
                           (rid, f"x{i}", 10.0 * i, 10.0 * i + 3, role)).lastrowid
        conn.execute("INSERT INTO transcripts (transmission_id, kind, model, raw_text, normalized_text) VALUES (?, 'gold', 'human', ?, ?)",
                     (xid, text, text))
    conn.commit()
    return rid


def test_the_tool_is_strict_and_the_request_matches_the_sonnet_parser_arm():
    assert TOOL["name"] == "report_conflicts" and TOOL["strict"] is True
    item_schema = TOOL["input_schema"]["properties"]["conflicts"]["items"]
    assert item_schema["required"] == ["type", "runway", "callsigns", "trigger_index"]
    assert item_schema["additionalProperties"] is False and item_schema["properties"]["type"]["enum"] == ["RUNWAY", "READBACK"]
    r = request("claude-sonnet-5", TXS)
    assert r["system"] == SYSTEM and r["tools"] == [TOOL] and r["tool_choice"] == {"type": "tool", "name": "report_conflicts"}
    assert (r["thinking"], r["output_config"]) == (MODEL_SETTINGS["claude-sonnet-5"]["thinking"], {"effort": "low"})
    assert MODELS == ("claude-sonnet-5",)


def test_render_sequence_numbers_every_transmission_from_one():
    assert render_sequence(TXS) == (
        "Transmissions, in order:\n"
        f"[1] (controller) {TURNS[0][1]}\n[2] (pilot) {TURNS[1][1]}\n[3] (controller) {TURNS[2][1]}")


def test_conflicts_map_to_zero_based_steps_and_bad_ones_are_dropped():
    found, dropped = conflicts_from_response(reply([
        item(), item(runway="4 Left", index=1, type_="READBACK", callsigns=["CSA  One"]),
        item(runway="99"), item(index=0), item(index=4)]), n=3)
    assert found == [{"type": "RUNWAY", "runway": "31", "step": 2, "callsigns": ["lufthansa four five six"]},
                     {"type": "READBACK", "runway": "04L", "step": 0, "callsigns": ["csa one"]}]
    assert dropped == 3


@pytest.mark.parametrize("response, message", [
    (reply([], stop_reason="refusal"), "refused"),
    (reply([], stop_reason="max_tokens"), "truncated"),
    (SimpleNamespace(stop_reason="end_turn", content=[SimpleNamespace(type="text", text="none")]), "no report_conflicts"),
])
def test_unusable_replies_raise(response, message):
    with pytest.raises(JudgeError, match=message):
        conflicts_from_response(response, 3)


def test_judgments_are_cached_and_failures_are_not(tmp_path):
    conn = init_db(tmp_path / "t.sqlite")
    rid = _seed(conn)
    client = FakeClient(RuntimeError("overloaded"), reply([item()]))
    with pytest.raises(RuntimeError):
        judge.judge(conn, rid, TXS, "gold", "human", client=client)
    assert not is_cached(conn, rid, "gold", "human")
    first = judge.judge(conn, rid, TXS, "gold", "human", client=client)
    assert first == ([{"type": "RUNWAY", "runway": "31", "step": 2, "callsigns": ["lufthansa four five six"]}], 0)
    assert judge.judge(conn, rid, TXS, "gold", "human", client=FakeClient()) == first   # no second call
    assert len(client.messages.calls) == 2 and is_cached(conn, rid, "gold", "human")
    assert judge.judge(conn, rid, [], "gold", "human", client=FakeClient()) == ([], 0)
    with pytest.raises(ValueError):
        judge.judge(conn, rid, TXS, "gold", "human", model="claude-haiku-4-5")


def test_the_judge_arm_row_places_conflicts_at_their_trigger(tmp_path, monkeypatch):
    conn = init_db(tmp_path / "t.sqlite")
    rid = _seed(conn)
    arm = JUDGE_ARMS[0]
    assert (arm.parser, arm.model, arm.context, arm.transcript) == ("judge", "claude-sonnet-5", "sequence", "gold")
    assert uncached(conn, arm, [rid])[0] == 1
    monkeypatch.setattr(judge, "_default_client", lambda: FakeClient(reply([item()])))
    row = recording_row(conn, arm, rid, "positives", {"runway": "31", "trigger_tx": 3, "edit_kind": "splice"})
    assert row["incomplete"] is False and row["tx_ids"] == [1, 2, 3] and row["events"] == [[], [], []]
    assert row["conflicts"] == [{"type": "RUNWAY", "severity": "alert", "runway": "31",
                                 "callsigns": ["lufthansa four five six"], "tx_id": 3, "step": 2}]
    assert detection(row) == "strict" and uncached(conn, arm, [rid]) == (0, 0.0)
    monkeypatch.setattr(judge, "_default_client", lambda: FakeClient(RuntimeError("down")))
    failed = recording_row(conn, arm, _seed(conn, external_id="r2"), "negatives", None)
    assert failed["incomplete"] is True and failed["conflicts"] == []


def test_estimate_cost_scales_with_the_sequences():
    one = estimate_cost("claude-sonnet-5", ["x" * 2000])
    assert 0 < one < 0.02 and estimate_cost("claude-sonnet-5", ["x" * 2000] * 3) == pytest.approx(3 * one)


# --- recorded replies (scripts/record_judge_fixtures.py) -----------------------------------------

FIXTURE = ROOT / "tests" / "fixtures" / "judge_responses.json"
RECORDED = {
    ("crossing_against_a_landing", "claude-sonnet-5"): [("RUNWAY", "31", 2)],
    ("released_before_the_takeoff", "claude-sonnet-5"): [],
}


def test_recorded_replies_map_to_the_pinned_conflicts():
    seen = set()
    for r in json.loads(FIXTURE.read_text()):
        response = SimpleNamespace(stop_reason=r["stop_reason"], content=[SimpleNamespace(**b) for b in r["content"]])
        found, dropped = conflicts_from_response(response, len(r["turns"]))
        assert [(c["type"], c["runway"], c["step"]) for c in found] == RECORDED[(r["case"], r["model"])] and dropped == 0
        seen.add((r["case"], r["model"]))
    assert seen == set(RECORDED)
    assert {r["version"] for r in json.loads(FIXTURE.read_text())} == {judge.VERSION}


@pytest.mark.skipif(not os.environ.get("ANTHROPIC_API_KEY"), reason="ANTHROPIC_API_KEY not set: live smoke test skipped")
def test_live_smoke_the_judge_finds_a_crossing_against_a_landing(tmp_path):
    conn = init_db(tmp_path / "t.sqlite")
    found, _ = judge.judge(conn, _seed(conn), TXS, "gold", "human")
    assert [(c["type"], c["runway"], c["step"]) for c in found] == [("RUNWAY", "31", 2)]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_judge.py tests/test_schema.py -q`
Expected: FAIL at collection with `ImportError: cannot import name 'judge' from 'atcdb'`.

- [ ] **Step 3: Write the implementation**

In `atcdb/schema.py`, replace:

```python
TABLES = ["sources", "recordings", "transmissions", "transcripts", "annotations", "phraseology_rules", "readback_pairs", "events"]
```

with:

```python
TABLES = ["sources", "recordings", "transmissions", "transcripts", "annotations", "phraseology_rules", "readback_pairs", "events",
          "judgments"]
```

In `atcdb/schema.py`, replace:

```python
CREATE INDEX IF NOT EXISTS ix_events_transcript ON events (transcript_id, parser, model);
"""
```

with:

```python
CREATE INDEX IF NOT EXISTS ix_events_transcript ON events (transcript_id, parser, model);

-- LLM-judge verdicts per recording (see atcdb/judge.py): the conflicts Claude reported over the whole transcript,
-- one row per (recording, transcript kind and model, judge model, judge version). Failed calls are not stored.
CREATE TABLE IF NOT EXISTS judgments (
    id                INTEGER PRIMARY KEY,
    recording_id      INTEGER NOT NULL REFERENCES recordings(id),
    transcript_kind   TEXT NOT NULL CHECK (transcript_kind IN ('gold', 'asr')),
    transcript_model  TEXT NOT NULL,
    judge_model       TEXT NOT NULL,
    judge_version     TEXT NOT NULL,
    conflicts_json    TEXT NOT NULL,
    dropped           INTEGER NOT NULL DEFAULT 0,
    created_at_utc    TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    UNIQUE (recording_id, transcript_kind, transcript_model, judge_model, judge_version)
);
"""
```

Create `atcdb/judge.py`:

```python
"""LLM judge, the evaluation's ablation arm (spec 2026-09-29-evaluation-3b1-design.md, section 7).

The whole transcript of one recording goes to Claude in one call, and a forced, strict `report_conflicts` tool lists the
incompatible clearances it sees. No parser, no engine: this is the "raw LLM over the transcript" baseline that the
structured system is compared with. The model and request settings match the parser's Sonnet arm (`parse_llm`), so the
comparison is about structure, not reasoning budget. Judgments are cached in the `judgments` table, one per (recording,
transcript kind and model, judge model, VERSION); API errors and unusable replies raise and cache nothing.

Bump VERSION by hand whenever SYSTEM, TOOL, `render_sequence`, `conflicts_from_response` or the request settings change.
"""
import json
import sqlite3
from typing import Any

from atcdb.engine import normalize_runway
from atcdb.parse_llm import MODEL_SETTINGS, PRICES_PER_MTOK, _default_client
from atcdb.parsing import Transmission

VERSION = "j1"
MODELS = ("claude-sonnet-5",)
MAX_TOKENS = 2048   # a recording holds at most a few conflicts; a truncated reply raises JudgeError
_TOOL_USE_OVERHEAD_TOKENS = 350
_OUTPUT_TOKENS = 120

SYSTEM = """You monitor an airport tower frequency. You are given one recorded sequence of radio transmissions, \
numbered in order, each with the speaker's role. Report every conflicting clearance with the report_conflicts tool, \
or an empty list when there is none.

RUNWAY conflict: an aircraft is cleared onto a runway that another aircraft is still cleared to use. For example a \
takeoff, line-up or crossing clearance while an earlier landing clearance on the same runway is still in force, or a \
landing clearance while another aircraft is cleared to take off, line up or cross there. An aircraft stops using a \
runway when it reports vacating it, is handed to ground (after landing or crossing) or to departure or radar (after \
takeoff), is told to go around, or is told to hold short of it. Two successive landing clearances on one runway are \
normal and are not a conflict.

READBACK conflict: a pilot reads back a runway instruction without the runway, or with a different runway.

For each conflict give the runway in digits with an optional L, R or C (for example 31 or 04L), the callsigns involved \
as spoken (the aircraft whose clearance creates the conflict first), and trigger_index, the number of the transmission \
at which the conflict arises. Report only what the transcript shows."""

TOOL: dict[str, Any] = {
    "name": "report_conflicts",
    "description": "Report every conflicting clearance in the sequence. An empty list means none.",
    "strict": True,
    "input_schema": {
        "type": "object",
        "properties": {"conflicts": {"type": "array", "items": {
            "type": "object",
            "properties": {
                "type": {"type": "string", "enum": ["RUNWAY", "READBACK"]},
                "runway": {"type": "string", "description": "digits plus optional L/R/C, e.g. 31 or 04L"},
                "callsigns": {"type": "array", "items": {"type": "string"},
                              "description": "lower-case words as spoken; the aircraft creating the conflict first"},
                "trigger_index": {"type": "integer", "description": "number of the transmission where it arises"},
            },
            "required": ["type", "runway", "callsigns", "trigger_index"],
            "additionalProperties": False,
        }}},
        "required": ["conflicts"],
        "additionalProperties": False,
    },
}


class JudgeError(RuntimeError):
    """The model answered, but not with a usable report_conflicts call: a refusal, a truncated reply, or no call."""


def render_sequence(txs: list[Transmission]) -> str:
    """The user message: every transmission, numbered from 1, with its speaker role."""
    return "\n".join(["Transmissions, in order:"] + [f"[{i}] ({tx.role}) {tx.text}" for i, tx in enumerate(txs, 1)])


def request(model: str, txs: list[Transmission]) -> dict[str, Any]:
    """Keyword arguments for `client.messages.create` for one recording."""
    return {"model": model, "max_tokens": MAX_TOKENS, "system": SYSTEM, "tools": [TOOL],
            "tool_choice": {"type": "tool", "name": TOOL["name"]},
            "messages": [{"role": "user", "content": render_sequence(txs)}], **MODEL_SETTINGS[model]}


def conflicts_from_response(response: Any, n: int) -> tuple[list[dict], int]:
    """(conflicts, dropped) from a reply about a sequence of `n` transmissions. Each conflict is {type, runway,
    callsigns, step}, `step` being the 0-based transmission index. A reported conflict whose trigger_index is outside
    1..n or whose runway does not normalise is dropped and counted. Raises JudgeError on an unusable reply."""
    if response.stop_reason == "refusal":
        raise JudgeError("the model refused this sequence")
    if response.stop_reason == "max_tokens":
        raise JudgeError(f"reply truncated at max_tokens={MAX_TOKENS}")
    call = next((b for b in response.content if b.type == "tool_use" and b.name == TOOL["name"]), None)
    if call is None:
        raise JudgeError("no report_conflicts call in the reply")
    out, dropped = [], 0
    for it in call.input["conflicts"]:
        runway = normalize_runway(it.get("runway") or "")
        index = it.get("trigger_index")
        if runway is None or not isinstance(index, int) or not 1 <= index <= n:
            dropped += 1
            continue
        out.append({"type": it["type"], "runway": runway, "step": index - 1,
                    "callsigns": [" ".join(c.lower().split()) for c in it.get("callsigns") or []]})
    return out, dropped


def _cached(conn: sqlite3.Connection, key: tuple) -> tuple[list[dict], int] | None:
    row = conn.execute(
        """SELECT conflicts_json, dropped FROM judgments WHERE recording_id = ? AND transcript_kind = ?
           AND transcript_model = ? AND judge_model = ? AND judge_version = ?""", key).fetchone()
    return (json.loads(row["conflicts_json"]), row["dropped"]) if row else None


def judge(conn: sqlite3.Connection, recording_id: int, txs: list[Transmission], transcript_kind: str,
          transcript_model: str, model: str = MODELS[0], client: Any = None) -> tuple[list[dict], int]:
    """(conflicts, dropped) for one recording's transmissions `txs`: from the `judgments` cache, or asked and stored.
    An empty sequence is judged empty without a call. Errors propagate and nothing is stored; if another request stored
    the same judgment first, that one is returned."""
    if model not in MODELS:
        raise ValueError(f"unknown judge model {model!r}; expected one of {MODELS}")
    if not txs:
        return [], 0
    key = (recording_id, transcript_kind, transcript_model, model, VERSION)
    cached = _cached(conn, key)
    if cached is not None:
        return cached
    response = (client or _default_client()).messages.create(**request(model, txs))
    conflicts, dropped = conflicts_from_response(response, len(txs))
    conn.execute("""INSERT OR IGNORE INTO judgments (recording_id, transcript_kind, transcript_model, judge_model,
                    judge_version, conflicts_json, dropped) VALUES (?, ?, ?, ?, ?, ?, ?)""",
                 (*key, json.dumps(conflicts), dropped))
    conn.commit()
    return _cached(conn, key)


def estimate_cost(model: str, prompts: list[str]) -> float:
    """Rough USD for one call per sequence prompt (four characters a token); for dry runs only."""
    fixed = (len(SYSTEM) + len(json.dumps(TOOL))) / 4 + _TOOL_USE_OVERHEAD_TOKENS
    tokens_in = sum(fixed + len(p) / 4 for p in prompts)
    price_in, price_out = PRICES_PER_MTOK[model]
    return (tokens_in * price_in + len(prompts) * _OUTPUT_TOKENS * price_out) / 1e6


def is_cached(conn: sqlite3.Connection, recording_id: int, transcript_kind: str, transcript_model: str,
              model: str = MODELS[0]) -> bool:
    return _cached(conn, (recording_id, transcript_kind, transcript_model, model, VERSION)) is not None
```

In `atcdb/evaluate.py`, replace:

```python
from atcdb import parse_llm

```

with:

```python
from atcdb import judge, parse_llm

```

In `atcdb/evaluate.py`, replace:

```python
    parser: str       # rule | llm
    model: str        # "rules", or a Claude model id
    context: str      # none | role | window

```

with:

```python
    parser: str       # rule | llm | judge
    model: str        # "rules", or a Claude model id
    context: str      # none | role | window; "sequence" for the judge, which sees the whole recording at once

```

In `atcdb/evaluate.py`, replace:

```python
# the pre-registered primary comparison
```

with:

```python
# the ablation (spec section 7): the whole transcript to Claude, conflicts out, no parser and no engine
JUDGE_ARMS: tuple[Arm, ...] = tuple(Arm("judge", m, "sequence", t) for m in judge.MODELS for t in TRANSCRIPTS)
# the pre-registered primary comparison
```

In `atcdb/evaluate.py`, replace:

```python
def recording_row(conn: sqlite3.Connection, arm: Arm, recording_id: int, set_name: str, truth: dict | None) -> dict:
    """Replay one recording under one arm and keep what scoring needs: per step the transmission, its time and events,
    and every conflict with the step that raised it. `span_s` covers all the recording's transmissions (first start to
    last end), whatever the transcript kind, so both transcript arms share a denominator. `missing_transcripts` counts
    transmissions with a gold transcript but none of the arm's kind (an ASR run that has not reached them); such a row
    is not scored. `all_test` says whether every transmission is in the ASR model's `test` split (spec section 3: the
    clean ASR headline)."""
    tl = build_timeline(conn, recording_id, parser=arm.parser, transcript_kind=arm.transcript, context=arm.context,
                        model=arm.model, transcript_model=default_transcript_model(conn, arm.transcript, recording_id))
    span, all_test = conn.execute(
        """SELECT MAX(end_s) - MIN(start_s), MIN(CASE WHEN split = 'test' THEN 1 ELSE 0 END)
           FROM transmissions WHERE recording_id = ?""", (recording_id,)).fetchone()
    gold = {tx.id for tx in load_recording(conn, recording_id, "gold", default_transcript_model(conn, "gold", recording_id))}
    return {"recording_id": recording_id, "set": set_name, "truth": truth, "span_s": span or 0.0,
            "all_test": bool(all_test), "missing_transcripts": len(gold - {s.tx.id for s in tl.steps}),
            "incomplete": any(s.error for s in tl.steps), "dropped": tl.dropped,
            "tx_ids": [s.tx.id for s in tl.steps], "t": [s.tx.start_s for s in tl.steps],
            "events": [[list(event_to_row(e)) for e in s.events] for s in tl.steps],
            "conflicts": [{"type": c.type, "severity": c.severity, "runway": c.runway, "callsigns": list(c.callsigns),
                           "tx_id": s.tx.id, "step": k} for k, s in enumerate(tl.steps) for c in s.conflicts]}
```

with:

```python
def _judge_steps(conn: sqlite3.Connection, arm: Arm, recording_id: int) -> dict:
    """The judge arm's part of a row: the transmissions it saw and the conflicts it reported, each an alert (the judge
    has no severities) placed at its trigger transmission. A failed call marks the row incomplete."""
    model = default_transcript_model(conn, arm.transcript, recording_id)
    txs = load_recording(conn, recording_id, arm.transcript, model)
    try:
        found, dropped = judge.judge(conn, recording_id, txs, arm.transcript, model or "", arm.model)
        error = False
    except Exception:   # an API error must not stop the run; nothing was cached, the next run retries
        found, dropped, error = [], 0, True
    return {"incomplete": error, "dropped": dropped, "tx_ids": [tx.id for tx in txs], "t": [tx.start_s for tx in txs],
            "events": [[] for _ in txs],
            "conflicts": [{"type": c["type"], "severity": "alert", "runway": c["runway"], "callsigns": c["callsigns"],
                           "tx_id": txs[c["step"]].id, "step": c["step"]} for c in found]}


def recording_row(conn: sqlite3.Connection, arm: Arm, recording_id: int, set_name: str, truth: dict | None) -> dict:
    """Replay one recording under one arm and keep what scoring needs: per step the transmission, its time and events,
    and every conflict with the step that raised it (for the judge arm, what the judge reported). `span_s` covers all
    the recording's transmissions (first start to last end), whatever the transcript kind, so both transcript arms
    share a denominator. `missing_transcripts` counts transmissions with a gold transcript but none of the arm's kind
    (an ASR run that has not reached them); such a row is not scored. `all_test` says whether every transmission is in
    the ASR model's `test` split (spec section 3: the clean ASR headline)."""
    if arm.parser == "judge":
        steps = _judge_steps(conn, arm, recording_id)
    else:
        tl = build_timeline(conn, recording_id, parser=arm.parser, transcript_kind=arm.transcript, context=arm.context,
                            model=arm.model, transcript_model=default_transcript_model(conn, arm.transcript, recording_id))
        steps = {"incomplete": any(s.error for s in tl.steps), "dropped": tl.dropped,
                 "tx_ids": [s.tx.id for s in tl.steps], "t": [s.tx.start_s for s in tl.steps],
                 "events": [[list(event_to_row(e)) for e in s.events] for s in tl.steps],
                 "conflicts": [{"type": c.type, "severity": c.severity, "runway": c.runway, "callsigns": list(c.callsigns),
                                "tx_id": s.tx.id, "step": k} for k, s in enumerate(tl.steps) for c in s.conflicts]}
    span, all_test = conn.execute(
        """SELECT MAX(end_s) - MIN(start_s), MIN(CASE WHEN split = 'test' THEN 1 ELSE 0 END)
           FROM transmissions WHERE recording_id = ?""", (recording_id,)).fetchone()
    gold = {tx.id for tx in load_recording(conn, recording_id, "gold", default_transcript_model(conn, "gold", recording_id))}
    return {"recording_id": recording_id, "set": set_name, "truth": truth, "span_s": span or 0.0,
            "all_test": bool(all_test), "missing_transcripts": len(gold - set(steps["tx_ids"])), **steps}
```

In `atcdb/evaluate.py`, replace:

```python
def uncached(conn: sqlite3.Connection, arm: Arm, recording_ids: Iterable[int]) -> tuple[int, float]:
    """(transmissions still to parse, rough USD) for one arm over the given recordings; parses and stores nothing."""
    misses = [m for rid in recording_ids for m in uncached_parses(
```

with:

```python
def uncached(conn: sqlite3.Connection, arm: Arm, recording_ids: Iterable[int]) -> tuple[int, float]:
    """(calls still to make, rough USD) for one arm over the given recordings: transmissions to parse, or for the judge
    recordings to judge. Calls and stores nothing."""
    if arm.parser == "judge":
        prompts = []
        for rid in recording_ids:
            model = default_transcript_model(conn, arm.transcript, rid)
            txs = load_recording(conn, rid, arm.transcript, model)
            if txs and not judge.is_cached(conn, rid, arm.transcript, model or "", arm.model):
                prompts.append(judge.render_sequence(txs))
        return len(prompts), judge.estimate_cost(arm.model, prompts)
    misses = [m for rid in recording_ids for m in uncached_parses(
```

In `scripts/eval_conflicts.py`, replace:

```python
run [--parser rule|llm] [--model M]
```

with:

```python
run [--parser rule|llm|judge] [--model M]
```

In `scripts/eval_conflicts.py`, replace:

```python
`run` replays every recording of the evaluation sets under each selected arm (all 18 by default) and writes one JSONL
per arm to data/eval/conflicts/. Parses come from the events cache, so a re-run is free; always `--dry-run` first, which
prints the uncached calls and a rough cost per arm and spends nothing.
```

with:

```python
`run` replays every recording of the evaluation sets under each selected arm (the 18 structured arms and the two
judge arms by default; `--parser judge` for the judge only) and writes one JSONL per arm to data/eval/conflicts/.
Parses and judgments come from their caches, so a re-run is free; always `--dry-run` first, which prints the uncached
calls and a rough cost per arm and spends nothing.
```

In `scripts/eval_conflicts.py`, replace:

```python
from atcdb.evaluate import (ADJUDICATION_COLUMNS, ARMS, adjudication_kappa, adjudication_rows, evaluation_sets,  # noqa: E402
                            overlap_rows, read_rows, run_arm, uncached, write_rows)
from atcdb.schema import init_db  # noqa: E402
```

with:

```python
from atcdb.evaluate import (ADJUDICATION_COLUMNS, ARMS, JUDGE_ARMS, adjudication_kappa, adjudication_rows,  # noqa: E402
                            evaluation_sets, overlap_rows, read_rows, run_arm, uncached, write_rows)
from atcdb.schema import init_db  # noqa: E402
```

In `scripts/eval_conflicts.py`, replace:

```python
def selected_arms(args: argparse.Namespace) -> list:
    return [a for a in ARMS if all(getattr(args, f) in (None, getattr(a, f)) for f in ("parser", "model", "context", "transcript"))]
```

with:

```python
def selected_arms(args: argparse.Namespace) -> list:
    return [a for a in ARMS + JUDGE_ARMS
            if all(getattr(args, f) in (None, getattr(a, f)) for f in ("parser", "model", "context", "transcript"))]
```

In `scripts/eval_conflicts.py`, replace:

```python
    run.add_argument("--parser", choices=["rule", "llm"])
    run.add_argument("--model")
    run.add_argument("--context", choices=["none", "role", "window"])
```

with:

```python
    run.add_argument("--parser", choices=["rule", "llm", "judge"])
    run.add_argument("--model")
    run.add_argument("--context", choices=["none", "role", "window", "sequence"])
```

Create `scripts/record_judge_fixtures.py`:

```python
#!/usr/bin/env python3
"""Record real Claude replies for the judge's regression fixtures (tests/fixtures/judge_responses.json).

Usage:
    ANTHROPIC_API_KEY=... python scripts/record_judge_fixtures.py

Sends each case below to every model in judge.MODELS with exactly the request the judge makes, and stores each reply's
stop reason and content blocks. Re-run it whenever judge.VERSION is bumped, then update the expectations in
tests/test_judge.py. The sequences are invented: UWB-ATCC corpus text is CC BY-NC-ND and must never be written into a
fixture.
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import anthropic  # noqa: E402

from atcdb.judge import MODELS, VERSION, request  # noqa: E402
from atcdb.parsing import Transmission  # noqa: E402

OUT = ROOT / "tests" / "fixtures" / "judge_responses.json"

# name -> [(role, text), ...]
CASES: dict[str, list[tuple[str, str]]] = {
    "crossing_against_a_landing": [
        ("controller", "csa one two three runway three one cleared to land wind calm"),
        ("pilot", "cleared to land runway three one csa one two three"),
        ("controller", "lufthansa four five six cross runway three one"),
        ("pilot", "crossing runway three one lufthansa four five six"),
    ],
    "released_before_the_takeoff": [
        ("controller", "csa one two three runway three one cleared to land wind calm"),
        ("pilot", "cleared to land runway three one csa one two three"),
        ("pilot", "runway vacated csa one two three"),
        ("controller", "csa one two three contact ground one two one decimal nine"),
        ("controller", "lufthansa four five six runway three one cleared for takeoff"),
        ("pilot", "cleared for takeoff runway three one lufthansa four five six"),
    ],
}


def main() -> None:
    client = anthropic.Anthropic()
    records = []
    for name, turns in CASES.items():
        txs = [Transmission(id=i, transcript_id=i, text=text, role=role, start_s=10.0 * i) for i, (role, text) in enumerate(turns)]
        for model in MODELS:
            reply = client.messages.create(**request(model, txs))
            records.append({"case": name, "model": model, "version": VERSION, "turns": [list(t) for t in turns],
                            "stop_reason": reply.stop_reason, "content": [b.to_dict() for b in reply.content]})
            print(f"{name:32} {model:18} {reply.stop_reason}", flush=True)
    OUT.write_text(json.dumps(records, indent=1) + "\n")
    print(f"wrote {len(records)} replies to {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_judge.py tests/test_schema.py tests/test_evaluate.py -q` then `.venv/bin/python -m pytest -q`
Expected: PASS; the whole suite is 279 passed with `ANTHROPIC_API_KEY` set (277 passed and 2 skipped without it).

- [ ] **Step 5: Dry-run the judge on a copy of the corpus (skip if `data/atc.sqlite` is absent)**

Run: `cp data/atc.sqlite /tmp/judge-check.sqlite && .venv/bin/python scripts/eval_conflicts.py --db /tmp/judge-check.sqlite --out /tmp/judge-check run --parser judge --dry-run`
Expected: two judge arms, 309 uncached calls for gold and fewer for ASR (only fully transcribed recordings), under
$2 in total; nothing is called. Delete the files. Do not re-record the fixture unless `judge.VERSION` changes.

- [ ] **Step 6: Commit**

```bash
git add atcdb/schema.py atcdb/judge.py atcdb/evaluate.py scripts/eval_conflicts.py scripts/record_judge_fixtures.py tests/fixtures/judge_responses.json tests/test_judge.py tests/test_schema.py
git commit -m "feat: LLM judge ablation arm with a judgments cache"
```
End the message with the attribution lines the session provides.

---

### Task 6: CROSS and LUAW staleness sweep

A finding, not a tuning (spec section 9): the longest replayable recording spans 139 s, so no timeout of 139 s
or more changes anything here. The sweep re-folds each arm's stored events with CROSS and LUAW set to 30, 60, 90, 120
and 300 s, without new parses, and reports recall and raw negative alerts. On the rules arms, shortening never removes
a negative alert (those come from landing and takeoff clearances) but loses real crossings at 30 s. `engine.STALE_S`
is overridden in place and always restored; nothing else changes.

**Files:**
- Modify: `atcdb/evaluate.py` (append the sweep section)
- Modify: `scripts/eval_conflicts.py` (the `sweep` subcommand)
- Test: `tests/test_evaluate.py`

**Interfaces:**
- Produces: `evaluate.SWEEP_KINDS`, `SWEEP_VALUES`, `refold(row, stale) -> list[conflict]` (RUNWAY only),
  `sweep(rows, values=SWEEP_VALUES, kinds=SWEEP_KINDS) -> list[{"stale_s", "recall", "negative_alerts"}]`.

- [ ] **Step 1: Write the failing tests**

In `tests/test_evaluate.py`, replace:

```python
from atcdb.evaluate import (ARMS, PRIMARY, Arm, Pending, adjudication_kappa, adjudication_rows, alert_key, alert_keys,
                            bootstrap, cohen_kappa, detection, evaluation_sets, false_alarm_units, in_overlap, overlap_rows,
                            paired_bootstrap, per_hour, rate, read_rows, read_verdicts, recall, recording_row, run_arm,
                            uncached, usable, write_rows)
```

with:

```python
from atcdb import engine
from atcdb.evaluate import (ARMS, PRIMARY, Arm, Pending, adjudication_kappa, adjudication_rows, alert_key, alert_keys,
                            bootstrap, cohen_kappa, detection, evaluation_sets, false_alarm_units, in_overlap, overlap_rows,
                            paired_bootstrap, per_hour, rate, read_rows, read_verdicts, recall, recording_row, refold,
                            run_arm, sweep, uncached, usable, write_rows)
```

Append to `tests/test_evaluate.py`:

```python


def test_refold_at_the_default_timeouts_reproduces_the_replay(tmp_path):
    db = tmp_path / "t.sqlite"
    conn = init_db(db)
    [row] = run_arm(db, PRIMARY[0], [(_seed(conn, CONFLICT), "negatives", None)])
    assert refold(row, {}) == [c for c in row["conflicts"] if c["type"] == "RUNWAY"] != []


def _timed(events_by_step, t, truth=None, set_name="positives", rid=1):
    """A row whose steps are at times `t`, with the given event rows."""
    return {"recording_id": rid, "set": set_name, "truth": truth, "span_s": 100.0, "incomplete": False,
            "missing_transcripts": 0, "tx_ids": list(range(1, len(t) + 1)), "t": list(t), "events": events_by_step,
            "conflicts": []}


def test_a_shorter_crossing_timeout_forgets_the_crossing_before_the_landing():
    events = [[["CROSS", "lufthansa four five six", "31", None]], [], [["LAND", "csa one two three", "31", None]]]
    row = _timed(events, [0.0, 20.0, 60.0], truth={"runway": "31", "trigger_tx": 3, "edit_kind": "splice"})
    assert [c["step"] for c in refold(row, {})] == [2]
    assert refold(row, {"CROSS": 30.0}) == []
    assert engine.STALE_S["CROSS"] == 300.0                       # the override never leaks
    negative = {**_timed(events, [0.0, 20.0, 60.0], set_name="negatives", rid=2)}
    result = sweep([row, negative], values=(30.0, 300.0))
    assert [r["stale_s"] for r in result] == [30.0, 300.0]
    assert [r["recall"]["strict"] for r in result] == [0, 1]
    assert [r["negative_alerts"] for r in result] == [0, 1]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_evaluate.py -q`
Expected: FAIL at collection with `ImportError: cannot import name 'refold'`.

- [ ] **Step 3: Write the implementation**

In `atcdb/evaluate.py`, replace:

```python
from atcdb import judge, parse_llm
from atcdb.inject import synthetic_recordings
from atcdb.parsing import CONTEXT_MODES, event_to_row

```

with:

```python
from atcdb import engine, judge, parse_llm
from atcdb.engine import State
from atcdb.inject import synthetic_recordings
from atcdb.parsing import CONTEXT_MODES, event_to_row, row_to_event

```

Append to `atcdb/evaluate.py`:

```python


# --- staleness sweep (spec section 9) --------------------------------------------------------------------------------

SWEEP_KINDS = ("CROSS", "LUAW")
SWEEP_VALUES = (30.0, 60.0, 90.0, 120.0, 300.0)


def refold(row: dict, stale: dict[str, float]) -> list[dict]:
    """The row's RUNWAY conflicts re-derived from its stored events with `engine.STALE_S` overridden by `stale`. No
    parse is repeated, so a `window` arm keeps the context it was parsed with. READBACK conflicts are not re-derived
    (the stored events do not carry the instruction text a readback is checked against)."""
    saved = dict(engine.STALE_S)
    engine.STALE_S.update(stale)
    try:
        state, out = State(), []
        for k, (tx_id, t, events) in enumerate(zip(row["tx_ids"], row["t"], row["events"])):
            for kind, callsign, runway, extra in events:
                state, new = engine.apply(state, row_to_event(kind, callsign, runway, extra, t=t))
                out += [{"type": c.type, "severity": c.severity, "runway": c.runway, "callsigns": list(c.callsigns),
                         "tx_id": tx_id, "step": k} for c in new if c.type == "RUNWAY"]
        return out
    finally:
        engine.STALE_S.clear()
        engine.STALE_S.update(saved)


def sweep(rows: list[dict], values: Iterable[float] = SWEEP_VALUES, kinds: tuple[str, ...] = SWEEP_KINDS) -> list[dict]:
    """For each timeout value applied to `kinds`: recall on the arm's positives and the raw count of distinct RUNWAY
    alerts on its negatives (not adjudicated: the sweep is a sensitivity finding, nothing is chosen from it)."""
    out = []
    for v in values:
        refolded = [{**r, "conflicts": refold(r, {k: v for k in kinds})} for r in rows if usable(r)]
        alerts = set().union(*[alert_keys(r, "RUNWAY") for r in refolded if r["set"] == "negatives"])
        out.append({"stale_s": v, "recall": recall([r for r in refolded if r["set"] == "positives"]),
                    "negative_alerts": len(alerts)})
    return out
```

In `scripts/eval_conflicts.py`, replace:

```python
    python scripts/eval_conflicts.py adjudicate [--kappa]

```

with:

```python
    python scripts/eval_conflicts.py adjudicate [--kappa]
    python scripts/eval_conflicts.py sweep [--values 30 60 90 120 300]

```

In `scripts/eval_conflicts.py`, replace:

```python
(extraction right, the matrix is too strict). Re-run it after new arms have run. `--kappa` reports agreement instead.

```

with:

```python
(extraction right, the matrix is too strict). Re-run it after new arms have run. `--kappa` reports agreement instead.

`sweep` re-folds every structured arm's stored events with the CROSS and LUAW timeouts set to each value and prints
lenient recall and raw negative alerts per value. A finding only: engine.STALE_S is not changed.

```

In `scripts/eval_conflicts.py`, replace:

```python
from atcdb.evaluate import (ADJUDICATION_COLUMNS, ARMS, JUDGE_ARMS, adjudication_kappa, adjudication_rows,  # noqa: E402
                            evaluation_sets, overlap_rows, read_rows, run_arm, uncached, write_rows)
from atcdb.schema import init_db  # noqa: E402
```

with:

```python
from atcdb.evaluate import (ADJUDICATION_COLUMNS, ARMS, JUDGE_ARMS, SWEEP_VALUES, adjudication_kappa,  # noqa: E402
                            adjudication_rows, evaluation_sets, overlap_rows, read_rows, run_arm, sweep, uncached,
                            write_rows)
from atcdb.schema import init_db  # noqa: E402
```

In `scripts/eval_conflicts.py`, replace:

```python
def main() -> None:
```

with:

```python
def cmd_sweep(args: argparse.Namespace) -> None:
    print(f"  {'arm':<40} " + "  ".join(f"{v:>5.0f}s recall/alerts" for v in args.values))
    for name, rows in arm_rows(args.out).items():
        if name.startswith("judge-"):
            continue   # the judge has no events to re-fold
        cells = [f"{r['recall']['lenient']:>5}/{r['recall']['n']:<4}{r['negative_alerts']:>9}" for r in sweep(rows, args.values)]
        print(f"  {name:<40} " + "  ".join(cells))


def main() -> None:
```

In `scripts/eval_conflicts.py`, replace:

```python
    adj.set_defaults(func=cmd_adjudicate)

```

with:

```python
    adj.set_defaults(func=cmd_adjudicate)
    sw = sub.add_parser("sweep", help="CROSS/LUAW staleness sensitivity (a finding, not a tuning)")
    sw.add_argument("--values", type=float, nargs="+", default=list(SWEEP_VALUES))
    sw.set_defaults(func=cmd_sweep)

```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_evaluate.py -q` then `.venv/bin/python -m pytest -q`
Expected: PASS; the whole suite is 281 passed with `ANTHROPIC_API_KEY` set (279 passed and 2 skipped without it).

- [ ] **Step 5: Commit**

```bash
git add atcdb/evaluate.py scripts/eval_conflicts.py tests/test_evaluate.py
git commit -m "feat: CROSS/LUAW staleness sensitivity sweep"
```
End the message with the attribution lines the session provides.

---

### Task 7: The results doc, and the README

`eval_report.summarize` turns every arm's rows, the adjudication verdicts, the injection check verdicts and
the adjudication kappa into numbers, and `render` writes `docs/results/conflict-eval.md` in the style of the existing
results docs: the pre-registered primary comparison first, then all arms, the ASR headline on fully test-split
recordings, recall per injection kind, the failure taxonomy, agreement and generator precision, the sweep and the
caveats. A rate whose alerts are not all adjudicated prints `pending`; an arm with no scorable negatives prints `n/a`.
The text is report material: no em dashes (a test checks).

**Files:**
- Create: `atcdb/eval_report.py`
- Modify: `scripts/eval_conflicts.py` (the `report` subcommand)
- Modify: `README.md`
- Test: `tests/test_eval_report.py`

**Interfaces:**
- Consumes: everything `evaluate` produces; `inject.EDIT_KINDS`, `inject.synthetic_recordings`.
- Produces: `eval_report.arm_summary`, `primary_differences`, `taxonomy`, `summarize(rows_by_arm, verdicts,
  injections, kappa) -> dict`, `render(summary, date) -> str`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_eval_report.py`:

```python
from atcdb.eval_report import arm_summary, primary_differences, render, summarize, taxonomy
from atcdb.evaluate import PRIMARY

TRUTH = {"runway": "31", "trigger_tx": 3, "edit_kind": "splice"}


def _c(step, severity="alert", runway="31", type_="RUNWAY"):
    return {"type": type_, "severity": severity, "runway": runway, "callsigns": ["a", "b"], "step": step, "tx_id": step + 1}


def _row(rid, set_name, conflicts, all_test=True, span=1800.0):
    events = [[["LAND", "a", "31", None]], [], [["CROSS", "b", "31", None]], []]
    return {"recording_id": rid, "set": set_name, "truth": TRUTH if set_name == "positives" else None, "span_s": span,
            "all_test": all_test, "incomplete": False, "missing_transcripts": 0, "dropped": 0, "tx_ids": [1, 2, 3, 4],
            "t": [0.0, 10.0, 20.0, 30.0], "events": events, "conflicts": conflicts}


RULES = [_row(1, "positives", [_c(2)]), _row(2, "positives", []), _row(10, "negatives", [_c(1)]),
         _row(11, "negatives", [], all_test=False)]
SONNET = [_row(1, "positives", [_c(2)]), _row(2, "positives", [_c(3)]), _row(10, "negatives", []),
          _row(11, "negatives", [], all_test=False)]
VERDICTS = {"10:RUNWAY:31:2": "missing_info"}


def test_arm_summary_counts_recall_and_false_alarms():
    s = arm_summary(RULES, VERDICTS)
    assert s["recall"] == {"n": 2, "strict": 1, "lenient": 1, "partial": 0, "miss": 1}
    assert s["fa_RUNWAY"] == 1.0 and s["hours"] == 1.0 and s["fa_READBACK"] == 0.0
    assert s["by_kind"]["splice"]["n"] == 2 and s["by_kind"]["runway_swap"]["n"] == 0
    assert arm_summary(RULES, {})["fa_RUNWAY"] is None   # an unadjudicated alert: pending, not a number


def test_primary_differences_are_paired_over_common_recordings():
    d = primary_differences(RULES, SONNET, VERDICTS)
    assert d["recall"][0] == -0.5 and d["recall_n"] == 2
    assert d["fa"][0] == 1.0 and d["fa_n"] == 2
    assert primary_differences(RULES, SONNET, {})["fa"] is None


def test_taxonomy_counts_verdicts_of_the_arms_own_alerts():
    assert taxonomy(RULES, VERDICTS) == {"missing_info": 1}
    assert taxonomy(RULES, {}) == {"unadjudicated": 1}


def test_the_report_covers_every_section_and_uses_no_em_dash():
    rows = {PRIMARY[0].name: RULES, PRIMARY[1].name: SONNET, "rule-rules-window-asr": RULES}
    injections = [{"edit_kind": "splice", "valid": "yes"}, {"edit_kind": "splice", "valid": "no"},
                  {"edit_kind": "runway_swap"}]
    summary = summarize(rows, VERDICTS, injections, (0.8, 12))
    assert summary["checks"]["splice"] == {"yes": 1, "no": 1} and summary["checks"]["runway_swap"] == {"unchecked": 1}
    assert list(summary["asr_headline"]) == ["rule-rules-window-asr"]
    assert summary["asr_headline"]["rule-rules-window-asr"]["hours"] == 0.5   # recording 11 is not all test split
    text = render(summary, "29 Sep 2026")
    for heading in ("Primary comparison", "All arms", "ASR headline", "Recall by injection kind", "Failure taxonomy",
                    "Agreement and generator precision", "staleness sensitivity", "Caveats"):
        assert heading in text
    assert "Cohen's kappa 0.80 over 12 alerts" in text and "-50 pts" in text
    assert "\u2014" not in text
    pending = render(summarize(rows, {}, [], None), "29 Sep 2026")
    assert "pending" in pending and "no alert has been labelled by both" in pending
    no_asr = summarize({"rule-rules-window-asr": [{**r, "missing_transcripts": 1} for r in RULES]}, {}, [], None)
    assert no_asr["arms"]["rule-rules-window-asr"]["hours"] == 0 and "| n/a | 0 | n/a | n/a | 0.00 |" in render(no_asr, "x")
    assert "Not run yet" in render(summarize({"rule-rules-none-gold": RULES}, VERDICTS, [], None), "29 Sep 2026")
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_eval_report.py -q`
Expected: FAIL at collection with `ModuleNotFoundError: No module named 'atcdb.eval_report'`.

- [ ] **Step 3: Write the implementation**

Create `atcdb/eval_report.py`:

```python
"""The Level 2 results doc (spec 2026-09-29-evaluation-3b1-design.md, section 10).

`summarize` turns every arm's rows, the adjudication verdicts, the injection check verdicts and the adjudication kappa
into plain numbers; `render` writes them as Markdown in the style of docs/results/. Both are pure. A false-alarm rate
whose alerts are not all adjudicated is reported as pending, never as a number. No em dashes: the text goes into the
report.
"""
from collections import Counter

from atcdb.evaluate import (PRIMARY, Pending, alert_keys, bootstrap, detection, false_alarm_units, paired_bootstrap,
                            per_hour, rate, recall, sweep, usable)
from atcdb.inject import EDIT_KINDS


def _recall_units(rows: list[dict]) -> dict[int, float]:
    """recording_id -> 1.0 for a lenient hit, 0.0 otherwise, over usable scorable positives."""
    out = {}
    for r in rows:
        if r["set"] == "positives" and usable(r):
            d = detection(r)
            if d != "unscorable":
                out[r["recording_id"]] = 1.0 if d in ("strict", "lenient") else 0.0
    return out


def _fa_units(rows: list[dict], verdicts: dict[str, str], conflict_type: str) -> dict[int, tuple[float, float]] | None:
    """recording_id -> (false alarms, span_s) over usable negatives, or None while some alert is unadjudicated."""
    negatives = [r for r in rows if r["set"] == "negatives" and usable(r)]
    try:
        units = false_alarm_units(negatives, verdicts, conflict_type)
    except Pending:
        return None
    return {r["recording_id"]: u for r, u in zip(negatives, units)}


def arm_summary(rows: list[dict], verdicts: dict[str, str]) -> dict:
    """Recall (strict, lenient with CI, partial), false alarms per hour (RUNWAY and READBACK, with CI, or None when
    pending), and the counts behind them, for one arm's rows."""
    positives = [r for r in rows if r["set"] == "positives"]
    negatives = [r for r in rows if r["set"] == "negatives"]
    hits = _recall_units(rows)
    out = {"recall": recall(positives), "recall_ci": bootstrap(list(hits.values()), rate),
           "incomplete": sum(r["incomplete"] for r in rows),
           "unscored": sum(not usable(r) for r in rows),
           "hours": sum(r["span_s"] for r in negatives if usable(r)) / 3600,
           "by_kind": {k: recall([r for r in positives if r["truth"]["edit_kind"] == k]) for k in EDIT_KINDS}}
    for t in ("RUNWAY", "READBACK"):
        units = _fa_units(rows, verdicts, t)
        out[f"fa_{t}"] = None if units is None else per_hour(list(units.values()))
        out[f"fa_{t}_ci"] = None if units is None else bootstrap(list(units.values()), per_hour)
    return out


def primary_differences(rows_a: list[dict], rows_b: list[dict], verdicts: dict[str, str]) -> dict:
    """Paired (point, low, high) differences, first arm minus second, over the recordings both arms scored: lenient
    recall, and RUNWAY false alarms per hour (None while pending)."""
    ha, hb = _recall_units(rows_a), _recall_units(rows_b)
    common = sorted(set(ha) & set(hb))
    out = {"recall": paired_bootstrap([(ha[k], hb[k]) for k in common], rate) if common else None, "recall_n": len(common)}
    fa, fb = _fa_units(rows_a, verdicts, "RUNWAY"), _fa_units(rows_b, verdicts, "RUNWAY")
    if fa is None or fb is None:
        out["fa"], out["fa_n"] = None, 0
    else:
        both = sorted(set(fa) & set(fb))
        out["fa"] = paired_bootstrap([(fa[k], fb[k]) for k in both], per_hour) if both else None
        out["fa_n"] = len(both)
    return out


def taxonomy(rows: list[dict], verdicts: dict[str, str]) -> Counter:
    """Verdict counts over the distinct alerts one arm raised on usable negatives (`unadjudicated` for none yet)."""
    keys = set().union(*[alert_keys(r) for r in rows if r["set"] == "negatives" and usable(r)])
    return Counter(verdicts.get(k, "unadjudicated") for k in keys)


def summarize(rows_by_arm: dict[str, list[dict]], verdicts: dict[str, str], injections: list[dict],
              kappa: tuple[float, int] | None) -> dict:
    """Everything the results doc reports. `injections` are the stored injections with their check verdicts (atcdb.inject
    .synthetic_recordings); `kappa` is the adjudication agreement, or None before a second adjudicator has started."""
    arms = {name: arm_summary(rows, verdicts) for name, rows in sorted(rows_by_arm.items())}
    headline = {name: arm_summary([r for r in rows if r["all_test"]], verdicts)
                for name, rows in sorted(rows_by_arm.items()) if name.endswith("-asr")}
    primary = [a.name for a in PRIMARY]
    checks = {k: Counter(i.get("valid") or "unchecked" for i in injections if i["edit_kind"] == k) for k in EDIT_KINDS}
    return {
        "arms": arms, "asr_headline": headline, "kappa": kappa, "checks": checks,
        "primary": primary if all(p in rows_by_arm for p in primary) else None,
        "primary_diff": primary_differences(rows_by_arm[primary[0]], rows_by_arm[primary[1]], verdicts)
        if all(p in rows_by_arm for p in primary) else None,
        "taxonomy": {name: taxonomy(rows, verdicts) for name, rows in sorted(rows_by_arm.items())},
        "sweep": {p: sweep(rows_by_arm[p]) for p in primary if p in rows_by_arm},
    }


def _pct(x: float) -> str:
    return f"{100 * x:.0f}%"


def _recall_cell(s: dict) -> str:
    r = s["recall"]
    if not r["n"]:
        return "n/a"
    lo, hi = s["recall_ci"]
    return f"{_pct(r['lenient'] / r['n'])} ({_pct(lo)} to {_pct(hi)})"


def _fa_cell(s: dict, t: str = "RUNWAY") -> str:
    if not s["hours"]:
        return "n/a"
    if s[f"fa_{t}"] is None:
        return "pending"
    lo, hi = s[f"fa_{t}_ci"]
    return f"{s[f'fa_{t}']:.1f} ({lo:.1f} to {hi:.1f})"


def _diff_cell(d: tuple[float, float, float] | None, pct: bool) -> str:
    if d is None:
        return "pending"
    fmt = (lambda x: f"{100 * x:+.0f} pts") if pct else (lambda x: f"{x:+.1f}")
    return f"{fmt(d[0])} ({fmt(d[1])} to {fmt(d[2])})"


def _arm_table(arms: dict[str, dict]) -> list[str]:
    lines = ["| Arm | Positives | Strict | Lenient recall (95% CI) | Warning only | RUNWAY false alarms / h (95% CI) "
             "| READBACK false alarms / h | Hours | Incomplete | Not scored |",
             "|---|---:|---:|---|---:|---|---|---:|---:|---:|"]
    for name, s in arms.items():
        r = s["recall"]
        lines.append(f"| {name} | {r['n']} | {r['strict']} | {_recall_cell(s)} | {r['partial']} | {_fa_cell(s)} "
                     f"| {_fa_cell(s, 'READBACK')} | {s['hours']:.2f} | {s['incomplete']} | {s['unscored']} |")
    return lines


def render(summary: dict, date: str) -> str:
    """The results doc as Markdown."""
    out = [f"# Conflict detection, Level 2 ({date})", "",
           "Positives are synthetic conflicts injected into real tower recordings and accepted by a human check; negatives "
           "are the unperturbed real recordings. Recall is lenient (an alert on the injected runway at or after the "
           "trigger transmission) unless marked strict (at the trigger). A false alarm is an alert on a negative that "
           "adjudication did not find genuine; rates are per hour of recording span. Intervals are 95% percentile "
           "bootstrap intervals over recordings (2,000 resamples, seed 0).", ""]
    if summary["primary"]:
        a, b = summary["primary"]
        sa, sb, d = summary["arms"][a], summary["arms"][b], summary["primary_diff"]
        out += ["## Primary comparison (pre-registered)", "",
                "| | " + a + " | " + b + " | Difference, first minus second (95% CI) |", "|---|---|---|---|",
                f"| Lenient recall | {_recall_cell(sa)} | {_recall_cell(sb)} | {_diff_cell(d['recall'], True)} "
                f"over {d['recall_n']} positives |",
                f"| RUNWAY false alarms / h | {_fa_cell(sa)} | {_fa_cell(sb)} | {_diff_cell(d['fa'], False)} |", ""]
    else:
        out += ["## Primary comparison (pre-registered)", "", "Not run yet: both primary arms are needed.", ""]
    out += ["## All arms, human and ASR transcripts", ""] + _arm_table(summary["arms"]) + [""]
    out += ["## ASR headline: recordings entirely in the ASR model's test split", "",
            "The Whisper model was fine-tuned on the corpus's train split, so ASR over train-split clips is optimistic. "
            "These rows keep only recordings whose every transmission is test split; the ASR rows above use all "
            "recordings and their degradation is a lower bound.", ""]
    out += _arm_table(summary["asr_headline"]) + [""] if summary["asr_headline"] else ["No ASR arm has run yet.", ""]
    out += ["## Recall by injection kind (lenient hits / scored)", "",
            "| Arm | " + " | ".join(EDIT_KINDS) + " |", "|---|" + "---:|" * len(EDIT_KINDS)]
    for name, s in summary["arms"].items():
        out.append(f"| {name} | " + " | ".join(f"{s['by_kind'][k]['lenient']}/{s['by_kind'][k]['n']}" for k in EDIT_KINDS) + " |")
    out += ["", "## Failure taxonomy of alerts on real recordings", "",
            "| Arm | genuine | parse_error | missing_info | engine_rule | unadjudicated |", "|---|---:|---:|---:|---:|---:|"]
    for name, t in summary["taxonomy"].items():
        out.append(f"| {name} | " + " | ".join(str(t.get(v, 0)) for v in
                                              ("genuine", "parse_error", "missing_info", "engine_rule", "unadjudicated")) + " |")
    kappa = summary["kappa"]
    out += ["", "## Agreement and generator precision", "",
            f"Adjudication agreement: Cohen's kappa {kappa[0]:.2f} over {kappa[1]} alerts labelled by both adjudicators."
            if kappa and kappa[1] else "Adjudication agreement: no alert has been labelled by both adjudicators yet.", "",
            "| Injection kind | Accepted | Rejected | Not checked |", "|---|---:|---:|---:|"]
    for k, c in summary["checks"].items():
        out.append(f"| {k} | {c.get('yes', 0)} | {c.get('no', 0)} | {c.get('unchecked', 0)} |")
    out += ["", "## CROSS and LUAW staleness sensitivity (a finding, not a tuning)", "",
            "The longest replayable recording spans 139 s, so no timeout of 139 s or more can change anything on this "
            "corpus; values below it are shown for sensitivity only, re-folding the stored events without new parses. "
            "`engine.STALE_S` stays at 300 s.", ""]
    for arm, rows in summary["sweep"].items():
        out += [f"{arm}:", "", "| CROSS and LUAW timeout | Lenient recall | RUNWAY alerts on negatives (raw) |",
                "|---:|---|---:|"]
        out += [f"| {r['stale_s']:.0f} s | {r['recall']['lenient']}/{r['recall']['n']} | {r['negative_alerts']} |" for r in rows]
        out.append("")
    out += ["## Caveats", "",
            "- The positives are synthetic. Most are splices: one real recording ending with a runway reservation, "
            "followed by another real recording from the same airport with a conflicting clearance. The rest are single "
            "edits of real text. Only the incident case studies (phase 4) are real conflicts.",
            "- Injection sites come from a keyword scan of clearance phrases with a runway. Conflicts phrased in ways "
            "the scan misses are not represented, which favours parsers that handle the same phrasing.",
            "- For text edits, the edited transmission's audio still says the original words, so its ASR transcript is "
            "the edited gold text; the ASR arms test noise on the rest of the sequence only.",
            "- The engine treats runway designators as separate runways, so a clearance for 13 and one for 31 (the two "
            "ends of one strip) never conflict.",
            "- The judge reports no severity; every conflict it reports is scored as an alert.", ""]
    return "\n".join(out)
```

In `scripts/eval_conflicts.py`, replace:

```python
    python scripts/eval_conflicts.py sweep [--values 30 60 90 120 300]

```

with:

```python
    python scripts/eval_conflicts.py sweep [--values 30 60 90 120 300]
    python scripts/eval_conflicts.py report [--doc docs/results/conflict-eval.md]

```

In `scripts/eval_conflicts.py`, replace:

```python
lenient recall and raw negative alerts per value. A finding only: engine.STALE_S is not changed.

```

with:

```python
lenient recall and raw negative alerts per value. A finding only: engine.STALE_S is not changed.

`report` writes the results doc from the arms' rows, the adjudication sheets and the injection check verdicts. False
alarm rates show as pending until every alert has a verdict on sheet A.

```

In `scripts/eval_conflicts.py`, replace:

```python
import csv
import sys

```

with:

```python
import csv
import datetime
import sys

```

In `scripts/eval_conflicts.py`, replace:

```python
from atcdb.evaluate import (ADJUDICATION_COLUMNS, ARMS, JUDGE_ARMS, SWEEP_VALUES, adjudication_kappa,  # noqa: E402
                            adjudication_rows, evaluation_sets, overlap_rows, read_rows, run_arm, sweep, uncached,
                            write_rows)
from atcdb.schema import init_db  # noqa: E402
```

with:

```python
from atcdb.eval_report import render, summarize  # noqa: E402
from atcdb.evaluate import (ADJUDICATION_COLUMNS, ARMS, JUDGE_ARMS, SWEEP_VALUES, adjudication_kappa,  # noqa: E402
                            adjudication_rows, evaluation_sets, overlap_rows, read_rows, read_verdicts, run_arm, sweep,
                            uncached, write_rows)
from atcdb.inject import synthetic_recordings  # noqa: E402
from atcdb.schema import init_db  # noqa: E402
```

In `scripts/eval_conflicts.py`, replace:

```python
def main() -> None:
```

with:

```python
def cmd_report(args: argparse.Namespace) -> None:
    sheet_a, sheet_b = read_sheet(args.sheet_a), read_sheet(args.sheet_b)
    both = set(read_verdicts(sheet_a)) & set(read_verdicts(sheet_b))
    kappa = adjudication_kappa(sheet_a, sheet_b) if both else None
    summary = summarize(arm_rows(args.out), read_verdicts(sheet_a), synthetic_recordings(init_db(args.db)), kappa)
    args.doc.parent.mkdir(parents=True, exist_ok=True)
    args.doc.write_text(render(summary, datetime.date.today().strftime("%d %b %Y")))
    print(f"wrote {args.doc}")


def main() -> None:
```

In `scripts/eval_conflicts.py`, replace:

```python
    sw.set_defaults(func=cmd_sweep)

```

with:

```python
    sw.set_defaults(func=cmd_sweep)
    rep = sub.add_parser("report", help="write the results doc")
    rep.add_argument("--sheet-a", type=Path, default=SHEET_A)
    rep.add_argument("--sheet-b", type=Path, default=SHEET_B)
    rep.add_argument("--doc", type=Path, default=ROOT / "docs/results/conflict-eval.md")
    rep.set_defaults(func=cmd_report)

```

In `README.md`, replace:

```markdown
pytest   # 215 tests; the live smoke test skips without ANTHROPIC_API_KEY
```

with:

```markdown
# 7. evaluation, Level 2 (phase 3b-1): synthetic conflicts, every arm, adjudication, results doc.
#    See docs/superpowers/specs/2026-09-29-evaluation-3b1-design.md. Dry-run before every paid run.
python scripts/make_event_sheet.py                  # Level 1 labelling sheets -> data/labels/event_sheet_{A,B}.csv
python scripts/run_asr.py --split train             # ASR for the rest of the corpus (~2 h CPU); before injecting
python scripts/inject_conflicts.py                  # store 100 synthetic-conflict recordings
python scripts/inject_conflicts.py --sheet data/labels/injection_check.csv        # then fill `valid` and
python scripts/inject_conflicts.py --apply-sheet data/labels/injection_check.csv  # record the verdicts
python scripts/eval_conflicts.py run --dry-run      # uncached calls and cost per arm; then without --dry-run
python scripts/eval_conflicts.py adjudicate         # alert verdicts -> data/labels/adjudication_{A,B}.csv
python scripts/eval_conflicts.py report             # -> docs/results/conflict-eval.md

pytest   # 285 tests; the live smoke tests skip without ANTHROPIC_API_KEY
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest -q`
Expected: PASS; the whole suite is 285 passed with `ANTHROPIC_API_KEY` set (283 passed and 2 skipped without it).

- [ ] **Step 5: Render a report from the rules arms on a copy of the corpus (skip if `data/atc.sqlite` is absent)**

Run: `cp data/atc.sqlite /tmp/report-check.sqlite && .venv/bin/python scripts/eval_conflicts.py --db /tmp/report-check.sqlite --out /tmp/report-check run --parser rule && .venv/bin/python scripts/eval_conflicts.py --db /tmp/report-check.sqlite --out /tmp/report-check report --sheet-a /tmp/report-check/a.csv --sheet-b /tmp/report-check/b.csv --doc /tmp/report-check/conflict-eval.md`
Expected: the doc renders; the primary comparison says `Not run yet`, the gold rules arms show RUNWAY false alarms as
`pending` (nothing is adjudicated), and the ASR rules arms show `n/a` until the `train` ASR run. Delete
`/tmp/report-check*`. Do not commit a results doc: it is written after the operational steps.

- [ ] **Step 6: Commit**

```bash
git add atcdb/eval_report.py scripts/eval_conflicts.py README.md tests/test_eval_report.py
git commit -m "feat: Level 2 results doc and README"
```
End the message with the attribution lines the session provides.

---

## After the plan: operational steps (not tasks; each one is the user's call)

In this order, on the real database, once the plan is merged or on its branch:

1. **ASR for the train split:** `python scripts/run_asr.py --split train` (about 2 h CPU). It must run before injection: synthetic recordings copy their originals' ASR transcripts when they are created.
2. **Inject:** `python scripts/inject_conflicts.py --dry-run`, then without `--dry-run`; then `--sheet data/labels/injection_check.csv`, a person fills `valid`, then `--apply-sheet data/labels/injection_check.csv`.
3. **Run the arms:** `python scripts/eval_conflicts.py run --dry-run` (about $53 for the Claude arms on gold, about the same on ASR, about $2 for the judge, by the estimate), then the free rules arms, then the Claude arms and the judge, one parser at a time.
4. **Adjudicate:** `python scripts/eval_conflicts.py adjudicate`; one person fills sheet A, a second fills sheet B; `adjudicate --kappa`.
5. **Report:** `python scripts/eval_conflicts.py sweep`, then `report`, and commit `docs/results/conflict-eval.md`.
6. **Labelling (independent):** `python scripts/make_event_sheet.py` when the team is ready, then `--check` on the filled sheet. Scoring it is 3b-2.
