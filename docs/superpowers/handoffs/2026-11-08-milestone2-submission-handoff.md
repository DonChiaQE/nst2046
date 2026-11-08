# Handoff: finish and submit the Milestone 2 report (2026-11-08)

Read this first in a new session. It supersedes `2026-10-25-evaluation-run-handoff.md`, whose evaluation run is done.

**The report is due today, 2026-11-08, 23:59 SGT** (guidelines, "At a glance"). Milestone 2 is 20% of the course:
a 6 to 10 page PDF excluding references and appendices, plus a stable link or attached copy of the technical
artefact. Everything technical is finished. What is left is writing, and three of the four items need the team's
own judgment rather than another analysis.

The working draft is `docs/milestone2-report-draft.md`. **It is git-ignored on purpose** (decision below), so it
lives only in the working tree. Keep a copy outside the repo.

## Next step: what only the team can do, in order

1. **Section 6, the societal and philosophical analysis.** This is 30% of the rubric, the largest single block,
   split across three 10% criteria: stakeholders and consequences, philosophical/normative analysis, and
   socio-technical integration. The draft gives structure, evidence and three candidate threads but deliberately
   does not pick one, because the submission checklist penalises concepts used "to reason, not merely to name-drop
   theories" and that choice has to be the team's. The recommended thread is the tracing comparison the professor
   asked for in feedback 6: the four-field extractor stays auditable, the LLM judge does not, and the judge is also
   worse (72% recall against 90%, 14.3 false alarms per hour against 4.9). Socio-technical integration is the
   criterion this evidence hits hardest, since the argument can point at `engine.apply` and at the judge arm's
   numbers rather than at a general worry about LLMs.
