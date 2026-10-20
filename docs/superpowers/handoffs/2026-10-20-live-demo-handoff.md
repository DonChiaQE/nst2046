# Handoff: Milestone 2 work and the live demo app (2026-10-20)

Read this first in a new session. For the evaluation run it supersedes the "Where things stand" section of
`2026-10-01-evaluation-run-handoff.md`; that file and `2026-09-29-evaluation-handoff.md` still hold the evaluation's
settled decisions and how the user likes to work.

## Next step: execute plan A

1. **Confirm the execution method with the user first.** They said "native and subagent". Read as: the session
   implements each task itself (native, superpowers:executing-plans), a fresh subagent reviews each task before the
   next starts, and a final whole-branch review runs on the most capable model. Ask in one line whether that is right.
2. Create branch `live-demo-helper` off `asr-recording-filter` and execute
   `docs/superpowers/plans/2026-10-20-live-demo-helper.md` (6 tasks). The plan was proven: all 22 files rebuilt from
   its text alone were byte-identical to a tested implementation, 329 tests passing (4 skipped in a checkout without
   the corpus DB; 2 of those run here). Each task fails, then passes, exactly as its steps say.
3. Run every test with the key unset: `env -u ANTHROPIC_API_KEY python -m pytest -q`. The two live smoke tests
   otherwise call the API.
4. After Task 6: operational step O2 (the Haiku 5.5 check, about 6 cents) **only after the user approves the spend**.
   O1 (the Whisper gate) already passed while planning.
5. Then write plan B (the SwiftUI app) with superpowers:writing-plans, from the spec, the HIG brief and O2's result.

## The live demo app (Runway Watch)

- **Spec (approved):** `docs/superpowers/specs/2026-10-20-live-demo-app-design.md`, amended while planning (the plan's
  eight "Planning amendments" win where they differ).
- **HIG brief:** `docs/2026-10-20-macos-hig-research.md`. The user insists the app follows Apple's Human Interface
  Guidelines; spec Section 7 is the checklist, plus an Accessibility Inspector pass.
- **Decided in chat (do not re-open):** a live demo in a few weeks on the user's M3 Pro; a native SwiftUI app (`mac/`)
  in front of a local Python helper running the evaluated code (approach 1); two speakers at one Mac, hold left Option
  for Tower and right Option for Pilot, plus click to start and stop (option B); rules and Claude side by side, each with
  its own engine (option A); both backups, a typed line and a replay (Austin NTSB, saved rehearsals); Claude model
  `claude-haiku-5-5` unless the week-1 check fails, then `claude-sonnet-5`; working name "Runway Watch".
- **Measured while planning:** the CTranslate2 Whisper model on CPU takes 7 to 10 s for a 2.8 s clip (too slow live);
  the same fine-tuned model on `mps` through `transformers` takes a median 1.03 s with a word error rate of 9.3% vs
  11.0% on 20 test clips; its first load takes about 18 s. Weights downloaded to
  `data/models/whisper-medium.en-atc-hf` (1.5 GB, git-ignored).
- **Cost:** building and rehearsing costs cents (Haiku 5.5 about $0.0002 per line). Nothing has been spent on the app.

## Milestone 2 (the professor's feedback, `memory: milestone-2-feedback`)

Done on `asr-recording-filter` (unpushed; commits 9b38fa2 to 1a3b167):
- Pilot cases with real output: `docs/results/pilot-cases.md` (Sonnet catches Austin at the takeoff clearance; rules warn
  36 s late; Sonnet read "on the go" as a takeoff; Prague is a `missing_release` false alarm for both).
- Rules vs Haiku 4.5 vs Sonnet on the 200 labelled instructions: `docs/results/extraction-pair-events.md` (runway
  events found / invented: rules 30 / 0, Haiku 31 / 7, Sonnet 32 / 9 of 32).
- The `missing_info` verdict split into `missing_release` and `other_frequency`.
- `docs/logs/ai-use.md` and `docs/logs/decisions.md` (22 entries each; owners marked Don need checking with Jennifer).
- Level 1 sheets generated, unlabelled: `data/labels/event_sheet_A.csv` (Don, 200) and `_B.csv` (Jennifer, the first
  50). Pilot lines repeating a clearance are labelled `readback <callsign>`, not the clearance.

Open:
- Jennifer fills `data/labels/injection_check.csv` blind (0 of 100; untracked until it has verdicts).
- The evaluation's paid run: the user declined the ~$30 primary run. Haiku 5.5 would make the primary comparison on
  gold and ASR about $1.50, but swapping Sonnet for it changes the pre-registered comparison and is the user's
  decision, informed by O2.
- Report writing (mechanism section around context and invented clearances; tracing comparison pipeline vs judge) is
  Jennifer's and Don's.
- Nothing pushed. The user decides when to push or open a PR.

## How this user likes to work (additions)

- Plain, simple explanations; they asked for the professor's feedback to be "easier to understand".
- Budget is tight: state every cost before spending, dry-run first, never run paid steps without a yes. A wrong
  claim of approval was made once this session and corrected; do not record approvals that were not given.
