# Live demo app: Runway Watch, design

**Status: design approved section by section in chat on 2026-10-20; spec approved the same day; amended while planning
(the eight "Planning amendments" in `docs/superpowers/plans/2026-10-20-live-demo-helper.md`, which win where they
differ).** Design guidance: `docs/2026-10-20-macos-hig-research.md` (the HIG brief, every point linked to its Apple page).

## 1. Purpose and success

**What it is for.** A live demo, a few weeks away, of the whole pipeline on the user's Mac: two people speak radio
calls into the Mac, one as the tower controller and one as the pilot; the app transcribes each call, runs both
extractors on it (the rules parser and Claude) and shows, side by side, what each understood and which runway
conflicts each one raised. The point the audience should see is the project's research question: the two extractors
disagree on real phrasing, and the side panel shows where.

**Success.**
- A full scripted exchange runs live, end to end, with no terminal and no restart.
- After a speaker releases the talk key, the transcript appears in about 2 s and both extractors' results within
  about 4 s.
- When live speech fails on the day, a typed line or a replay keeps the demo going without leaving the app.
- The app follows Apple's Human Interface Guidelines (Section 7) and passes Accessibility Inspector.
- What runs is the evaluated system: the same engine, rules parser and Claude parser code as the evaluation.

**Decided in chat (2026-10-20).**
- Approach 1: a native SwiftUI app in front, a local Python helper running the repo's own code behind it.
- Two speakers at one Mac, one talk key each (option B); no automatic speaker detection.
- Both extractors side by side (option A).
- Both backups: a typed-input box and a scenario replay.
- Claude model in the app: Haiku 5.5 (`claude-haiku-5-5`), subject to the week-1 check (Section 8).

**Out of scope.** Speaker detection from voice; iOS; distributing the app (signing for other Macs, notarization, the
App Store); editing any line but the last; more than one session at a time; a Claude model picker; the
conditional-clearance fix (still deferred, see the decision log).

## 2. Components

```
Mac app (SwiftUI, mac/)  --HTTP + event stream on 127.0.0.1-->  helper (Python, atcdb/live.py + live routes)
  window, keys, microphone,                                      Whisper ATC transcription (GPU)
  Apple speech preview,                                          rules parser + engine copy A
  typed input, replay, Settings                                  Claude parser (Haiku 5.5) + engine copy B
                                                                 session log in data/live/sessions/
```

**Mac app** (`mac/`, an Xcode project; Swift 6, SwiftUI, macOS 26 or later, Apple silicon). It owns everything on
screen and the microphone. It starts the helper at launch and stops it at quit (Section 6). Its logic lives in a
`LiveSession` model object that talks to the helper through a `HelperClient` protocol, so tests can swap in a fake.

**Helper** (Python, in this repo). A new module `atcdb/live.py` holds the session logic and no web code. Routes under
`/api/live/` join the existing FastAPI app (`atcdb/api.py`, `create_app`), so the replay page and the live app share
one server. The app runs it as `.venv/bin/python -m uvicorn atcdb.api:app --host 127.0.0.1 --port 8020` from the
repo checkout.

**Shared code.** The helper calls `engine.apply`, `parse_rules.parse`, `parse_llm.make_parser`,
`replay.build_context` and `asr.normalize_asr_text` unchanged. The only additions outside `live.py` and its routes
are `claude-haiku-5-5` in `parse_llm` (Section 8) and the GPU transcriber in `asr.py` (Section 5).

## 3. The window

Layout follows the HIG brief, sections 1 and 2.

```
┌──────────────────────────────────────────────────────────────────────────┐
│ Live Session      [ Tower (left ⌥) ] [ Pilot (right ⌥) ]   [Replay ▾] [▥] │
├───────────────────────────────────────────────┬──────────────────────────┤
│ transcript, newest at the bottom               │ CONFLICTS (newest first) │
│   each line: time, speaker, text,              │ RUNWAYS (Rules, Claude)  │
│   then a Rules row and a Claude row            │ SELECTED LINE            │
│ [Tower | Pilot]  Type a transmission... [Send] │                          │
└───────────────────────────────────────────────┴──────────────────────────┘
```

**Toolbar** (three groups at most).
- Leading: the window title, "Live Session".
- Center: one grouped control holding Talk as Tower and Talk as Pilot. Neither is the `.prominent` style at rest.
  While one records, it changes its background, its label reads "Recording" and its `mic.fill` symbol breathes
  (Breathe animation, off under Reduce Motion).
- Trailing: the Replay menu and the inspector toggle.
- Every toolbar item has a menu bar command (Section 4).

**Main pane: the transcript.** One row per transmission:
- time since the session started, the speaker (`headset` for Tower, `airplane` for Pilot) and the text (selectable);
- a **Rules** row and a **Claude** row with what each extracted, in the event-sheet wording (`LAND 18L fedex
  fourteen thirty two heavy`), or "Nothing understood";
