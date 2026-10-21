# Handoff: the Runway Watch Mac app, plan B ready (2026-10-21)

Read this first in a new session. It supersedes the "Next step" section of `2026-10-20-live-demo-handoff.md`; that file
still holds the decisions made in chat and how the user likes to work.

## Where things stand

- **Plan A is done** on `live-demo-helper` (commits f830b5c to 9cb9cd2): the helper, `/api/live/` routes, Whisper on
  the GPU, Haiku 5.5 in the parser. The user chose "Native only, no reviews", so no reviewer has read that code.
- **O2 is done** (9da2820, 4734dea): Haiku 5.5 passed the gate against Sonnet (31 of 32 runway events found, 6
  invented; Sonnet 32 and 9) and stays the app's model. About 5 cents, from the dry-run estimates.
- **Pushed 2026-10-20 at the user's request:** `asr-recording-filter` and `live-demo-helper`. The pull request
  `live-demo-helper` into `asr-recording-filter` is for the user to open from
  https://github.com/DonChiaQE/nst2046/compare/asr-recording-filter...live-demo-helper?expand=1 (`gh` cannot run here).
- **Plan B is written** on `runway-watch-app` (off `live-demo-helper`, not pushed):
  `docs/superpowers/plans/2026-10-21-runway-watch-app.md`, 7 tasks and operational steps B1 to B4. It was proven: all
  files rebuilt from its text alone were byte-identical to a tested prototype, except the recorded fixture, which the
  plan's script regenerates (the same 95 events, the two extractors interleaved differently); 51 Swift tests pass; the
  app builds with no warnings; the prototype ran against the real helper (typed lines, the Austin replay ending with the
  rules parser's one late warning on 18L at 6:39:34, launching and stopping its own helper).
- The spec's week-1 `SpeechAnalyzer` gate passed while planning (plan B, amendment 1).

## Next step

1. Ask the user to review plan B and choose how to execute it (plan A: "Native only, no reviews").
2. Execute it on `runway-watch-app`.
3. B1 and B2 need the user at the Mac (microphone, Option keys, VoiceOver, Accessibility Inspector). B3 and B4 call
   Claude: ask first, with the cost (about 1 cent each).

## This Mac

- `/usr/local/bin/git` and `/usr/local/bin/gh` are Intel binaries and there is no Rosetta: scripts that call `git` need
  `PATH=/usr/bin:$PATH`; `gh` does not run.
- The terminal has no screen-recording or assistive access, so screenshots and UI scripting fail. An app can capture its
  own window (`cacheDisplay`), but that misdraws the inspector's translucent background; drawing a view alone in an
  offscreen `NSHostingView` shows its real colors.
- The shell exports `ANTHROPIC_API_KEY`: start a helper or the app from a terminal with `env -u ANTHROPIC_API_KEY`
  unless a paid step was approved.
