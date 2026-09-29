# Phase 3b-1: Level 2 synthetic evaluation and LLM judge, design

**Status: design approved 2026-09-29; amended while planning the same day (splicing, section 4; the others are marked
"planning").** Plan: `docs/superpowers/plans/2026-09-29-evaluation-3b1.md`. Amends
`2026-09-12-conflict-engine-design.md` (Section 4 and Addendum A.5). Where this file and A.5 disagree, this file wins
for the parts it covers.

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

**Cost (planning, measured by the dry run).** About $53 for the twelve Claude arms on human transcripts, over the 309
negatives and 100 positives (the positives are new transcripts, so they are parsed afresh), about the same again on
ASR, and about $2 for the judge. Every paid run is dry-run first.

## 2. Findings that shaped this design

- **Staleness cannot be tuned on this corpus.** The longest replayable recording spans 139 s; a timeout only acts on
  sequences longer than itself, so every value from 139 s to 300 s gives identical output on all 309 recordings.
  CROSS and LUAW stay at 300 s. A sensitivity sweep is reported as a finding; nothing is chosen from it, so no
  held-out split is needed. This replaces A.3.6's and A.5's "tuned on a held-out split".
- **ASR coverage and leakage.** ASR transcripts existed only for the jacktol `test` split. That split is per clip,
  not per recording: of the 2,016 transmissions in the 309 recordings, 405 are `test` and 1,611 are `train` (almost
  certainly seen when the Whisper model was fine-tuned). None of the 309 recordings is entirely `test` (every
  recording mixes both splits); an earlier "12 recordings, about 0.23 h" figure named recordings replayable from the
  ASR that existed at the time, not recordings entirely in the `test` split.
- **Audio hours.** The 309 recordings span 2.65 h (first transmission start to last end, summed); speech is 1.73 h.
- **Few clips hold two clearances (planning).** Only 34 of the 309 recordings contain two runway clearances, so the
  four text edits of section 4 find about ten candidates in the whole corpus. Splicing (section 4) supplies the rest.
- **One strip, two designators (planning).** Almost all traffic uses 31 and 13, the two ends of the same runway. The
  engine treats designators as separate runways, so a clearance for 13 and one for 31 never conflict. Reported as a
  caveat, not changed.

## 3. ASR over the replayable recordings

`python scripts/run_asr.py --split train` transcribes the missing clips (about 2 h CPU). No code change; it is an
operational step documented in the plan, run after the plan's tasks.