- a small spinner on a row still waiting, an inline error with **Retry** on a row that failed (Section 6);
- a conflict symbol on the row that raised a conflict, per extractor.

While a key is held, a live row shows "Recording, Tower" and Apple's preview text; on release the preview is
replaced by the helper's transcript. A row whose transcript came from Apple speech carries the label "Apple speech".
The typed-input box sits under the transcript: a Tower/Pilot segmented control, a text field, and Send (Return).

**Inspector** (trailing; ⌥⌘I and View > Show Inspector / Hide Inspector):
- **Conflicts**, newest first. Each card: symbol, label and color together (Runway conflict:
  `exclamationmark.octagon.fill`, red; Readback: `exclamationmark.triangle`, orange), the runway, the two callsigns
  and clearances, and **Raised by: Rules / Claude / Both**. Cards stay until New Session.
- **Runways**: a table with columns Runway, Rules and Claude, each cell what that extractor's engine holds on that
  runway (kind and callsign), or empty.
- **Selected line**: for the transcript row selected, the two extractors' events field by field (kind, runway,
  callsign).

**Look.** Semantic system colors, system text styles (Body 13 pt default), SF Mono for times, runways and callsigns,
standard materials in the content (Liquid Glass only where the system puts it), system appearance (no in-app
light/dark setting). Text size is adjustable from the View menu up to 200 percent, so a room can read it.

## 4. Commands and keys

| Command | Menu | Shortcut |
|---|---|---|
| Talk as Tower (start / stop) | Session | ⌘1, or hold left Option |
| Talk as Pilot (start / stop) | Session | ⌘2, or hold right Option |
| Undo Last Line | Edit | ⌘Z |
| New Session | File | ⌘N |
| Save Session As... | File | ⌘S |
| Replay: Austin 2023 / a saved session | Session > Replay | none |
| Stop Replay | Session | Esc |
| Show / Hide Inspector | View | ⌥⌘I |
| Bigger Text / Smaller Text / Actual Size | View | ⌘+ / ⌘- / ⌘0 |
| Use Apple Speech for Transcripts (toggle) | View | none |
| Settings... | app menu | ⌘, |

**Hold-to-talk.** The left and right Option keys are told apart with `NSEvent` modifier flags (device-dependent
masks for left and right Option), read by a local event monitor while the app is active. Option types no character,
so the keys never clash with the text field. The HIG does not cover hold-to-talk, so the menu commands and the toolbar
buttons start and stop recording with a click as well (HIG brief, section 2). Esc also stops a recording.

## 5. One transmission

1. **Key down.** The app notes `t` (seconds since the session started), starts recording the microphone with
   `AVAudioEngine` and feeds the same buffers to Apple's `SpeechAnalyzer` with a `SpeechTranscriber`, whose volatile
   results fill the live row. The analysis context is primed with ATC words (NATO alphabet, digits, "runway",
   "cleared"), if the API supports it (checked in week 1).
2. **Key up.** A clip shorter than 0.5 s is dropped with the note "Too short". Otherwise the app writes the clip as
   16 kHz mono 16-bit WAV and posts it with the role, `t` and Apple's final text to the helper.
3. **Transcription.** The helper transcribes the clip with the Whisper ATC model and normalizes it with
   `normalize_asr_text`. If Whisper fails or takes over 8 s, or the app has View > Use Apple Speech for Transcripts on,
   the helper uses Apple's text instead (normalized the same way) and marks the source. It sends `transcript` at once.
4. **Extraction.** Both extractors parse the same text, each in `window` context built with `build_context` from the
   session's own history and its own engine state. Each result is sent as soon as it is ready.
5. **Engine.** Each extractor's engine copy applies its events; the result carries the events, the new conflicts and
   that engine's runway table.

**Ordering.** Each extractor has one worker that handles transmissions in sequence order, because `window` context
needs the previous line's state. Rules never waits for Claude. A transmission that arrives while Claude is busy waits
in Claude's queue.

