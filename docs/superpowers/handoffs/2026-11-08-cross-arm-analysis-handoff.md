# Handoff: the cross-arm replication and the 2026 real cases (2026-11-08)

Read this **after** `2026-11-08-milestone2-submission-handoff.md`, which still governs the submission. That handoff's
"Next step" list is unchanged except where noted at the bottom here. This document covers only the two analyses added
on 2026-11-08 and how to re-run them.

Everything here reads **committed rows**. No database, no API key, no spend — except one optional step, flagged below.

## Suggested skills

- `superpowers:verification-before-completion` before reporting any number from these scripts as final.
- `superpowers:systematic-debugging` if a count here disagrees with `docs/results/conflict-eval.md`; the two are
  derived from the same rows and a disagreement is a bug, not a finding.
- No brainstorming skill is needed: both analyses are built and tested. This is a read-and-interpret task.

## Two new scripts, and what each answers

### 1. `scripts/cross_arm_replication.py` → `docs/results/cross-arm-replication.md`

Sibling of `scripts/divergent_cases.py`. That script prints one arm pair's events for a human to read, which is how
Appendix A's mechanisms were found — on **rules vs Sonnet 5, gold transcripts, only**. This one runs all four
rules-vs-LLM pairs on both transcript kinds and answers three questions:

1. **Invented conflicts per arm.** `parse_error` is the only adjudication verdict the choice of extractor can move.
2. **The contingency** per pair: both / rules only / LLM only / neither, on positives and negatives.
3. **A mechanism label for every divergent positive**, via `classify()`.

```bash
python scripts/cross_arm_replication.py                                              # terminal tables
python scripts/cross_arm_replication.py --markdown > docs/results/cross-arm-replication.md
```

**Where the results go in the report:** §4.3 (the replication table and the two corrections), and the §7 limitation
about the contingency covering one arm pair, which this closes. The committed results doc holds per-recording tables
for every divergent positive and negative, which is what to read before writing about any individual case.

**How `classify()` works, because the report cites its counts.** Both mechanisms turn on `engine.apply` capping a
conflict at `warning` when *either* party's callsign is unknown. The labels:

| Label | Meaning |
|---|---|
| `identity_holder` | the arms differ on whether an aircraft **holding** the runway is named — needs identity carried across transmissions, which is what `window` context supplies |
| `identity_trigger` | they differ on the callsign of the **conflicting clearance itself** — needs no memory of earlier transmissions |
| `supersession` | the arm that missed gave one aircraft two kinds of hold, so the later invented one rewrote the earlier and the matrix rated the pair lower |
| `unclassified` | none of the above; counted rather than explained away |

Appendix A named two mechanisms by hand. The classifier splits the first in two: an unresolved callsign on the prior
holder and one on the trigger have the same engine consequence but different causes, and the split is what the §4.3
claim about context depends on. It currently labels all 25 divergent positives with none unclassified.

**Two things a reader should not get wrong:**

- The mechanism is **identity resolution, not model class.** On recording 3291 the rules parser resolves a
  bare-numeric callsign that Haiku 5.5 drops. The earlier draft claimed callsign resolution is something "only the
  windowed LLM does"; that was corrected.
- Runway state comes from **folding the stored events through `engine.apply`** (`holders()`), not from scanning the
  event list. A hold-short for the same runway, a `VACATED`, a go-around, or a handoff to ground/departure all
  release a reservation, and reservations can go stale. An earlier version read the event list and happened to agree
  on all 50 lookups in this data; it would have drifted on data where a release occurs before the trigger. Do not
  re-introduce a second implementation of engine state.

### 2. `scripts/real_2026_cases.py`

Sibling of `scripts/pilot_cases.py`. Replays the two 2026 reconstructions (Goa 2026-04-03, Houston 2026-04-24) from
`data/labels/real_2026_cases_A.csv` — 7 transmissions, `normalized_text` already filled, `events` column still empty.

```bash
python scripts/real_2026_cases.py                                    # every recorded arm: free, no key
python scripts/real_2026_cases.py --dry-run                          # price a re-derivation, free
python scripts/real_2026_cases.py --verify --model claude-sonnet-5   # billed; checks the recording
python scripts/real_2026_cases.py --record --model claude-sonnet-5   # billed; (re)writes the recording
```

