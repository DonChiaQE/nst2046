# Handoff: the report drafts after the strip fix (2026-11-08, evening)

Read this first if you are picking up the report. It does not supersede
`2026-11-08-milestone2-submission-handoff.md` — that one is still the guide to *what the report needs* (section 6,
the contribution statement, the trim). This one covers *what changed underneath it* in the session after that
handoff was written, and what is already reconciled.

## The one thing that will confuse you

**Both report drafts are git-ignored** (`docs/milestone2-report-draft*.md`, a glob since 2026-11-08). Jennifer
compiles the submitted report outside the repo. So:

- Edits you make to a draft **will not be committed and will not show in `git status`.** That is intended, not a bug.
- `git add -A && git commit` will report "nothing to commit" after a pure draft edit. Don't go looking for what
  went wrong.
- The tracked evidence is `docs/results/*.md` plus `docs/logs/`. Keep draft edits and evidence regeneration in
  separate steps so you can tell which half you actually changed.

`data/atc.sqlite` is also untracked now (~23 MB, rebuildable, carries UWB-ATCC text this project does not
redistribute). It exists in this working tree. A fresh clone will not have it, so the corpus tests skip there.

## What changed underneath the report

`origin/same-strip-engine` was merged (2026-11-08). The engine now treats the two ends of one strip as one runway
(`OPPOSITE_MATRIX`), every arm was re-scored, and two follow-ups landed on top:

1. **The rules parser's designator pattern.** A blanket relaxation to accept a single digit-word had been applied
   to every recording. Measured, it is one-sided on this corpus: 110 of 22,956 transcripts (73 gold, 37 ASR) gain a
   designator the strict pattern refuses and **not one is genuine** — every one is a truncated mention
   (`"runway three o"` → `LUAW 03`; `"runway zero niner cleared to land"` → clearance dropped). So the default now
   requires two digit-words, verified identical to the frozen v1 baseline across 66,273 comparisons (22,956
   transcripts × 3 context modes, `parse` and `count_unresolved`), **0 differences**. The US single-digit form is
   opt-in per replay via `parse_rules.make_parser(single_digit_runways=True)`, enabled only for the Austin case
   studies (KAUS) and the Houston 2026 case (KIAH). No scored arm uses it.
2. **Adjudication.** The strip fix raised two alerts at keys no sheet covered (261, 352); both are now
   `parse_error`. Separately, three 2026-11-02 verdicts were revised `parse_error` → `missing_release` because the
   sheet then showed only six context lines and hid the clearance their verdict denied existed.

## The current numbers, and how to get them

Everything below is free and deterministic — stored rows only, no database beyond `atc.sqlite`, no API call. Always
run with `env -u ANTHROPIC_API_KEY` so nothing can bill.

```bash
env -u ANTHROPIC_API_KEY .venv/bin/python scripts/eval_conflicts.py report        # -> conflict-eval.md + case CSVs
env -u ANTHROPIC_API_KEY .venv/bin/python scripts/cross_arm_replication.py --markdown > docs/results/cross-arm-replication.md
env -u ANTHROPIC_API_KEY .venv/bin/python scripts/risk_score.py                   # §5 / Appendix G weights
env -u ANTHROPIC_API_KEY .venv/bin/python scripts/pending_sensitivity.py          # per-arm §4.2 rates; flags anything unadjudicated
env -u ANTHROPIC_API_KEY .venv/bin/python scripts/divergent_cases.py              # Appendix A1
env -u ANTHROPIC_API_KEY .venv/bin/python scripts/real_2026_cases.py              # §4.5 / Appendix F
```

**`cross_arm_replication.py` needs `--markdown` to reproduce the committed doc.** Without it you get fixed-width
output and a pointless diff.

| §4.2, window context | rules | Sonnet 5 | paired gap |
|---|---|---|---|
| gold, RUNWAY false alarms/h | 4.1 (1.9–6.6) | 5.3 (2.6–8.2) | −1.1 (−2.9 to +0.4) |
| ASR, RUNWAY false alarms/h | 4.5 (2.0–7.3) | 6.4 (3.3–9.8) | **−1.9 (−3.6 to −0.4)** |

