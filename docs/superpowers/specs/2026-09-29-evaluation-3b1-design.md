# Phase 3b-1: Level 2 synthetic evaluation and LLM judge, design

**Status: design approved 2026-09-29; spec awaiting review.** Amends `2026-09-12-conflict-engine-design.md`
(Section 4 and Addendum A.5). Where this file and A.5 disagree, this file wins for the parts it covers.

## 1. Decomposition of 3b

Labelling will come from the team, but not for weeks, so 3b is split and ordered to avoid waiting on it.

| Sub-project | Content | Needs event labels |
|---|---|---|
| **3b-1 (this spec)** | ASR over the replayable recordings, conflict injection, arm runner and scoring, alert adjudication, LLM judge, staleness sweep, results doc. Also the event labelling sheet generator, so labelling can start whenever the team is ready | No (only a yes/no check per injection and alert adjudication) |
| 3b-2 | Level 1 extraction: `eval_parsers.py`, Risk weights, κ on the event sheet | Yes |
| 3b-3 | Level 2 real positives: ASRS triage and reconstruction, NTSB events. Reuses 3b-1's runner and scoring unchanged | No |

**Arms.** Extractor (rule, Haiku 4.5, Sonnet 5) × context (`none`, `role`, `window`) × transcript (human, ASR) = 18
structured arms, plus the Sonnet judge on each transcript kind. **Primary comparison** (pre-registered, A.5): rule vs
Sonnet, `window`, human transcripts.

**Cost.** About $130 for all 18 arms over the 309 negatives (A.4's $66 for gold, doubled for ASR), plus about $15 for
the injected positives and the judge. Every paid run is dry-run first.

## 2. Findings that shaped this design

- **Staleness cannot be tuned on this corpus.** The longest replayable recording spans 139 s; a timeout only acts on
  sequences longer than itself, so every value from 139 s to 300 s gives identical output on all 309 recordings.
  CROSS and LUAW stay at 300 s. A sensitivity sweep is reported as a finding; nothing is chosen from it, so no
  held-out split is needed. This replaces A.3.6's and A.5's "tuned on a held-out split".
- **ASR coverage and leakage.** ASR transcripts existed only for the jacktol `test` split. That split is per clip,
  not per recording: of the 2,016 transmissions in the 309 recordings, 405 are `test` and 1,611 are `train` (almost
  certainly seen when the Whisper model was fine-tuned). Only 12 recordings are entirely `test` (about 0.23 h).
- **Audio hours.** The 309 recordings span 2.65 h (first transmission start to last end, summed); speech is 1.73 h.

## 3. ASR over the replayable recordings

`python scripts/run_asr.py --split train` transcribes the missing clips (about 2 h CPU). No code change; it is an
operational step documented in the plan, run after the plan's tasks.

- **Level 2 ASR headline:** the 12 fully-`test` recordings, with its (wide) CIs stated.
- **Level 2 ASR secondary:** all 309, reported with the share of probably-leaked transmissions (80%); the ASR
  degradation it shows is a lower bound.
- **Level 1:** the event sheet samples only `test`-split transmissions (section 8), so its ASR factor is clean.

## 4. Conflict injection (`atcdb/inject.py`, `scripts/inject_conflicts.py`)

**Candidate scan, independent of every parser.** On each replayable recording's `human` gold text, find *anchors*:
controller transmissions with a clearance verb (`cleared to land`, `cleared for takeoff`, `line up and wait`,
`cross`) near a runway designator that `normalize_runway` accepts. Also find hold-shorts (`hold short (runway) X`)
and releases (`contact ground`, `contact departure`, `runway vacated`, `vacated`). The regexes live in `inject.py`,
not in `parse_rules` (which stays frozen at v1), and are deliberately broader than it: no `runway` token required,
single-digit designators accepted.

**Edit kinds.** Each takes an earlier anchor A (a reservation of kind K on runway R) and a later transmission B,
and edits B's text only (or, for kind 4, deletes one transmission):

1. **`runway_swap`**: B is a clearance to a runway other than R; its runway designator becomes R (spoken form, e.g.
   `one three`).
2. **`holdshort_to_cross`**: B is `hold short (runway) X`; it becomes `cross runway R`.
3. **`verb_upgrade`**: A is a landing clearance on R and B is `line up and wait R` or a landing clearance on R; B's
   verb becomes `cleared for takeoff`.
4. **`release_delete`**: a release transmission lies between A and a later clearance C on R whose kind is
   incompatible with K; the release is removed from the synthetic copy, and C plays the role of B.

One edit per synthetic recording. The generator targets `--n 100`, stratified across kinds as far as candidates
allow (kind 4 will be rare; its count is reported). `--seed` fixes every choice. A recording with no candidate for a
kind yields no injection of that kind.

**Storage.** Source `synthetic-conflicts` (`kind='corpus'`), one new recording per injection, with `airport_icao`
and `facility` copied from the original. `recordings.notes` holds JSON:
`{"original_recording_id", "edit_kind", "anchor_tx", "trigger_tx", "runway", "seed", "before", "after"}`, where the
transmission ids are the synthetic copy's. Transmissions are copied with the same `start_s`, `end_s`, role and
`clip_path`, and `pcm_sha1` NULL. Gold transcripts are `kind='gold', model='synthetic'`; only B differs from the
original's `human` text. 3a's per-recording transcript pinning already replays these.

**ASR for synthetic recordings.** Unedited transmissions copy the original's Whisper transcript row (same model and
version). B's audio does not contain the edit, so B's ASR row holds B's edited gold text, same model, with
`model_version='synthetic'`. The ASR arm thus measures whether ASR noise on the real half of the conflict hides it.
The report states this.

