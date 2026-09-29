# Handoff: ATC conflict engine (2026-09-29)

Read this first in a new session. It supersedes `2026-09-26-conflict-engine-handoff.md`; everything in that file's
"Settled decisions" still holds and is repeated below.

## Where things stand

| Piece | State |
|---|---|
| Spec | `docs/superpowers/specs/2026-09-12-conflict-engine-design.md`. The **Addendum, phase-3 design pass** is the source of truth and wins over the text above it. A.4 gained one sentence in 3a (window-mode parse failures, below) |
| Phase 1, engine core | Merged, PR #1 |
| Phase 2, replay UI | Merged, PR #2 |
| Phase 2.5, engine tuning | **PR #3 open** against `main` (branch `phase-2.5-engine-tuning`). Also carries the phase-3 design docs |
| Phase 3a, Claude parser | **PR #4 open**, stacked on #3 (branch `phase-3a-claude-parser`, base `phase-2.5-engine-tuning`) |
| Phase 3b, evaluation | Commitments recorded (spec A.5); **needs its own design pass before a plan**. This is the next step |
| Phase 4, case studies | Sources settled (spec A.6) |

Integration is the user's call. Merge #3 first; when its branch is deleted GitHub retargets #4 to `main`. Most commits
on both PRs carry a "Co-Authored-By: Claude Sonnet 5" trailer (the implementing subagents'); the user has not yet said
whether to reword them (that would rewrite pushed commits).

## Run it

```bash
source .venv/bin/activate                      # Python 3.14; anthropic==1.8.0 is now a requirement
python -m pytest -q                            # 215 with ANTHROPIC_API_KEY set; 214 + 1 skipped without
uvicorn atcdb.api:app --reload --port 8011     # 8000 and 8010 are usually taken by other servers
python scripts/show_replay.py 528 --parser llm --model claude-sonnet-5
python scripts/parse_events.py --parser llm --model claude-sonnet-5 --dry-run   # always dry-run before a paid run
```

`ANTHROPIC_API_KEY` is exported from `~/.zshenv` (the user added it on 2026-09-27). The live smoke test in
`tests/test_parse_llm.py` makes one tiny Haiku call whenever the key is set.

## What phase 3a delivered

- `atcdb/parse_llm.py`: parser name **`llm`** (the `events` table's CHECK allows only `rule` and `llm`). One strict,
  forced `report_events` tool per transmission. Haiku 4.5 at temperature 0 via `extra_body` (anthropic 1.x removed the
  `temperature` argument); Sonnet 5 with thinking disabled and effort `low`. `parse_llm.VERSION = "p1"`; bump it when
  SYSTEM, TOOL, `render_prompt`, `to_events` or the request settings change, then re-run
  `scripts/record_llm_fixtures.py` (costs cents) and update the pinned expectations.
- Registry in `atcdb/replay.py`: `PARSERS` (name to factory taking a model), `PARSER_MODELS` (first is the default),
  `PARSER_VERSIONS`, `PARSER_AVAILABILITY`. The client is created only on a cache miss, so cached replays need no SDK
  and no key.
- **Cache key:** `window` rows are stored under `<version>+engine<ENGINE_VERSION>` (`engine.ENGINE_VERSION = "1"`);
  bump it whenever engine rules change. `none`/`role` rows keep the plain version. Old rules `window` rows stored as
  `v1` are inert.
- **Dropped events:** anything Claude reports that cannot be placed becomes an `UNRESOLVED` row; the engine counts it
  in `State.ignored`, so `Step.dropped` includes it on cache hits.
- **Window-mode failures (found in final review, now in spec A.4):** after a parse error in a `window` replay, later
  transmissions are served from the cache only; a miss is marked `skipped: ...` and nothing is parsed or stored, so no
  parse is ever cached against incomplete engine state.
- `parse_events.py --model --recording --dry-run`; `--refresh` refuses `--recording` (it clears every recording).
- Page: parser-model choice (unavailable ones disabled with the reason), request token, dropped chip, basis tooltip.
- The 3a plan (`docs/superpowers/plans/2026-09-27-claude-parser.md`) was proven by rebuilding from its text,
  byte-identical, before execution.

## Measured so far (report material; one recording and six fixtures, not results)

- **Cost:** Sonnet over all 2,016 replayable tower transmissions in `window` context is about $7.15 by the dry-run
  estimate; Haiku about $3.58. Recording 528 cost about $0.15 for both models and took 41 s (Haiku) and 68 s (Sonnet).
- **Recorded fixtures (Austin NTSB text):** both models parse the 0634:14 landing clearance that the rules parser
  drops, and the US callsigns. On the pilot's takeoff readback, Haiku reports a new TAKEOFF for "one seven zero" (the
  heading) and Sonnet reports a READBACK but misses the callsign. Pinned as findings; the prompt was not tuned.
- **Recording 528 (cached for both models):** Sonnet reproduces the known false RUNWAY alert at step 17, as the spec
  predicted. Haiku avoids it only because it invents a `RunwayVacated` for Air France at step 15: the right output for
  the wrong reason. Both LLMs raise a READBACK alert at step 13 (the pilot's crossing readback omits runway 13), which
  the rules parser misses because it took "delta" as the callsign. Haiku also misreads a controller's "vacate to the
  left" as a vacated report and a controller "roger standby" as a READBACK.
- The report figure `~/Downloads/parser-comparison-table.html` still has a *predicted* LLM column; it can now be
  replaced with the measured Austin and recording-528 behaviour above.

## Settled decisions (do not re-open)

- Approach A, runways only, cache semantics, API error codes (earlier handoffs).
- Build order 2.5 → 3a → 3b → 4.
- **Rules parser frozen at `parse_rules` v1** as the pre-registered baseline; its `runway`-token, US-callsign and
  elliptical-handoff gaps are findings. Only `normalize_runway` was fixed.
- `ENGINE_VERSION` in the cache key (done in 3a, as the `window`-row suffix).
- LLM arms: Haiku 4.5 at temperature 0 vs Sonnet 5 with thinking disabled and effort `low`; reproducibility from the
  cache and the strict tool schema.
- Capabilities carry `available` and `reason`; the UI disables unavailable parsers (even when a replay is cached).
- A hold-short of a different runway releases nothing, so recording 528 stays a false alert on purpose.
- Staleness: LAND ≥ 284 s (Austin). CROSS and LUAW values are chosen in 3b against the false-alarm metric.
- Case studies from NTSB dockets; only FA/MA investigations have verbatim transcripts.
- Framing: the engine detects incompatible clearances, a proxy for loss of separation, not ICAO compliance.
- UWB-ATCC text is CC BY-NC-ND and never committed (fixtures use NTSB or invented text).

## Open risks and carry-overs for 3b

- **Labelling is still 0/250.** Level 1 needs about 250 hand-labelled transmissions (200 plus a 50-row overlap for
  kappa). It blocks 3b's first metric; raise it at the start of the 3b design pass.
- The Haiku readback-as-clearance error creates phantom reservations in `window` replays; 3b should measure it
  (false alarms per hour), not patch it. Any prompt change bumps `parse_llm.VERSION`.
- `count_unresolved` (rules drops) is a lower bound: it counts instruction kinds, not instances.
- Deferred small items: a cached llm replay cannot be opened from the page without a key (spec mandates the disabled
  option); leaving and re-opening a cold llm replay starts a second concurrent parse; the live smoke test runs by
  default whenever a key is set; `none`/`role` parallel parsing belongs to 3b's evaluation script.
- Left for the 3b design pass (spec A.5): ASRS triage and reconstruction, Risk-weight derivation, labelling logistics,
  the LLM-judge ablation, CROSS/LUAW staleness tuning on a held-out split.

## How this user likes to work

- Brainstorm → approved design → spec → plan → subagent-driven development with **Sonnet** implementers and
  reviewers, **Opus** for the final whole-branch review, one fix wave after it.
- Plans are proven before commit: build in the scratchpad, then rebuild from the plan text and compare
  (`apply_plan.py`-style script: applies each replace/append/create, checks each RED/GREEN step and pass count).
- Integration (merge / push / PR) is always the user's call; stacked PRs are fine.
- Prefers short, plain answers; no em dashes in material for the report.
- `.superpowers/` (SDD ledgers) is git-ignored and deleted when a plan finishes.
- Load the `claude-api` skill before touching Anthropic API code.