**Whisper on the GPU.** `asr.make_hf_whisper_transcriber` loads `jacktol/whisper-medium.en-fine-tuned-for-ATC`
(the Hugging Face weights behind the repo's CTranslate2 model) with `transformers` on PyTorch's `mps` device, into
`data/models/whisper-medium.en-atc-hf` (git-ignored). The CTranslate2 model stays for the evaluation's ASR. Measured
2026-10-20: the CTranslate2 model on CPU takes 7 to 10 s for a 2.8 s clip, too slow live.

**Typed lines** skip steps 1 to 3 (source `typed`). **Replays** send each scripted line at the script's pace with the
script's own `t`: text lines skip steps 1 to 3; audio lines from a saved session go through steps 3 to 5.

**Austin scenario.** Built from `tests/fixtures/austin_dca23fa149.txt` from 0628:26 on (as `scripts/pilot_cases.py`
does), roles from the speaker ident, `t` from the transcript times, one line every 2 s on screen. The engine sees the
real 284 s gap between the landing and takeoff clearances.

## 6. Helper API and failure handling

All under `/api/live/`, JSON unless noted:

| Route | Does |
|---|---|
| `GET health` | Whisper `loading` / `ready` / `failed` (with reason), Claude key present, versions |
| `POST sessions` | New session; returns `session_id`. Starts a session folder |
| `POST sessions/{id}/transmissions` | Multipart: `role`, `t`, `source` (`speech` / `typed` / `replay`), `transcriber` (`whisper` / `apple`), and `audio` (WAV) and/or `text`, plus `preview_text`. Returns `seq` |
| `POST sessions/{id}/undo` | Removes the last transmission from both engines; returns its `seq` |
| `POST sessions/{id}/transmissions/{seq}/retry` | Re-runs Claude on a failed line and on every later line, in order (see Undo and retry) |
| `POST sessions/{id}/label` | Names the session for the Replay menu (Save Session As...) |
| `GET sessions` | Saved sessions, for the Replay menu |
| `GET sessions/{id}/replay` | A saved session's lines (role, `t`, text, audio path), for replaying |
| `GET sessions/{id}/stream` | Server-sent events: `transcript`, `extraction` (per extractor: events, conflicts, runways, or an error), `undone`, `status` |

**Session log.** `data/live/sessions/<timestamp>/` (git-ignored) holds `clip_<seq>.wav` and `session.jsonl`: one
record per transmission with role, `t`, source, Apple's text, the transcript, each extractor's events, conflicts,
timings and, for Claude, token use. Undone lines stay in the log, marked undone.

**Undo and retry.** Each engine keeps its state per step (`State` is immutable). Undo removes the last step from both
engines and restores the state before it; a Claude result that arrives for an undone line is discarded. A failed Claude
line is skipped, and later lines are parsed against the state without it (unlike the evaluation, which stops a
`window` replay at a failure, because a demo has to carry on). Retry re-runs Claude on the failed line and then on
every later line, in order, rebuilding Claude's engine from that point; at Haiku 5.5 prices this costs a fraction of a
cent.

**Failures.** All shown inline next to the problem, with a way to fix it; no alerts (HIG brief, section 3).

| Failure | Behaviour |
|---|---|
| No internet, a Claude error, a refusal, or no reply in 10 s | The Claude row: "Claude unavailable:" and the reason, with **Retry**. The live client uses a 10 s timeout and one retry. Claude's engine skips the line until retried; Rules carries on |
| Whisper fails or takes over 8 s | Apple's text is used for that line, labelled "Apple speech" |
| Garbled line | Undo Last Line, then speak or type it again |
| Clip under 0.5 s | Dropped, "Too short" |
| Microphone access denied | Inline `mic.slash` note, "Open System Settings", typing still works |
| Speech recognition denied | No preview text; transcription by Whisper is unaffected |
| Helper does not start or crashes | One automatic restart; then an inline note with **Restart Helper**, Talk disabled with the reason |
| Whisper model loading (about 18 s) | "Loading speech model...", determinate if the download is running; Talk disabled until ready |

**API key.** An app started from the Dock cannot see `~/.zshenv`. Settings has a field for the Anthropic API key,
stored in the Keychain and passed to the helper as `ANTHROPIC_API_KEY` when the app starts it. Settings also holds the
repo checkout path the helper runs from (default: the path the app was built from).

**Permissions and strings.** Ask for the microphone on the first Talk, not at launch.
`NSMicrophoneUsageDescription`: "Runway Watch uses the microphone to transcribe the radio calls you speak."
`NSSpeechRecognitionUsageDescription`: "Runway Watch uses speech recognition to show your words while you talk."
Claude sends transcript text off the Mac; the Settings key field says so.

## 7. Apple Human Interface Guidelines

The HIG brief is the checklist. Requirements every screen is checked against before the demo:
1. Instructions and conflicts in a trailing inspector, toggled from the toolbar and ⌥⌘I; no leading sidebar.
2. At most three toolbar groups; every toolbar item mirrored in the menu bar; nothing essential at the window bottom
   except the typed-input backup.
3. Conflicts shown with symbol, text and color, never color alone; no alert or notification per conflict; cards not
   dismissed on a timer.
4. Semantic colors and system text styles; system appearance; contrast at least 4.5:1 for body text; Increase
   Contrast and Reduce Transparency checked.
5. Microphone requested on first use with the purpose string above; denial handled inline with a System Settings
   button; no success message after granting.
6. VoiceOver labels on every control, updated with state ("Start talking as Tower"); new conflicts announced; rows
   grouped as single elements; headings Transcript, Conflicts, Runways, Selected Line.
7. Full Keyboard Access; standard shortcuts not repurposed; full screen supported with Talk and the inspector
   reachable.
8. Reduce Motion stops the breathing microphone and row animations; motion is never the only signal.
9. Labels: verbs in title case on buttons, nouns on column headings, one term list (Tower, Pilot, Runway conflict,
   Readback, Rules, Claude); errors say how to fix them; empty state "No transmissions yet. Hold a talk key and read
   a clearance."
10. Window size, inspector state and text size restored on relaunch.
11. App icon drawn in Icon Composer (no SF Symbols in the icon), with default, dark, clear and tinted variants.

Accessibility Inspector runs on the finished app, and its findings are fixed before the rehearsals.

## 8. Haiku 5.5 in the parser

`parse_llm.MODELS` gains `claude-haiku-5-5` with settings `thinking: {type: "disabled"}`, `output_config: {effort:
"low"}` and no sampling parameters (Haiku 5.5 rejects non-default `temperature`; it accepts disabled thinking at low
effort and a forced tool call). `PRICES_PER_MTOK` gains (0.10, 0.50); the dry-run estimate counts about 30 percent more
tokens for it (newer tokenizer). `parse_llm.VERSION` stays `p1`: the cache key already includes the model. Recorded
replies back its tests, as for the other two models.

**Week-1 check (about 6 cents, in the cost table shown on 2026-10-20).** Run it on the 200 labelled instructions (`role` context,
`score_pair_events.py --model claude-haiku-5-5`) and on the two pilot cases, against Sonnet 5's saved results. Its replies on the Austin lines are kept as the recorded
replies the helper's tests use. It
becomes the app's Claude model if it misses at most 2 more labelled runway events than Sonnet and invents at most
twice as many; otherwise the app uses Sonnet 5 (about $0.004 per line). The same result informs the evaluation's
model choice, which stays a separate decision.

## 9. Build order and testing

| Week | Work | Gate |
|---|---|---|
| 1 | Whisper on `mps`: time 20 test-split clips; word error rate against the human transcripts, beside the CTranslate2 model's | Median at most 2.0 s per clip and a word error rate at most 2 points above CTranslate2's; otherwise Apple speech becomes the default transcript and Whisper an option. Passed while planning: 1.03 s, 9.3% vs 11.0% |
| 1 | Haiku 5.5 in `parse_llm` and the 6-cent check (Section 8) | As in Section 8 |
| 1 | `SpeechAnalyzer` probe: volatile results and context priming on this Mac | Preview text appears while talking |
| 2 | `atcdb/live.py` and the `/api/live/` routes | Tests pass |
| 2 to 3 | The Mac app | Tests pass; manual checklist below |
| 3 | HIG and Accessibility Inspector audit; two full rehearsals with Jennifer, one saved as the replay backup | Section 1 success criteria met in a rehearsal |

The work follows the usual flow: this spec, a plan proven from its text, subagent-driven development with review.

**Python tests (test first, pytest).** Session logic with a fake transcriber and recorded Claude replies (no paid
calls): each extractor's state is separate; ordering under a slow fake Claude; Rules not blocked by Claude; undo
restores both engines; a Claude failure leaves Rules untouched and Retry re-runs in order; the Apple-text fallback on a
Whisper timeout; clips under 0.5 s rejected. The Austin replay through the session: Rules raises its warning at 0639:34
only, as in `docs/results/pilot-cases.md`, and the Claude side gives exactly what an offline fold of the same recorded
replies gives (`scripts/pilot_cases.py`), so the live path and the evaluated path cannot drift apart. Routes
through FastAPI's `TestClient`, including the event stream. UWB-ATCC text stays out of tests and fixtures, as before.

**Swift tests (Swift Testing).** `LiveSession` against a fake `HelperClient`: rows fill as events arrive in any order,
undo, retry, errors shown on the right row, Raised by computed from both extractors, replay pacing. Event-stream
parsing from recorded server-sent events.

**Manual checklist** (in the plan): permissions granted and denied, left and right Option told apart, helper crash
and restart, no internet, Whisper fallback, text size, VoiceOver pass, full screen, light and dark.

## 10. Cost

| Item | Cost |
|---|---|
| Claude in the app (Haiku 5.5) | About $0.0002 per line; a 50-line rehearsal about 1 cent |
| Week-1 Haiku 5.5 check | About 6 cents |
| Tests | None: recorded replies (the two existing live smoke tests cost a fraction of a cent when a key is set) |
| Whisper, Apple speech, Xcode, running the app on this Mac | Free (a paid Apple Developer account is only needed to distribute the app) |
