# Extraction evaluation (Level 2)

Scores any model that reads one ATC transmission and says whether it changes a runway or taxiway's
status, and if so which surface, what kind of change, and for which aircraft. Model-agnostic: the
model writes a predictions CSV; `scripts/eval_extraction.py` scores it against the human gold sheet.

## The task

Input: one transmission's text, plus an adjustable amount of context (see below).
Output: zero or more *extractions*, each

| field | values | meaning |
|---|---|---|
| `change` | True / False | does this transmission change (or explicitly hold) a surface's status? |
| `callsign` | normalized words, e.g. `csa three eight whiskey` | the aircraft the instruction is addressed to — for a block, who now holds the surface; for a clear, who releases it. Always filled when `change=True`; `?` if inaudible |
| `surface_type` | `runway` / `taxiway` / blank | blank for HANDOFF and GO_AROUND, which name no surface |
| `surface` | `13`, `24L`, `B` … | runway designator or taxiway letter; `?` if not named |
| `kind` | see below | the instruction |
| `conditional` | True / False | "behind the landing Airbus, line up and wait" — the clearance is not active until the condition is met |

Several instructions in one transmission ("cross runway 13, hold short of 24") are `;`-separated in
every field, aligned by position: `kind=CROSS;HOLD_SHORT`, `surface=13;24`, `callsign=a;a`.

### Kinds and their effect

| effect | kinds | engine meaning |
|---|---|---|
| **block** | `LAND` `TAKEOFF` `LUAW` `CROSS` | a reservation is added for `callsign` on `surface` |
| **hold** | `HOLD_SHORT` | intent recorded; status unchanged |
| **clear** | `VACATED` `HANDOFF` `GO_AROUND` `CANCEL` | `callsign`'s reservation is released |

`CANCEL` ("cancel takeoff clearance") is new and the engine does not yet have an event for it.
Clears matter as much as blocks: missed releases are what produce stale reservations and false alarms
(recording 528, step 17). Taxiways are **extracted but not tracked** — the engine holds no taxiway
state and raises no taxiway conflicts (that needs airport-map routes and surveillance; Weiß 2013).

Not changes: readbacks, requests, information ("wind two one zero"), altitude/heading/frequency
instructions, greetings.

## Context levels

The sheet carries context columns; the evaluator hands the model only what `--context` allows:

| level | model sees |
|---|---|
| `none` | `text` |
| `role` | + `speaker_role` (pilot / controller) |
| `window` | + `prev_1..prev_4` (previous transmissions as `role: text`), `active_callsigns`, `active_runways` (what the engine was tracking before this transmission, from the rules-parser replay — context, not labels) |

`none` is the honest baseline and Chang et al.'s condition; `window` is what the deployed system has.

## Two scores

1. **Change detection** — over all labelled transmissions: accuracy, precision, recall, F1 of `change`.
   This is the base-rate-sensitive one (Helmke: at 2% prevalence, 85% accuracy ⇒ 88% false alarms).
2. **Content** — over transmissions where gold has `change=True`: per-field accuracy for
   `callsign`, `surface_type`, `surface`, `kind`; exact-match rate (every event, every field, no extras);
   and a weighted aggregate. Weights default to equal; pass `--weights` with the consequence weights
   from `scripts/derive_weights.py` once derived. Gold fields marked `?` are skipped.

Predictions with multiple events are aligned to gold greedily by number of matching fields; an extra
predicted event breaks exact match but does not reduce per-field accuracy. 95% bootstrap CIs over
transmissions on the headline numbers; breakdown by speaker role.

## Files

| file | role |
|---|---|
| `atcdb/extraction.py` | schema, sheet read/write, `events_to_extractions` (engine events → schema), scoring |
| `scripts/eval_extraction.py` | CLI: score a predictions file, or `--parser rule --context …` to generate and score rules-parser predictions |
| `scripts/make_event_sheet.py` | writes the H4 gold sheets from `data/atc.sqlite` (needs the DB) |
| `tests/fixtures/event_sheet_mock.csv` | 12-line mock gold sheet (recording-528-style sequence + edge cases) for running the pipeline without the DB |
| `tests/test_extraction.py`, `tests/test_make_event_sheet.py` | unit tests |

Try it without the DB:

```bash
python scripts/eval_extraction.py tests/fixtures/event_sheet_mock.csv --parser rule --context none
python scripts/eval_extraction.py tests/fixtures/event_sheet_mock.csv --parser rule --context window --save-pred /tmp/pred.csv
```

On the mock sheet the rules parser scores change-accuracy 0.67 (`none`) → 0.83 (`window`); the two
remaining misses are `CANCEL` and a taxiway hold-short, which it has no rule for.

## Instructions for Don: generating the gold sheets

Needs `data/atc.sqlite` with the `events` cache warm (the sheet's `window` columns come from the
rules-parser replay). On the machine with the DB, on branch `jennifer`:

```bash
git fetch && git checkout jennifer
source .venv/bin/activate
python -m pytest -q tests/test_extraction.py tests/test_make_event_sheet.py    # 14 tests
python scripts/parse_events.py                                                # warms the cache if needed
python scripts/make_event_sheet.py --n 200 --overlap 50 --seed 0
```

This writes six files to `data/labels/`: `event_sheet_{none,role,window}_{A,B}.csv`. Same 200
transmissions in the same order in all three; `_B` is the first 50 rows for the second labeller.
Sampling: Tower recordings, stratified 60% controller / 40% pilot, and within each 60% lines that
mention a surface keyword (runway, taxiway, cross, hold short, line up, vacat, go around, cancel) so
positives are guaranteed without any parser choosing. State this keyword stratification in the report.
The console prints the final counts. Commit the six CSVs (`data/labels/` is not git-ignored) and push.

Sanity checks before sending the sheets round: the `window` sheet's `prev_*` columns look like
`controller: …` / `pilot: …`; `active_runways` is non-empty on some rows; no row has a blank `text`.

## Labelling

Label the **window** sheet (the truth needs context; the evaluator can still feed the model `none`).
Fill `change`, and when True: `callsign`, `surface_type`, `surface`, `kind`, `conditional`, per the
table above; `?` for a field you cannot determine; `notes` for anything odd. Definitions and the
agreement procedure are in `docs/labelling-protocol.md` (H4). Then:

```bash
python scripts/score_agreement.py data/labels/event_sheet_window_A.csv data/labels/event_sheet_window_B.csv \
    --key transmission_id --columns change,kind,surface
python scripts/eval_extraction.py data/labels/event_sheet_window_A.csv --parser rule --context none  --report docs/results/extraction-rule-none.md
python scripts/eval_extraction.py data/labels/event_sheet_window_A.csv --parser rule --context window --report docs/results/extraction-rule-window.md
```

For an LLM extractor, write its outputs as a predictions CSV with columns
`transmission_id, change, callsign, surface_type, surface, kind[, conditional]` and run
`python scripts/eval_extraction.py data/labels/event_sheet_window_A.csv predictions.csv`.
