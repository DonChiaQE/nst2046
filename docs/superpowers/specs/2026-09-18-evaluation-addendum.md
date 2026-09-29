# Evaluation addendum — three levels, human gold, consequence weighting

**Status: DRAFT 2026-09-18. Supersedes Section 4 of `2026-09-12-conflict-engine-design.md` where they
disagree.** Open decisions are marked `DECIDE`. Nothing here changes the engine or the parsers; it
changes what we measure, on what, and who checks it.

## Why revise

The course guidelines grade on "baseline, controlled comparison, justified choices" and "analyses
failures, uncertainty and limitations", and require at least one analysed counterexample. Section 4
had the experiments but (a) all its gold except the event sheet came from the rules parser or from
synthetic edits, (b) it had one human touchpoint, (c) it scored every extraction error equally, and
(d) its two case studies were both assumed to be clearance conflicts; one is not. Prior work found
since (see `docs/references.md`): Chang et al. 2026 show LLM extraction errors concentrate on runway
identifiers and that aggregate F1 hides this; Helmke et al. 2022 give a real-audio benchmark of ~80%
recall / ~11% false alarms for rules+ML readback detection.

## Research question (one)

When the component that turns ATC transmissions into structured runway clearances is changed from
rule-based extraction to an LLM (Claude Haiku / Sonnet), and when the context it receives is varied
(none / speaker role / recent-transmission window; gold vs ASR transcripts), how do conflict-detection
recall and false-alarm rate change — and what follows for controller responsibility and automation
bias when such a tool sits between controller and pilot?

**H1:** the LLM extractor is more robust to non-standard phraseology and ASR noise (higher recall,
similar false alarms). **H2:** the LLM extractor produces events that rules never would (hallucinated
clearances), raising false alarms in a setting where false alarms are themselves a hazard.

## Level 1 — Engine

- *Gold:* hand-written event sequences, one per compatibility-matrix cell plus releases, go-around,
  staleness. Exists: `tests/test_engine.py`.
- *Human:* H1 matrix sign-off. Both labellers agree each cell's severity and write the reason into the
  decision log. This makes the matrix a documented policy, not a constant.
- **DECIDED 2026-09-19 (Jennifer): TAKEOFF (new) vs LAND (active) stays `alert`.** Austin 2023 is
  this cell. The clearance was legal under anticipated separation; only distance made it hazardous,
  and a voice-only engine has no distance. Keeping `alert` means routine "cleared for takeoff,
  traffic on final" also fires; those false alarms are *measured* (H5, cause
  `anticipated_separation`) and reported as a finding, not tuned away. Parsing distance callouts
  ("three-mile final") as a suppressing event is the named next test.
- **DECIDED 2026-09-19: per-kind staleness is derived from the corpus, not asserted.** For each
  reservation kind, measure the time from clearance to the observed release (vacated / handoff /
  go-around) where a release was heard, and set the timeout at the 95th percentile
  (`scripts/measure_release_times.py`, writes `docs/results/release-times.md` with the histograms).
  Fallback values if a kind has too few observed releases (< 20): CROSS 90 s, LUAW 180 s,
  LAND/TAKEOFF 300 s, stated as guesses in the report. Current engine value is a single
  `STALE_S = 300` for every kind.

## Level 2 — Parser extraction

- *Gold:* H4 event sheet, ~200 Tower transmissions sampled by transmission (not by parser output),
  stratified by speaker role, rules output hidden; 50-row overlap, kappa reported. The finished sheet
  becomes `tests/fixtures/event_gold.csv`; a test asserts the rules parser's score on it does not
  regress.
- *Design:* parser {rule, haiku, sonnet} x context {none, role, window} x transcript {gold, asr} =
  18 cells, all on the same ~200 transmissions. ~2,400 API calls, cached in `events`.
- *Pre-registered primary comparison:* **rule vs sonnet, window context, gold transcripts.** All
  other cells are secondary (ablations). Stated before any LLM parse runs.