Lenient recall is unchanged by all of this: 87% both transcript kinds for rules, 90% gold / 91% ASR for Sonnet.
The ASR false-alarm interval is still the only one in the study that excludes zero, and it is now *wider* than the
−1.5 it replaces, because the two new alerts count against the arm that raised them.

Per-arm `parse_error` after the revision: **0** for the rules parser on both transcript kinds, 1 Sonnet gold,
2 Sonnet ASR, 1 on each Haiku arm. Taxonomy over sheet A: 32 `parse_error` / 31 `missing_release` /
33 `engine_rule`, 0 `genuine`. κ = 0.80 over 31 — unchanged, because none of the five touched keys is in sheet B's
30% overlap.

Risk Score, rules stream, after the strip fix: `wrong_runway` 23/27/6, `dropped` 27/45/0, `spurious_inuse`
54/7/37, `spurious_other` **71/0/61** (changed output / lost a detection / created a false alarm).

## What is already reconciled in draft-2

Do not redo these; do spot-check any you rely on.

- **§2.2.1** records the designator restructuring and that the default is verified identical to the frozen baseline.
- **§2.3** has `OPPOSITE_MATRIX` in its own paragraph, notes that reservations are *stored* under one designator
  while only the *check* spans both ends (which is why `ENGINE_VERSION` needs no bump), and that a hold-short
  releases both ends.
- **§3.3.2** explains the `Pending` rule and carries the adjudication context-window limitation, including that the
  remaining 20 exposed rows were not individually re-walked.
- **§4.2** has the adjudicated numbers; the three-treatment sensitivity table was removed as redundant.
- **§4.3** contingency (gold Sonnet-only negatives 3) and the taxonomy sentence.
- **§4.4** ablation row (Sonnet extractor 5.3, `parse_error` 2 → now 1; **check this one**, see below).
- **§5 / Appendix G** rewritten against the re-scored tables; finding 3 is *reversed* — an invention on a runway
  "not in use" was the harmless case at 0% and is now the most consequential perturbation at 61%.
- **§7** rewritten with the 110-transcript measurement, the no-US-airport point, and the read-back asymmetry.
- **Appendices A1, B0, D1, H** — headings and contents corrected.

## Traps this session hit, so you don't

1. **Stale framing words outlive stale numbers.** Four of five stale items in the final pass were words, not
   figures: "verbatim", "ten", "a majority", "frozen". Grep your own hedge-words.
2. **`22,091` vs `22,956`.** An inner join against `transmissions` silently drops rows. The corpus is 22,956
   transcripts (17,039 gold, 5,917 ASR), all with `normalized_text`.
3. **`109` vs `110`.** Count by diffing what the relaxed pattern captures against the strict one, not by a
   hand-written regex. A regex for clearances must allow intervening words — `"cleared for immediate takeoff"`
   breaks `clear(?:ed)? for take ?off`.
4. **Don't dispatch reviewers at a tree you are about to change.** One reported that `engine.apply` ignores the
   strip — true of the tree it read, false by the time it reported. Pin a SHA, then review.
5. **`conflict-eval.md` can legitimately disagree with the report.** It refuses to print a rate while any alert is
   unadjudicated (`evaluate.Pending`). If you see `pending` there, run `pending_sensitivity.py` before assuming the
   report is stale.

## Open, and whose it is

- **Nothing arithmetic is known to be unreconciled.** §4.4's `parse_error` column was the last: it read 2 for the
  Sonnet extractor and 7 for the Sonnet judge, now 1 and 6 after the verdict revision. If you touch the
  adjudication again, that column and §4.3's taxonomy sentence are the two places per-arm `parse_error` is quoted.
- **The submission handoff's three items** (section 6, contribution statement, trim to 3,000–5,000 words) are
  untouched and still the team's.
- **The test suite is green: 430 pass, 2 skip, 0 fail.** The 2 skips are the live-app smoke tests, which need
  an API key. `torch` had been pinned at `2.13.0`, a release that does not exist, so it was never installed and
  the two GPU-transcriber tests failed on the missing module; repinned to `2.11.0` on 2026-11-08.
- **Not defects, reported as limitations:** the single-digit opt-in is correct by construction but exercised by no
  transcript in this corpus, and `readback.extract_items` deliberately stays ICAO-only, so a runway read-back miss
  on a single-digit designator goes undetected. Both have tests pinning them.
