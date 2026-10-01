# Handoff: the Level 2 evaluation run, in progress (2026-10-01)

Read this first in a new session. It supersedes the "Where things stand" and "Next" sections of
`2026-09-29-evaluation-handoff.md`; that file still holds what 3b-1 built, the measured findings, the settled
decisions and how the user likes to work. Read it second.

## Where things stand

| Step (3b-1 plan, final section) | State |
|---|---|
| 1. ASR on the evaluation's train-split clips | **Done** 2026-09-30: 1,611 clips in 4.9 h (about 10 s per clip, slower than the 4.5 s estimate). All 309 replayable recordings now have complete ASR |
| 2. Injection | **Stored**: 100 synthetic recordings under `synthetic-conflicts` (seed 0: 92 splices, 5 holdshort_to_cross, 1 each of the other three). Backup taken just before: `data/atc.sqlite.bak-2026-09-29` |
| 2b. Human check sheet | **Waiting on the user**: `data/labels/injection_check.csv`, 0 of 100 `valid` filled. Then `python scripts/inject_conflicts.py --apply-sheet data/labels/injection_check.csv` |
| 3a. Rules arms | **Run on negatives** (free, 10 s): `run --parser rule --set negatives`. Positives join after the check sheet (`run --parser rule --set positives` merges into the same files) |
| 3b. Claude arms and judge | **Not run; cost decision pending** (below) |
| 4. Adjudication | Not started; wait until the Claude arms have run so each alert is judged once with every arm's view |
| 5. Report | Not started |

Rules arms on the 309 real recordings (2.65 h; distinct alerts, not yet adjudicated):

| Arm | RUNWAY | READBACK |
|---|---:|---:|
| none, gold / ASR | 15 / 17 | 0 / 0 |
| role, gold / ASR | 11 / 12 | 12 / 14 |
| window, gold / ASR | 11 / 12 | 27 / 23 |

READBACK alerts need role or window context (without the role the rules parser never sees a readback).

## Cost decision pending (the user asked for the handoff before deciding)

Dry run on the 309 negatives: Haiku arms $10.42 gold + $10.47 ASR, Sonnet $20.84 + $20.94, total $62.66; judge
$1.96. The 100 positives add about $40, so the full run is about $105 (estimate good to a factor of about two). Why:
about 40,000 calls, and about 95% of each call's input is the same ~940 tokens of system prompt and tool schema.
Options put to the user:
- Stage it: primary comparison first (Sonnet, window, gold, on negatives and positives, about $12) plus the judge
  (about $2 plus positives); ablations only if the report needs them. This was the recommendation.
- Prompt caching of the fixed prefix (check the model's minimum cacheable length first; ~940 tokens may be below it)
  and the Batch API for `none`/`role` (not `window`, which is sequential). Could take the full run to about $40-50.
  Either changes the request settings, so bump `parse_llm.VERSION`; nothing meaningful is cached yet.

## Git

- Local branch `asr-recording-filter` (2 commits, **not pushed**): 0ed7119 the 2026-09-29 handoff, 5dc3f3f
  `run_asr.py --replayable` (ASR only for `real_recordings`; without it `--split train` is all 11,868 train clips,
  12 h or more). 293 tests. Needs a PR or a merge to `main` (user's call); this handoff is committed there too.
- `data/labels/injection_check.csv` is untracked: commit it once it has verdicts (as with the readback sheets).
- `data/eval/conflicts/*.jsonl` and the database are git-ignored.

## Also open

- **Conditional clearances** ("behind the landing airbus, line up runway 31 behind") raise false RUNWAY alerts: events
  have no condition field. The user wants this fixed in a later phase (brainstorm first). Until then, adjudicate those
  alerts as `engine_rule`. About 17 human transcripts match.
- Jennifer needs a copy of `data/atc.sqlite` (13.9 MB before injection, larger now; not on GitHub; UWB-ATCC text, so
  team-only). Send her the copy after injection and the check sheet so it includes the synthetic recordings.
- Level 1 event sheet not generated yet (`python scripts/make_event_sheet.py` when the team can label; A = full 200,
  B = first 50 for the second labeller, kappa on the overlap).