- *Metrics per cell:*
  1. exact event-set match per transmission (unordered);
  2. per-slot precision / recall for action type, callsign, runway;
  3. **consequence-weighted score**: each transmission scores 1 minus the sum of error weights,
     floored at 0. An extraction error is one of five types, because an event is exactly
     `(kind, callsign, runway)`: `wrong_runway`, `wrong_kind`, `wrong_callsign`, `missed_event`,
     `spurious_event`. **DECIDED 2026-09-19: weights are derived from the engine, not asserted.**
     For each error type, perturb one event in each gold sequence that way, replay through the
     engine, and record whether the set of conflicts changed (an alert appeared or disappeared).
     The weight is the fraction of perturbations that changed the verdict
     (`atcdb/consequence.py`, `scripts/derive_weights.py`, writes `docs/results/consequence-weights.md`).
     Weights are fixed before the LLM parser runs. Robustness check: report the rules-vs-LLM
     ranking under equal weights as well. Chang et al. 2026 (errors cluster on runway identifiers)
     and our WER finding (digit errors dominate) are the prior expectation that `wrong_runway`
     comes out heaviest; the derivation tests it.
- *Failure taxonomy (required analysed failure):* every error classified as `multi_instruction |
  conditional_clearance | nonstandard_phrasing | asr_digit | hallucinated_event | other`, counted
  per parser. Cross-tab by speaker role and airport to test whether non-standard-phrasing errors
  cluster (the "English in cultural contexts" thread, now measurable).
- *Bootstrap CIs* (1,000 resamples over transmissions) on every metric; n is small and the report
  says so.

## Level 3 — End-to-end conflict detection

Three gold sources, **reported as separate columns, never pooled**:

| Column | Source | N (target) | Realism | Human check |
|---|---|---|---|---|
| Synthetic | seeded text-level perturbations of real tower sequences (Section 4 design) | 40-60 sequences | low | none needed; labelled *synthetic* everywhere |
| ASRS-derived | H3 human-reconstructed sequences from triaged ASRS narratives | 10-20 | medium | second labeller marks fidelity |
| Case studies | Austin 2023 (positive), JFK 2023 (counterexample); candidate: San Diego 2023-08-11, Haneda 2024-01-02 | 2-4 | real | team-transcribed audio |

- *Metrics:* recall on synthetic and ASRS-derived sequences (did the engine raise the expected
  conflict, at or before the expected step); **false alarms per hour of unperturbed tower audio**
  (the unit the alerting literature uses); precision on adjudicated alerts (H5). Each metric per
  parser x transcript, window context only (context ablation stays at level 2).
- *H5 alert adjudication* also yields the false-alarm cause taxonomy: `anticipated_separation |
  missed_release | parser_error | asr_error | other`. Expect `anticipated_separation` to dominate if
  Level-1 option (1) is chosen; that is the finding.
- *LLM-judge arm:* whole sequence to Claude, "list conflicting clearances", scored on the same
  synthetic + ASRS-derived sets. Comparison column answering "is the structured pipeline worth it";
  replicates the AIAA 2024 GPT-4 setup.
- *Counterexample analysis:* JFK. Engine raises nothing and is right to; the report explains why a
  communications-only system cannot see a compliance failure, and what does (ASDE-X).

## Scope argument (evidence, not assumption)

- Surface surveillance at 44 US airports; no expansion planned (OIG 2025).
- Controller operational incidents: 18% of all FY2024 incursions, but 59% of Category A and 53% of
  A+B since FY2022 (`docs/incidents/ab-incursions-fy2022-2024.csv`).
- H2 ASRS triage estimates the share of communication-attributed reports that are runway vs taxiway
  vs airborne, and the share of pilot deviations with a frequency trace. Report both with kappa.

## Deliverables

| Script | Produces |
|---|---|
| `scripts/make_event_sheet.py` | H4 sheets |
| `scripts/make_alert_sheet.py` | H5 sheets from a replay run |
| `scripts/make_asrs_triage_sheet.py` | H2 sheets (done) |
| `scripts/score_agreement.py` | kappa per column (done; `cohen_kappa` pending) |
| `scripts/derive_weights.py` | consequence weights by perturbation, `docs/results/consequence-weights.md` (harness done; `perturb_event` pending) |
| `scripts/measure_release_times.py` | per-kind staleness from observed releases, `docs/results/release-times.md` |
| `scripts/eval_parsers.py` | level-2 table, `docs/results/parser-accuracy.md` |
| `scripts/eval_conflicts.py` | level-3 table, `docs/results/conflict-detection.md` |
| `scripts/eval_llm_judge.py` | judge column, appended to the above |

## Fallbacks

- No Claude API budget or time: the comparison degrades to rules vs LLM-judge on the same sets —
  still baseline + controlled comparison.
- Labelling time short: priority order H1, H4, H5, H2, H3, H6 (see `docs/labelling-protocol.md`).
  Whatever is dropped is stated in the report's limitations.