2. **The contribution statement.** Required by the submission checklist and by section 8 of the guidelines; nobody
   outside the team can write it. While writing it, resolve the trailing line of `docs/logs/decisions.md` ("Owners
   marked Don are decisions approved in Claude Code sessions; check whether Jennifer was consulted"). Several
   owners look wrong: Jennifer did the injection check (100 rows) and adjudication sheet B (31 rows, both rounds).
3. **Trim.** The draft is about 7,300 words against a 3,000 to 5,000 word target. Most of the excess is editorial
   scaffolding written for the team, not for the reader: the "Working notes" feedback table at the top, the
   per-section page budgets in the headings, and the instructions to yourselves. Appendix A does not count toward
   the limit.
4. **Figures 1 and 5 are placeholders.** Figure 1 is the pipeline box-and-arrow diagram and is mechanical; Figure 5
   is the three-column tracking/tracing comparison and should be drawn only after item 1 settles, so it illustrates
   the chosen claim instead of preceding it. Figures 2, 3 and 4 exist in `docs/figures/` (git-ignored).
5. **Finish the references.** The draft's list is partial; the sources are in `docs/references/` (git-ignored).

## What landed this session

All of it is on `main` and pushed (`12768f4`, then `1129789`). 348 tests pass; the two failures in
`tests/test_asr.py` are pre-existing and need a GPU module this Mac does not have.

- **The consequence-weighted Risk Score Milestone 1 promised** (`scripts/risk_score.py`, 17 tests,
  `docs/results/risk-score.md`). Perturbs one event at a time in a recording's stored stream, re-folds it through
  the engine and records what happened to the alerts. Free and deterministic: no re-parsing, no API call. Findings:
  only 19 to 34% of single-field errors change any alert; omission costs recall (45 to 54%) and raises a false
  alarm 0% of the time on every arm, while invention raises one 37% of the time when it lands on a runway in use
  and 0% when it does not; and an invented clearance on an unused runway still loses a true detection 14 to 20% of
  the time, because a new reservation supersedes whatever that aircraft already held. The last of these is a
  hallucination that suppresses a real alert with no alert, no alarm and no trace.
- **A paired interval for the primary pair on ASR transcripts** (`PRIMARY_ASR` in `atcdb/evaluate.py`, rendered by
  `atcdb/eval_report.py`), answering feedback 4. Rules minus Sonnet on ASR: lenient recall -4 pts (-10 to +1),
  RUNWAY false alarms -1.5 per hour (-3.0 to -0.4). **That false-alarm interval is the only one in the study that
  excludes zero**, and it contradicts the Milestone 1 hypothesis: under transcription noise the LLM is not worse at
  finding conflicts, it is worse at not inventing them.
- **The divergence analysis** (`scripts/divergent_cases.py`, report Appendix A). The arms agree on 83 of 98
  positives and 306 of 309 negatives, so ten recordings carry the whole difference. Reading them one by one, the
  5-2 split on positives is two mechanisms pulling opposite ways, not one parser being better. All five Sonnet-only
  catches are the same thing: the rules parser extracts the reservation already open with an empty callsign, so the
  engine caps the conflict at warning because an unidentified aircraft may be the same aircraft; Sonnet names it
  and the identical situation alerts. Both rules-only catches are the mirror: Sonnet invents a clearance for the
  aircraft already holding the runway, the new reservation supersedes the old one, and the matrix rates the
  rewritten pair lower (LUAW becomes TAKEOFF, warning; TAKEOFF becomes LAND, ok). Only one of the ten, recording
  242, is an invented conflict.
- **The report draft was rewritten against the Milestone 1 feedback.** Section 2 is now about context and
  hallucination, with Milestone 1's tokenisation/attention/softmax passage and its temperature-0 claim explicitly
  retracted (Sonnet 5 rejects a `temperature` parameter; spec addendum A.4). Section 6 is restructured onto
  pipeline against judge rather than rules against LLM. Section 4 leads with extraction and reports gold beside
  ASR. Sections 4.3 and 4.4 were merged so the results move from the shared mass to the divergences.

## Environment: one thing fixed, one thing to know

- **`data/atc.sqlite` is now the real one.** Jennifer's copy had 0 injections, 882 cached events and 0 judgments,
  so `eval_conflicts.py report` silently dropped all 98 positives and wrote `recall: n/a over 0 positives`. Don's
  copy is committed on branch **`runway-watch-app`** (commit `aa889ee`, 24 MB), not on `main`, and carries 100
  injections, 36,001 cached events (7,276 Sonnet 5, 7,122 Haiku 5.5: the paid parses) and 1,628 judgments. It is
  installed. The previous copy is backed up at `data/atc.sqlite.bak-20261108` (git-ignored).
  To re-install from scratch: `git cat-file -p origin/runway-watch-app:data/atc.sqlite > data/atc.sqlite`.
- **`report` now regenerates correctly.** Verified by regenerating and diffing: the gold section comes out
  byte-identical to the committed doc, and the only change is the new ASR block. If a future run ever prints
  `recall: n/a over 0 positives` again, the database has lost its injections; do not commit that output.

## Open decisions, with recommendations

1. **The hybrid extractor, measured but not written up.** The divergence mechanisms suggest a specific combination:
   take the rules parser's events, which never invent, and backfill blank callsigns from Sonnet's event of the same
   kind and runway on the same transmission. Simulated from the stored rows with no API call, it scores **94%
   lenient recall (92/98) at 4.5 RUNWAY false alarms per hour**, against rules at 87%/4.1 and Sonnet at 90%/4.9. It
   beats both on recall, sits between them on false alarms, and raised **zero** new alert keys, so that rate is
   fully adjudicated rather than pending. Both baselines reproduce the committed doc exactly, so the harness is
   sound. It exists only as a scratchpad script. **Recommendation: report it in section 7 as the most informative
   next test with a preliminary number, not in section 4 as a result.** It is post-hoc, designed after reading the
   divergences and scored on the same 98 positives that motivated it, so presenting it as a finding would be
   overfitting. It is also not cheaper to run than Sonnet, since you still need the LLM for the callsigns.
2. **A caveat for section 4.1.** Sonnet's 9 "inventions" rest on one labeller with no second reader and no kappa,
   and 7 of them are approach clearances read as landing clearances, which is arguably a judgment call rather than
   a clear error. The handoff scores on the same sheet were already discarded for exactly this reason (the labeller
   marked only 36 of 92 "contact <frequency>" lines as handoffs), so the precedent is in `extraction-pair-events.md`
   already. **Recommendation: add one sentence.**
3. **API credits remain, and the LLM context sweep is still unrun.** Section 2 argues that context is the operative
   mechanism variable but can only evidence it from the rules arms (91/87/87 at none/role/window) and from the
   hallucination data, because both LLMs ran at `window` only for Level 2. Dry run measured 2026-11-08 with the
   caches now restored: Sonnet at `none` $6.88, at `role` $6.90. **Recommendation: do not run it today.** It is
   4,000 live API calls on the afternoon of the deadline, and sections 2 and 7 already name it as the first thing
   to buy. Revisit for the Week 13 presentation.

## Decided this session

- **The report draft, `docs/figures/` and `docs/references/` are git-ignored** (commit `12768f4`). The draft and
  figures are the deliverable and are written outside the repo; `docs/results/` holds the tracked evidence they
  cite. `docs/references/` is 42 MB of papers that are not ours to redistribute.
- **Tracked instead:** `notebooks/milestone2_pipeline_walkthrough.ipynb`, which the report attaches as its
  technical artefact, and `data/labels/real_2026_cases_A.csv` / `_B.csv`, the Goa 2026 reconstruction.

## Still open from the plan, reported as deviations

These are already written into the draft's limitations section; they are listed here so nobody re-discovers them.

- **The pre-registered Level 1 event sheets were never labelled.** `data/labels/event_sheet_A.csv` (0 of 200) and
  `event_sheet_B.csv` (0 of 50, the overlap for kappa) exist but are empty, and no script reads them. Section 4.1
  substitutes the readback sheet's 200 labelled instructions (`data/labels/pair_events_A.csv`, 200 of 200), which
  is one labeller, no kappa, and mostly approach and radar rather than tower. Labelling sheet B is 50 rows, about
  20 minutes each for two people, and would give Level 1 a kappa on tower audio and let the Risk Score weights
  become a per-parser score.
- **The Goa 2026 reconstruction is prepared but unlabelled** (`data/labels/real_2026_cases_A.csv` / `_B.csv`, 7
  rows each, `events` empty). Real incidents are reported as case studies without rates, per the professor's
  suggestion 3.
- **READBACK alerts were counted but not adjudicated**, so their rate is an upper bound (decision 2026-10-25).
- **The ASR arms carry train/test leakage**: the Whisper model was fine-tuned on this corpus's train split and 80%
  of our transmissions are train split, so reported degradation is a lower bound.