**Where the results go in the report:** §4.5, and the §7 next-tests list. The finding is about the **framing**, not
either parser: the engine recognises four reservation kinds (`LAND`, `TAKEOFF`, `LUAW`, `CROSS`) and no transmission
in either case maps to any of them, so no extractor can raise an alert. Goa is a backtrack incursion; Houston is a
callsign-confusion event. Neither is an incompatible pair of runway clearances.

**Reproducibility is deliberately two-sided**, because a recording that is only ever replayed is hardcoded data:

- **keyless** — replays `data/eval/real_2026/` (tracked; `.gitignore` has `!data/eval/`).
- **with a key** — `--verify` re-derives from the API and checks the recording, exiting non-zero on failure.

`--verify` is **not byte-equality**, and this is load-bearing: §2 of the report retracts Milestone 1's temperature-0
determinism claim, so identical prompts need not give identical replies and a strict diff would be unsound by the
report's own argument. It separates:

- the **invariant** the report cites — no arm produces a runway reservation. A breach **fails** the check.
- **drift** — any other per-row difference. Reported per case and row, **not** a failure; re-record so the committed
  file matches what the API now returns.

## The one step still needing a key

`data/eval/real_2026/events-claude-sonnet-5.json` **does not exist yet.** Sonnet 5 was run manually on these rows and
produced no reservation, but that output was transcribed through a chat session, so it was deliberately *not* written
to disk by hand — a file claiming to be a machine recording has to be machine-written.

One command creates it (`--dry-run` priced it at about **$0.02**, 7 uncached parses):

```bash
read -rsp "Anthropic API key: " ANTHROPIC_API_KEY && export ANTHROPIC_API_KEY && .venv/bin/python scripts/real_2026_cases.py --record --model claude-sonnet-5
```

After that, `test_the_committed_sonnet_recording_also_yields_no_reservation` stops skipping and starts guarding the
§4.5 claim. Until then the §4.5 table's Sonnet column is sourced from a manual run and is **not** reproducible — do
not present it as reproducible before this step is done.

Do **not** run the LLM context sweep (about 4,000 calls, ~$6.88 per arm). The prior handoff's recommendation to defer
it to the Week 13 presentation stands.

## Refactor that touched existing files

`load`, `caught` and `false_alarms` were byte-identical in `divergent_cases.py` and the new script. `atcdb/evaluate.py`
states in its own header that everything below `read_rows` is pure, and scripts import from it, so the predicates were
promoted there: **`caught`, `false_alarms`, `scored`** now live in `atcdb/evaluate.py` with 5 tests in
`tests/test_evaluate.py`. Both scripts import them.

This caught a real bug introduced during the move: `detection` was dropped from `divergent_cases.py`'s imports while
line 60 still calls it. Output baselines for `divergent_cases.py` (3 arm pairs), `cross_arm_replication.py` and
`risk_score.py` were captured before the refactor and verified identical after — **re-capture baselines the same way
before touching these scripts again.**

## Verification state

- **385 tests pass.** The 2 failures in `tests/test_asr.py` are pre-existing and need a GPU module this Mac lacks.
- Use `.venv/bin/python`, not the system/anaconda python — the latter is missing `jiwer` and fails collection.
- `python scripts/eval_conflicts.py report` still regenerates `docs/results/conflict-eval.md` **byte-identically**;
  if it ever prints `recall: n/a over 0 positives`, the database has lost its injections — do not commit that.
- `docs/results/cross-arm-replication.md` is byte-identical across the whole refactor apart from its heading date.

## What this changes in the submission handoff

- Its §7 limitation "the contingency analysis covers rules-vs-Sonnet-gold only, not Haiku or ASR" is **closed**; the
  replacement limitation (the classifier is automatic, hand-validated on one pair) is already written into §7.
- Its "ASR paired difference CI is not yet computed" line was **stale** and is removed.
- Its item 1 (§6, the societal/philosophical analysis) is **explicitly parked by the team** — do not pick a thread.
- Its items 2 (contribution statement), 3 (trim — the team is doing this themselves), 4 (Figures 1 and 5) and
  5 (references) are **still open**. On references: all 9 existing entries were verified against the PDFs in
  `docs/references/` and are correct; what is missing is the data and standards layer — ATCO2 (its corpus paper is
  on disk), UWB-ATCC, the Whisper model, ICAO Doc 4444, NTSB DCA23FA149, and the two avherald URLs in the
  `source_citation` column of the 2026 sheets.
- The hybrid extractor from its open decision 1 is **still unreproducible**: the scratchpad script is not in the
  working tree, not in git, and not in any ignored path. Its 94% / 4.5 numbers cannot be cited until it is rebuilt.
