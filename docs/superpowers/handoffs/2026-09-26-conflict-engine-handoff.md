# Handoff — ATC conflict engine (2026-09-26)

Read this first in a new session. It supersedes `2026-09-18-conflict-engine-handoff.md`.

## Where things stand

| Piece | State |
|---|---|
| Spec | `docs/superpowers/specs/2026-09-12-conflict-engine-design.md`. The **Addendum — phase-3 design pass** (approved 2026-09-26) is the source of truth and wins over the text above it |
| Phase 1, engine core | Merged, PR #1 |
| Phase 2, replay UI | Merged, PR #2 (2026-09-18) |
| **Phase 2.5, engine tuning** | **Plan written and verified, not executed.** `docs/superpowers/plans/2026-09-26-engine-tuning.md` |
| Phase 3a, Claude parser | Designed (spec A.4), no plan |
| Phase 3b, evaluation | Commitments recorded (spec A.5); needs its own design pass |
| Phase 4, case studies | Sources settled (spec A.6) |

Git: branch **`phase-3-design`** (local, not pushed) holds three commits on top of `main`: the spec addendum, the
review decisions, the phase-2.5 plan. Integration is the user's call; ask before pushing or opening a PR.

**Next step:** execute the phase-2.5 plan. Ask the user subagent-driven (their usual) or inline. Execute on
`phase-3-design` or a branch off it.

## Run it

```bash
source .venv/bin/activate                      # Python 3.14
python -m pytest -q                            # 155 tests today; 181 after phase 2.5
uvicorn atcdb.api:app --reload --port 8010     # port 8000 is usually taken
python scripts/show_replay.py uwb-atcc_TWR-DM7AI0
```

## About the phase-2.5 plan

- Eight tasks, one per spec item A.3.1–A.3.9. Pass counts per task: 160, 162, 166, 169, 174, 178, 181, 181.
- Verified: prototyped in a scratch copy, then the repo was rebuilt from the plan text alone by a script that applies
  each edit and checks each red/green step and commit. 0 problems; byte-identical to the prototype.
- Measured on the corpus: rules-parser events unchanged in all three context modes (2,035 events), conflicts stay at
  85, one conflict changes (recording 1970's READBACK alert now names runway 13). **No events-cache refresh needed.**
- Task 5's `count_unresolved` sits beside `parse_rules.parse` rather than inside it, because the rules parser is frozen.
- Task 7's Austin fixture was generated from the NTSB PDF's text layer (`pdftotext -raw`), not retyped.

## Settled decisions — do not re-open

Everything in the earlier handoff still holds (Approach A, runways only, cache semantics, API error codes). Added
2026-09-19 and 2026-09-26, all recorded in the spec addendum:

- Build order 2.5 → 3a → 3b → 4.
- **Rules parser frozen at `parse_rules` v1** as the pre-registered baseline. Its `runway`-token, US-callsign and
  elliptical-handoff gaps are findings, not bugs. Only `normalize_runway` (shared by every extractor) is fixed.
- A hand-bumped **`ENGINE_VERSION` joins the events cache key in 3a**, before the first LLM parse is cached.
- LLM arms: Haiku 4.5 at temperature 0 vs Sonnet 5 with thinking disabled and `effort: "low"`. Sonnet 5 rejects
  `temperature`; reproducibility comes from the cache and a `strict: true` tool schema.
- Capabilities entries carry `available` and `reason`; the UI disables unavailable parsers.
- A hold-short of a *different* runway releases nothing, so recording 528 stays a false alert on purpose.
- Staleness: LAND ≥ 284 s (Austin). CROSS and LUAW values are chosen in 3b against the false-alarm metric.
- Case studies come from NTSB dockets (LiveATC keeps 30 days). Only major (FA/MA) investigations have verbatim ATC
  transcripts.
- Framing: the engine detects incompatible clearances, a proxy for loss of separation, not ICAO compliance.

## Open risk

Phase 3b's Level 1 needs about 250 hand-labelled transmissions (200 plus a 50-row overlap), and the readback sheets
are still 0/250. Labelling can run in parallel with 2.5 and 3a. Raise it with the user if it has not started.

## Report assets (outside the repo)

The user's written report exists separately. Figures made for it live in `~/Downloads`:
`parser-comparison-table.html` (Austin vs recording 528, rules actual vs LLM predicted) and
`investigation-diagram.svg` / `.png` (pipeline with the two test levels). Copy HTML to the clipboard for Google Docs
with `osascript -e 'set the clipboard to (read (POSIX file "<path>") as «class HTML»)'`. The LLM column is a stated
prediction; replace it with measured output once 3a runs.

## How this user likes to work

- Brainstorm → approved design → spec → plan → subagent-driven development with **Sonnet** implementers and
  reviewers, **Opus** for the final whole-branch review, one fix wave after it.
- Plans are proven before commit: build the code in the scratchpad, then rebuild from the plan text and compare.
- Integration (merge / push / PR) is always the user's call.
- Prefers short, plain answers; no em dashes in material for the report.
- `.superpowers/` (SDD ledgers) is git-ignored and deleted when a plan finishes.