- **Level 2 ASR headline.** *(follow-up)* No real recording in the corpus is entirely in the ASR model's `test`
  split (the split is per clip, not per recording, and every one of the 309 recordings mixes `test` and `train`), so
  the headline reports recall only; it has no usable negative. The headline filters on a row flag `clean_asr`: a
  negative counts when every transmission is `test` split (`all_test`), which the negatives never satisfy on this
  corpus; a positive counts when its **trigger** transmission is `test` split (the anchor may still be `train`, so a
  splice's earlier clearance can still be leaked audio), which about 4% of positives satisfy. The headline table
  shows the human-transcript arms beside the ASR arms on those same rows, so the ASR recall is measured against a
  matched gold baseline; its text states the leakage share (test-split transmissions over all transmissions, summed
  over one arm's negatives) and how headline positives are chosen. ASR false alarms are reported only in the
  all-recordings table, where the leakage makes the degradation a lower bound. (An earlier version of this bullet
  said "the 12 fully-`test` recordings, with its (wide) CIs stated"; no recording is fully `test`, so that claim was
  wrong. Those 12 were recordings replayable from the ASR that existed when that estimate was made.)
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
and edits B's text only (or, for kind 4, deletes one transmission; kind 5 edits nothing):

1. **`runway_swap`**: B is a clearance to a runway other than R; its runway designator becomes R (spoken form, e.g.
   `one three`).
2. **`holdshort_to_cross`**: B is `hold short (runway) X`; it becomes `cross runway R`.
3. **`verb_upgrade`**: A is a landing clearance on R and B is `line up and wait R` or a landing clearance on R; B's
   verb becomes `cleared for takeoff`.
4. **`release_delete`**: a release transmission lies between A and a later clearance C on R whose kind is
   incompatible with K; the release is removed from the synthetic copy, and C plays the role of B.
5. **`splice`** (planning): recording X ends holding A (no release of A's kind follows it in X) and a different real
   recording Y, from the same airport, contains a clearance B on R that conflicts with A. The synthetic recording is X
   followed by Y, Y's times shifted to start 5 s after X ends; only splices whose B falls within A's staleness timeout
   are kept. Nothing is edited, so every transcript, ASR included, is real. On the corpus copy: 1, 6, 1, 2 and 8,141
   candidates for kinds 1 to 5.

One edit (or splice) per synthetic recording. The generator targets `--n 100`, stratified across kinds by round robin
(a kind that runs out leaves its share to the others), at most one per original recording and kind; splices fill what
the text edits cannot. `--seed` fixes every choice.

**Storage.** Source `synthetic-conflicts` (`kind='corpus'`), one new recording per injection, with `airport_icao` and
`facility` copied from the original. `recordings.notes` holds JSON: `{"original_recording_id", "second_recording_id",
"edit_kind", "anchor_tx", "trigger_tx", "splice_tx", "runway", "seed", "before", "after", "deleted"}`, where the
transmission ids are the synthetic copy's (`second_recording_id` and `splice_tx`, the first transmission from Y, are set
for splices only). Transmissions are copied with the same `start_s`, `end_s`, role and `clip_path`, and `pcm_sha1` NULL.
Gold transcripts are `kind='gold', model='synthetic'`; only B differs from the original's `human` text. 3a's
per-recording transcript pinning already replays these.

**ASR for synthetic recordings.** Unedited transmissions copy the original's Whisper transcript row (same model and
version). B's audio does not contain the edit, so B's ASR row holds B's edited gold text, same model, with
`model_version='synthetic'`. The ASR arm thus measures whether ASR noise on the real half of the conflict hides it.
The report states this.

**Human check.** `inject_conflicts.py --sheet data/labels/injection_check.csv` writes one row per injection: the
recording's lines around A and B (A and B marked), B before and after, and empty `valid` and `notes` columns. `valid` is
`yes` when B is addressed to a different aircraft from A, A is not released or cancelled before B (for `release_delete`,
the deleted transmission was A's own release; for a splice, nothing at the end of X lets A's aircraft off the runway),
and the phraseology is plausible; otherwise `no`. `inject_conflicts.py --apply-sheet` reads it back. Only `valid=yes`
injections form the positive set; rejection rates per kind are reported as the generator's precision. Re-running the
generator with the same seed is idempotent (existing synthetic recordings are matched by `external_id =
"<original>-<kind>-<seed>-<n>"`).

## 5. Runner and scoring (`atcdb/evaluate.py`, `scripts/eval_conflicts.py`)

**Sets.** `negatives`: the 309 replayable real tower recordings (`replay.real_recordings`, planning: `list_recordings`
without the `synthetic-conflicts` source). `positives`: synthetic
recordings with `valid=yes`.

**Runner.** For each arm and recording, call `build_timeline` and keep the conflicts. Parses use the `events` cache,
so re-runs are free. `none` and `role` recordings run on a small thread pool; `window` runs sequentially within a
recording and in parallel across recordings. `--dry-run` prints uncached calls and estimated cost per arm (via
`uncached_parses`). A `window` replay that hits a parse failure is marked `incomplete`, excluded from that arm's
denominators, and counted in the report.

**Driver (planning).** `eval_conflicts.py` has subcommands `run`, `adjudicate`, `sweep` and `report` in place of the
flags named in sections 6, 9 and 10. A row counts only when its replay finished and every transmission with a gold
transcript also has one of the arm's kind (`missing_transcripts == 0`), so a partial ASR run is never scored.

**Output.** One JSONL per arm at `data/eval/conflicts/<extractor>-<model>-<context>-<transcript>.jsonl` (git-ignored
with the rest of `data/`). Row: `recording_id`, `set`, `span_s`, `incomplete`, `dropped`, and `conflicts` (type,
severity, runway, callsigns, trigger transmission id, step index). Scoring reads only these files and the
adjudication sheets, so it is pure. *(final review)* Rows also carry `truth` (a positive's runway, anchor and trigger
transmission ids and kind), `missing_transcripts`, `all_test`, `clean_asr` (section 3), `n_tx` and `n_test` (the
recording's transmissions and those in the `test` split). A recording with missing transcripts is returned unusable
and empty without replaying or judging it, and `--dry-run` skips it, so no cache holds a parse or judgment made from a
partial sequence; each judgment is also stored with the sha1 of the sequence it judged, and one of another sequence is
judged again. `run --set` replaces only that set's rows in an existing JSONL. The report drops positive rows whose
injection is no longer accepted and counts them per arm.

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

Sheet A (`data/labels/adjudication_A.csv`) has every row; sheet B (`adjudication_B.csv`) holds a fixed 30% of keys for a
second person, chosen per key from a seeded hash so the overlap stays the same as more arms add alerts. Cohen's κ on the
overlap. Non-`genuine` verdicts are false alarms; the four verdicts are the failure taxonomy. Re-generating the sheet
keeps existing verdicts (rows matched on the dedup key) and appends new alerts.

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
`clip_path`, `events`, `notes`. The labeller writes `events` as one event per line: `<kind> <runway> <callsign>` for
runway instructions (planning: runway first, since callsigns are several words), `handoff <to> <callsign>`, `vacated
<callsign>`, `go_around <callsign>`, `readback <callsign>`, or `noop`. No parser output appears on the sheet. A
`parse_event_cell` function validates the syntax (kinds, handoff targets, runways through `normalize_runway`) so bad
cells are found when the sheet is read, not at scoring time. Scoring is 3b-2.

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
- `judge.py`: injected fake client (the `parse_llm` pattern), two recorded Sonnet replies to invented sequences (never
  UWB-ATCC text; `scripts/record_judge_fixtures.py` re-records them), one live smoke test that skips without a key.
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
