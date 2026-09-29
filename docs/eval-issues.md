# Evaluation: open issues and decisions taken without asking

Logged while building the Level 2 (extraction) and Level 3 (conflict detection) evaluators on
2026-09-19 without the corpus DB. Each item says what was decided and why, so it can be reversed.

## Decided, reversible

1. **Injection recall is 1.0 by construction for the injecting configuration.** An injection is only
   kept if the injecting parser+engine raises a new conflict, so scoring the same configuration on it
   is circular. *Decision:* `eval_conflicts.py --save-injected` freezes the set (with the generating
   configuration recorded); every other configuration is scored with `--load-injected`. The report
   must name which configuration generated the set. Cleanest is to generate with the strongest
   configuration (rules, window, gold) and score everything else against it; the alternative — a
   human-verified injected set — is H3.

2. **Injected sequences cannot be replayed on ASR transcripts.** Edited lines have no ASR version
   (the edit is to the gold text). *Decision:* the gold-vs-ASR factor is measured at Level 2 and on
   the unperturbed false-alarm rate only; injected recall is gold-only. State this in the report. A
   workaround later: edit the ASR text of the same transmission with the same substitution.

3. **`drop_release` drops a cluster, not one line.** A landing is normally released twice
   ("vacated", then "contact ground"); dropping one leaves the other and nothing changes. *Decision:*
   drop the chosen release plus any release call within the next 3 lines (`RELEASE_CLUSTER`). This
   over-simulates a missed release; the alternative (drop only "vacated") under-simulates it.

4. **"Hours" = span of transmission start times, not audio duration or operations.** Recordings are
   silence-reduced; the denominator is `max(start_s) - min(start_s)` per recording. This inflates
   alerts-per-hour relative to wall-clock operations. *Decision:* keep it, label it "per hour of
   transmission time", and note that Wickens' comparable figure is per alert (1 − precision), which
   the H5 adjudication gives directly.

5. **Every unperturbed RUNWAY conflict is treated as a candidate false alarm.** The corpus has ~0 real
   conflicts (spec), so this is right in expectation, but only adjudication (H5) turns candidates into
   a false-alarm *rate*. Until then the report shows counts and per-hour, not precision.

6. **Injection only edits controller lines** (except `drop_release`, which may drop a pilot "vacated").
   Editing a pilot readback would create a READBACK conflict, not a RUNWAY one; those are a separate
   injection mode not written yet.

7. **`swap_runway` picks the replacement from runways already named in the recording.** A parser
   mishears a digit into another runway that is on frequency; it does not invent runway 07. Same
   plausibility rule as `perturb_event` in `atcdb/consequence.py`. Single-runway recordings cannot
   be injected this way and return None.

8. **Level 2 gold uses `?` for an unknowable field**, and the field is skipped in scoring rather than
   counted wrong. An LLM that guesses a callsign the human could not hear is therefore neither
   rewarded nor penalised. Alternative: count `?` as "must be blank" (penalises guessing).

9. **Extra predicted events break exact-match but not per-field accuracy.** A hallucinated second
   event on a line therefore shows up in score 2's exact-match and in score 1's false positives on
   lines with no gold change, but not in per-field accuracy. If hallucination is the H2 concern,
   add a per-line "spurious events" count to score 2.

10. **`CANCEL` and taxiways are in the label schema but not in the engine.** A correct `CANCEL`
    extraction is dropped before the engine; taxiway extractions never reach state. Both are scored
    at Level 2 and invisible at Level 3. The parser is expected to grow; the engine needs a
    `CancelClearance` event (decision pending: releases the named kind only, or any reservation).

11. **Sheet sampling stratifies by a keyword regex** (runway / taxiway / cross / hold short / line
    up / vacat / go around / cancel), 60% keyword lines. This biases prevalence, not labels, and
    guarantees positives; it must be stated. Rows with no keyword can still be positives ("cleared to
    land" without the word "runway"), which is why the regex includes "cleared"-free phrasing only
    via the keywords above — a line like "cleared to land" with no runway word is in the 40% stratum.

12. **`window` context columns in the gold sheet come from the rules-parser replay**
    (`active_callsigns`, `active_runways`). They are context shown to models, not labels, but they do
    inherit the rules parser's state. An LLM given `window` context is partly given rules output.
    The `none` and `role` levels are clean.

## Not done, needs the DB or a decision

- Run `make_event_sheet.py` and `eval_conflicts.py` on the corpus (instructions in
  `docs/eval-extraction.md`).
- Readback-mismatch injection mode.
- ASR variant of injected sequences (issue 2).
- `scripts/measure_release_times.py` (per-kind staleness from observed releases) — needs the DB.
- `cohen_kappa` and `perturb_event` (Jennifer).
- An LLM parser (`atcdb/parse_llm.py`) to register in `PARSERS` for both eval scripts.
- The LLM-judge arm (`eval_llm_judge.py`): whole-sequence and incremental variants, scored on the
  frozen injected set with the same `detected()`.
