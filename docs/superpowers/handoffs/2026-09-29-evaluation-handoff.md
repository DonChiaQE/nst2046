# Handoff: after phase 3b-1 (2026-09-29, evening)

Read this first in a new session. It supersedes `2026-09-29-conflict-engine-handoff.md`; that file's "Settled decisions"
still hold and are repeated below.

## Where things stand

| Piece | State |
|---|---|
| Phases 1, 2, 2.5, 3a, 3b-1 | **All on `main`** (`abf53ee`, PR #6). 293 tests (291 + 2 skipped without a key) |
| Phase 3b-1 spec | `docs/superpowers/specs/2026-09-29-evaluation-3b1-design.md` (amends Section 4 and A.5 of the engine spec) |
| Phase 3b-1 plan | `docs/superpowers/plans/2026-09-29-evaluation-3b1.md`; its last section lists the operational steps |
| Level 2 evaluation | **Code done, nothing run on the real data yet.** This is the next step |
| 3b-2 (Level 1 extraction) | Needs labels (0/250) and its own design pass |
| 3b-3 (ASRS, NTSB positives) | Needs its own design pass |
| Phase 4 (case studies) | Sources settled (engine spec A.6) |

PRs #3, #4 and #5 were merged within seconds of each other, so #4 and #5 landed in their stacked bases instead of
`main`; PR #6 brought everything onto `main`. The old branches (`conflict-engine-core`, `replay-ui`,
`phase-2.5-engine-tuning`, `phase-3-design`, `phase-3a-claude-parser`, `phase-3b1-evaluation`) are fully merged and can
be deleted when the user says so. Several pushed commits carry a "Co-Authored-By: Claude Sonnet 5" trailer; rewording
them now would rewrite `main`, so leave them unless the user asks.

## Run it

```bash
source .venv/bin/activate
python -m pytest -q
uvicorn atcdb.api:app --reload --port 8011
python scripts/eval_conflicts.py --help        # run | adjudicate | sweep | report
```

`ANTHROPIC_API_KEY` is exported from `~/.zshenv`.

## What 3b-1 built (on `main`)

- `atcdb/inject.py`, `scripts/inject_conflicts.py`: synthetic positives. Four text edits find only about 10
  candidates (few clips hold two clearances), so a fifth kind, `splice`, joins a recording that ends holding a runway
  reservation to another from the same airport that clears a conflicting use of that runway. Seed 0 stores 100 (92
  splices). Stored under the `synthetic-conflicts` source; `replay.real_recordings` keeps them out of the real sets.
  A person marks each `valid` yes/no on `data/labels/injection_check.csv`. The injector refuses to run while the
  originals lack ASR (`--allow-missing-asr` overrides).
- `atcdb/evaluate.py`, `scripts/eval_conflicts.py run`: 18 arms (rules, Haiku, Sonnet x none/role/window x gold/ASR)
  plus two judge arms, JSONL per arm in `data/eval/conflicts/`. A recording with incomplete transcripts of the arm's
  kind is skipped (never parsed, judged or cached). `run --set` merges into the arm's file.
- Scoring: strict and lenient recall; false alarms per hour "pending" until every alert is adjudicated; bootstrap
  and paired-bootstrap CIs; kappa. Primary comparison (pre-registered): rules vs Sonnet, window, gold.
- `eval_conflicts.py adjudicate`: `data/labels/adjudication_A.csv` (all alerts) and `_B.csv` (stable 30% overlap).
  Verdicts: genuine, parse_error, missing_info, engine_rule.
- `atcdb/judge.py`: whole transcript to Sonnet 5, parser-arm settings; `judgments` table checked against a sha1 of the
  sequence.
- `eval_conflicts.py sweep`: CROSS/LUAW staleness sensitivity (a finding; `STALE_S` stays 300 s).
- `eval_conflicts.py report` -> `docs/results/conflict-eval.md`.
- `scripts/make_event_sheet.py`: Level 1 sheet, 200 test-split transmissions + 50 overlap.

## Measured while building (report material)

- Only 34 of the 309 recordings hold two runway clearances; 31 and 13 (one strip) carry almost all traffic, and the
  engine treats them as unrelated runways (a caveat, not changed).
- ASR: the jacktol split is per clip. Of the 309 recordings' 2,016 transmissions, 405 are test split, mixed within
  every recording, so no real recording is entirely test split. The ASR headline is therefore recall-only; a positive
  counts when its trigger transmission is test split (25 of the 100 seed-0 positives).
- Rules arm on gold (corpus copy): 86 of 100 positives strict, 13 warning-only, 1 missed. That is high partly because
  injection sites use the clean phrasing the rules parser handles; the report states this.
- Staleness sweep, rules arms: shortening CROSS/LUAW never removes a negative alert and loses real crossings at 30 s.
- Dry-run cost: about $53 for the Claude arms per transcript kind, about $2 for the judge.

## Next: the operational run (on `data/atc.sqlite`, in this order)

1. `python scripts/run_asr.py --split train --replayable` (about 2 h CPU, free; Ctrl-C pauses, re-run resumes).
   Must precede injection. Without `--replayable` it transcribes the whole train split (12 h or more).
2. `python scripts/inject_conflicts.py --dry-run`, then without it; `--sheet data/labels/injection_check.csv`; a
   person fills `valid`; `--apply-sheet data/labels/injection_check.csv`.
3. `python scripts/eval_conflicts.py run --parser rule` (free); `run --dry-run`; then the Claude arms and the judge,
   one parser at a time (user approves the spend).
4. `adjudicate`; two people fill sheets A and B; `adjudicate --kappa`.
5. `sweep`, `report`; commit `docs/results/conflict-eval.md`.
6. Independently: `python scripts/make_event_sheet.py` when the team can label; then design 3b-2.

## Settled decisions (do not re-open)

- Approach A, runways only, cache semantics, API error codes; build order 2.5 -> 3a -> 3b -> 4.
- Rules parser frozen at `parse_rules` v1 as the pre-registered baseline; only `normalize_runway` was fixed.
- `ENGINE_VERSION` in the window cache key; LLM arms Haiku 4.5 (temperature 0) vs Sonnet 5 (thinking off, effort low).
- A hold-short of a different runway releases nothing (recording 528 stays a false alert on purpose).
- Staleness: LAND >= 284 s (Austin); CROSS/LUAW reported as untunable on this corpus (3b-1 spec section 2).
- 3b split into 3b-1 (done), 3b-2 (Level 1), 3b-3 (ASRS/NTSB); splicing is a positive kind; alerts adjudicated
  pooled across arms; judge is Sonnet 5 only.
- Framing: incompatible clearances, a proxy for loss of separation, not ICAO compliance.
- UWB-ATCC text is CC BY-NC-ND and never goes into tests or fixtures; label sheets live in `data/labels/` like the
  readback sheets (private repo).

## How this user likes to work

- Brainstorm -> approved design -> spec -> plan (proven by rebuilding from its text) -> subagent-driven development
  with Sonnet implementers and reviewers, Opus final review, one fix wave.
- Integration is the user's call. Stacked PRs merged together land in their old bases: check `main` afterwards.
- Short, plain answers; no em dashes in report material. Load `claude-api` before touching Anthropic API code.