**Human check.** `inject_conflicts.py --sheet data/labels/injection_check.csv` writes one row per injection: the
recording's lines around A and B (A and B marked), B before and after, and empty `valid` and `notes` columns. `valid`
is `yes` when B is addressed to a different aircraft from A, A is not released before B, and the phraseology is
plausible; otherwise `no`. `inject_conflicts.py --apply-sheet` reads it back. Only `valid=yes` injections form the
positive set; rejection rates per kind are reported as the generator's precision. Re-running the generator with the
same seed is idempotent (existing synthetic recordings are matched by `external_id = "<original>-<kind>-<seed>-<n>"`).

## 5. Runner and scoring (`atcdb/evaluate.py`, `scripts/eval_conflicts.py`)

**Sets.** `negatives`: the 309 replayable real tower recordings (`list_recordings`). `positives`: synthetic
recordings with `valid=yes`.

**Runner.** For each arm and recording, call `build_timeline` and keep the conflicts. Parses use the `events` cache,
so re-runs are free. `none` and `role` recordings run on a small thread pool; `window` runs sequentially within a
recording and in parallel across recordings. `--dry-run` prints uncached calls and estimated cost per arm (via
`uncached_parses`). A `window` replay that hits a parse failure is marked `incomplete`, excluded from that arm's
denominators, and counted in the report.

**Output.** One JSONL per arm at `data/eval/conflicts/<extractor>-<model>-<context>-<transcript>.jsonl` (git-ignored
with the rest of `data/`). Row: `recording_id`, `set`, `span_s`, `incomplete`, `dropped`, and `conflicts` (type,
severity, runway, callsigns, trigger transmission id, step index). Scoring reads only these files and the
adjudication sheets, so it is pure.

**Positives.** Hit = a `RUNWAY` conflict of severity `alert` on runway R triggered by the trigger transmission
(**strict**) or by it or any later transmission (**lenient**, which catches Austin-style late firing at a
re-confirmation). A `warning` on R that meets the same timing is counted separately as partial detection. Recall per
arm and per edit kind.

**Negatives.** Every alert is a candidate false alarm until adjudicated (section 6). Rate = adjudicated false alarms
÷ hours of recording span. `RUNWAY` and `READBACK` reported separately; `RUNWAY` is the headline. Any unadjudicated
alert makes the arm's rate "pending", never a number.

**CIs.** Percentile bootstrap, 2,000 resamples, fixed seed: recordings resampled for false-alarm rates, injections
for recall. For the primary comparison, a paired bootstrap of the rule-minus-Sonnet difference over the same
resamples.

## 6. Adjudication

`eval_conflicts.py --adjudication-sheet` pools alerts on negatives from all 18 arms and the judge, deduplicated on
`(recording, type, runway, trigger transmission)` (callsigns are not in the key, since the rules parser often
extracts `''`). Each row shows the transcript window up to the trigger, the arms that raised it and the callsigns
each reported, and an empty `verdict`:

- `genuine`: a truly incompatible pair of clearances.
- `parse_error`: extraction was wrong.
- `missing_info`: extraction right, the release was never spoken (the recording 528 type).
- `engine_rule`: extraction right, the matrix is too strict.

