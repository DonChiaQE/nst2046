# Handoff: run the evaluation through the API (2026-10-25)

Read this first in a new session. It supersedes the "Next step" section of `2026-10-21-runway-watch-app-handoff.md`,
which still describes plan B (the Mac app) and this Mac's tooling traps.

## Next step: the evaluation run, paid from the user's API credits

The user said on 2026-10-25: "i suddenly came across a lot of API credits, i think we can run the API after handoff".
That approves running the evaluation through the API in the next session. Still state each step's cost before spending,
and dry-run first.

1. **Ask one question first: Haiku 5.5 only, or Sonnet too?** Before the credits, the user said "i dont think we need
   sonnet ... haiku's good enouhg", and Claude agreed: Haiku 5.5 did as well on the 200 labelled lines (31 of 32 runway
   events found, 6 invented; Sonnet 32 and 9), costs a twentieth, and is what the demo runs. With credits, running
   Sonnet as well keeps the pre-registered comparison (rules vs Sonnet, window) and needs no deviation in the decision
   log. Recommend both if the credits cover about $25; Haiku 5.5 only otherwise.
2. **Switch the code.** Add `claude-haiku-5-5` to `atcdb/evaluate.py` `EVAL_MODELS` (or replace Sonnet, per step 1)
   and to `atcdb/judge.py` `MODELS`; update the tests that pin them (`tests/test_evaluate.py` asserts the arms' models
   are rules, Haiku 4.5 and Sonnet 5). Drop the Haiku 4.5 arms unless the user wants them (the professor: cut to the
   pre-registered comparison). Log the decision in `docs/logs/decisions.md` before any paid call.
3. **Dry run (free)**, measured 2026-10-22 on the 309 real recordings, `window` context, gold and ASR: parser 1,989 +
   2,016 calls, judge 309 + 309. **Haiku 5.5 $1.05; Sonnet $16.18.** The 100 injected recordings add $0.69 at Haiku
   5.5. `judge.estimate_cost` lacks `parse_llm`'s 1.3 tokenizer factor for Haiku 5.5, so its dry-run line reads about
   30% low.
4. **Run the negatives**: `python scripts/eval_conflicts.py run --parser llm --model <M> --context window --set
   negatives` (both transcripts), then `--parser judge`. The six rules arms are already done (free):
   `data/eval/conflicts/rule-*.jsonl`.
5. **The positives wait for Jennifer's injection check** (`data/labels/injection_check.csv`, 0 of 100, untracked):
   only `valid=yes` injections are scored. Then `python scripts/inject_conflicts.py --apply-sheet
   data/labels/injection_check.csv` and `run ... --set positives`.
6. Then `python scripts/eval_conflicts.py adjudicate` writes the false-alarm sheets for Don and Jennifer (guide section 3),
   and `report` writes `docs/results/conflict-eval.md`.

## Decided since the last handoff (2026-10-22)

- **The Level 1 event sheets are skipped for Milestone 2** (no time). Extraction results come from the readback sheet's
  200 labelled instructions, with its limits stated (mostly approach and radar, controller lines only, one labeller).
  Logged in `docs/logs/decisions.md`.
- **A labelling guide** is at `data/labels/README.md`: the injection check (Jennifer, now), the event sheets (if ever),
  adjudication (after the run). Its new conventions (area control counts as departure; a frequency with no unit is noop;
  runway from context with a note; conditional and corrected clearances) were shown to the user, not yet confirmed.
- **No subscription runs for the evaluation.** Claude Code on the subscription sends its own instructions and the
  plugins' hook text with every request, and `claude --bare` (the clean mode) authenticates only with an API key. A
  subscription run is not the parser's request and could not be reported as the result.

## Still open

- **Plan B** (`docs/superpowers/plans/2026-10-21-runway-watch-app.md`): awaiting the user's review and execution choice.
  Claude recommended inline execution with one review of the whole branch at the end.
- **Pull request** `live-demo-helper` into `asr-recording-filter`: for the user to open from GitHub's compare link
  (`gh` cannot run here).
- **The professor's points** (`memory: milestone-2-feedback`): 1 done (readback sheet and pilot cases); 2 is this run;
  3 is Jennifer's injection check; 4 is the adjudication after the run; 5 is report writing for Don and Jennifer; 6 the
  logs are drafted, owners marked Don to check with Jennifer.

## Where the work is

Branch `runway-watch-app` (off `live-demo-helper`, not pushed) holds plan B, the labelling guide, the decision row and
this handoff. `asr-recording-filter` and `live-demo-helper` are pushed. Do the evaluation run on `runway-watch-app` too
unless the user wants a separate branch: the three branches stack, so everything merges in order.