Sheet A has every row; sheet B is a seeded 30% sample for a second person. Cohen's κ on the overlap. Non-`genuine`
verdicts are false alarms; the four verdicts are the failure taxonomy. Re-generating the sheet keeps existing
verdicts (rows matched on the dedup key) and appends new alerts.

## 7. LLM judge (`atcdb/judge.py`)

Sonnet 5, same settings as the parser arm (thinking disabled, effort `low`), one call per recording, strict forced
tool `report_conflicts`: an array of `{type: RUNWAY|READBACK, runway, callsigns, trigger_index}`. Input: numbered
transcript lines with speaker roles; the system prompt describes incompatible clearances as the engine's matrix
does, without the matrix itself. `judge.VERSION = "j1"`, bumped by hand like `parse_llm.VERSION`.

Cached in a new `judgments` table keyed by `(recording_id, transcript_kind, transcript_model, judge_model,
judge_version)`, with a `conflicts_json` column; an empty list is stored and cached. API errors and refusals
propagate and cache nothing. Reported conflicts with an out-of-range `trigger_index` or an unresolvable runway are
dropped and counted. Scored with the same hit rule (the trigger index maps to a transmission) and pooled into
adjudication. Runs on both transcript kinds.

## 8. Event labelling sheet (`scripts/make_event_sheet.py`)

Samples 200 transmissions uniformly (seeded) from the `test`-split transmissions of the 309 replayable recordings,
independent of every parser. Writes `data/labels/event_sheet_A.csv` (200 rows) and `event_sheet_B.csv` (the first 50,
for κ). Columns: `row_id`, `transmission_id`, `recording_id`, `role`, `context` (previous 4 lines with roles), `text`,
`clip_path`, `events`, `notes`. The labeller writes `events` as one event per line: `<kind> <callsign> <runway>` for
runway instructions, `vacated <callsign>`, `go_around <callsign>`, `handoff <callsign> <to>`, `readback <callsign>`, or
`noop`. No parser output appears on the sheet. A `parse_event_cell` function validates the syntax (kinds, handoff
targets, runways through `normalize_runway`) so bad cells are found when the sheet is read, not at scoring time.
Scoring is 3b-2.

## 9. Staleness sweep

`eval_conflicts.py --sweep-stale` re-folds each arm's cached events with CROSS and LUAW at 30, 60, 90, 120 and 300 s,
making no new parses, and reports recall and raw alert counts per value. `window` arms keep the context they were
parsed with at 300 s; the report says so. `STALE_S` is not changed.

## 10. Results doc

`eval_conflicts.py --report` writes `docs/results/conflict-eval.md`, in the style of the existing results docs: the
primary comparison first, then per-arm tables (recall strict and lenient, partial detections, false alarms per hour,
CIs), the failure taxonomy, κ for adjudication, injection precision per kind, the ASR headline and secondary with the
leakage caveat, the incomplete counts, the judge column and the sweep. No em dashes.

## 11. Testing

- `inject.py`: hand-built sequences for each edit kind; seeding and stratification; no candidate means no injection;
  the synthetic copy is identical to the original except B (or the deleted release); idempotent re-run.
- `evaluate.py`: pure scoring over hand-written JSONL rows (strict and lenient hits, warnings, `incomplete`
  exclusion, "pending" when unadjudicated, the per-hour denominator, bootstrap on toy data with a fixed seed, paired
  difference).
- Runner: fake parsers, as in the existing replay tests.
- `judge.py`: injected fake client (the `parse_llm` pattern), one recorded Sonnet fixture on invented text (never
  UWB-ATCC text), one live smoke test that skips without a key.
- `make_event_sheet.py`: sampling only from `test` transmissions, no parser output in columns, `parse_event_cell`
  accept and reject cases.
- Real-corpus checks (injection on recording 528) skip when `data/atc.sqlite` is absent.

## 12. Build order

One plan; each step leaves the repo tested and runnable.

1. Event sheet generator and `parse_event_cell`, so labelling can start.
2. `inject.py` and `inject_conflicts.py` with the check sheet.
3. Runner and scoring.
4. Adjudication sheet and κ.
5. Judge and the `judgments` table.
6. Staleness sweep.
7. Report writer.

Operational steps after the plan (not plan tasks): ASR on the `train` split, the injection check, dry-runs then paid
runs, adjudication, the report.
