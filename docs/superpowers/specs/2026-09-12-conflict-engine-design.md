# ATC conflict engine — design

**Status: APPROVED 2026-09-14; Section 3 addendum approved 2026-09-17; phase-3 design-pass addendum written
2026-09-26, awaiting review.** Phases 1 and 2 merged (PR #1, PR #2). Next step: review the addendum, then the phase-2.5
plan via `superpowers:writing-plans`.

## Context / pivot

The group (Don, Jennifer) settled the project idea (evolved from the two ideas in the
consult doc): **parse ATC transmissions into structured state-changing actions
("instruction = a tool call") over a spatial world model of runway occupancy, and flag
conflicting clearances.** Example: "Tail 001 cleared to land runway 31" reserves runway 31;
a later incompatible clearance for 31 (another aircraft cleared to cross it) is flagged.

Feasibility checked against `data/atc.sqlite`: 1,142 Tower + 133 Ground recordings;
169 tower recordings with ≥6 transmissions in sequence (max 27); 393 tower recordings with
≥2 runway mentions. Enough sequential material for replay; genuine conflicts ≈ 0 in the data
(normal ops), so evaluation uses synthetic conflict injection + real incident case studies.

## Decisions locked (with the user)

1. **Replay-first**: demo replays recorded sequences. Stretch goal: "live" mode where the
   team speaks into the mic (push-to-talk → existing ATC-fine-tuned Whisper → same pipeline).
   No LiveATC dependency.
2. **Unify with existing readback work**: readback checking becomes a second conflict type in
   the same engine (instruction creates an expected readback; engine flags runway clashes AND
   bad readbacks). Human labelling sheets (`data/labels/`, still 0/250 filled) remain relevant.
3. **World model scope: runways only** (v1). Reservations for land/takeoff/cross/line-up-and-wait;
   no taxiway routing, no altitude-level tracking. Same-runway conflicts only; intersecting-runway
   geometry is a stretch goal.
4. **LLM = Claude API** (tool use). Rules/NER parser is the non-LLM baseline.
5. **App = FastAPI backend + JS front-end**: runway board, transmission feed, conflict banners,
   browser mic for push-to-talk stretch.
6. **Architecture = Approach A**: deterministic event-sourced state machine core; parsers are
   swappable and quarantined to extraction. Rejected: LLM-as-agent holding state (B).
   End-to-end LLM judge (C) is folded in as an **evaluation arm only** (structured system vs
   raw-LLM-over-transcript — maps to the proposal's "is AI better than simpler ML, what context
   helps" questions).

## Section 1 — Events, state, conflicts

- **Events** (dataclasses in new `atcdb/engine.py`, pure logic, no I/O):
  `ClearToLand`, `ClearTakeoff`, `LineUpAndWait`, `ClearToCross`, `HoldShort` (each
  `(callsign, runway)`); `RunwayVacated(callsign)`, `GoAround(callsign)`,
  `Handoff(callsign, to)` with `to ∈ {ground, departure, tower, approach}`;
  `ReadbackObserved(callsign, text)` → routed to existing readback checker; `NoOp`.
  Runway designators normalized at event creation ("three one" → `31`, L/R/C suffix kept).
- **State = pure fold over events** (`state = apply(state, event)`), holding per-runway active
  reservation sets `(callsign, kind, seq)` and per-aircraft status (reservation, pending
  instruction text awaiting readback, last activity seq). Pure fold ⇒ time-scrubbing in UI
  free, unit tests are event-list → expected-conflicts.
- **Conflict compatibility matrix** — checked when a new reservation is added against each
  active reservation on the same runway. Initial values below; **severities are open for
  tuning** once real sequences run through.

  | new ↓ / active → | LAND | TAKEOFF | LUAW | CROSS |
  |---|---|---|---|---|
  | LAND | ok (anticipated separation) | alert | alert (Austin 2023 pattern) | alert |
  | TAKEOFF | alert | warning | ok if same callsign (upgrade), else alert | alert |
  | LUAW | alert | warning | warning | warning |
  | CROSS | alert | alert | warning | ok |

  `HoldShort` never conflicts (it is the safe instruction) but records intent; it is released by
  the next instruction to the same callsign. Readback mismatch: warning by default, **alert**
  when the mismatched item is the runway.
- **Releases**: `RunwayVacated`; `Handoff` to `ground` (releases LAND and CROSS — a taxiing
  aircraft handed to ground is off the runway) or `departure` (releases TAKEOFF); `GoAround`
  cancels LAND. Fallback for missed release calls: a
  reservation older than a **staleness timeout, initially 300 s** of transmission time
  (`start_s`), is dropped silently. Tunable.
- **Conflict record**: `(type RUNWAY|READBACK, severity alert|warning, runway, callsigns,
  triggering transmission_id, human-readable explanation)` — explanation is what the app
  displays.
- **Persistence**: new `events` table, one row per event, keyed by
  `(transcript_id, parser, model, model_version, context)` + `seq`, with `kind`, `callsign`,
  `runway`, `extra_json`. Keying by `transcript_id` (not `transmission_id`) means a gold parse
  and an ASR parse of the same transmission are distinct cache entries. `parser ∈ {rule, llm}`,
  `context ∈ {none, role, window}` (the Section 2 context modes). A transmission that parses to no instruction is stored as a single
  `NoOp` row so the cache knows it was parsed. Parse **failures are not cached**; the next
  replay retries. Conflicts are derived at replay/eval time, not stored.

## Section 2 — Parsers

- **Interface**: `parse(transmission, context) -> list[Event]`. `context` = speaker role
  (from DB), last few transmissions, active callsigns/runways. Context is a first-class,
  ablatable parameter with three modes — `none`, `role` (speaker role only), `window` (role +
  the last 4 transmissions + active callsigns/runways) — answering the proposal's "what
  context helps?" question empirically. `window` is the default outside ablation runs.
- **Rules parser** (`atcdb/parse_rules.py`): extends existing NER/phraseology regexes,
  pattern → event mappings. Known blind spots (= report material): multi-instruction
  transmissions, conditional clearances ("behind the landing A320, line up and wait"),
  clipped/nonstandard phrasing.
- **Claude parser** (`atcdb/parse_llm.py`): Claude tool-use, tool schema mirrors event
  dataclasses 1:1, temperature 0, short ATC-phraseology system prompt. Run Haiku vs Sonnet
  as a cheap-vs-strong axis. All parses cached in `events` keyed by
  `(parser, model, model_version, context)` — one API call per transmission per model per
  context mode, ever.
  ⚠ Before writing any API code: load the `claude-api` skill.
- **Shared input knob**: run both parsers on gold transcripts AND on ASR output (13.0% WER,
  digit-heavy errors) — third eval axis: does ASR noise break parsing; does the LLM degrade
  more gracefully than rules?
- **Label-circularity caution** (lesson from readback round): eval labels must not come from
  the rules parser alone → human-verify a slice (~200 transmissions, hand-checked events,
  same workflow as the existing labelling sheets). See Section 4.

## Section 3 — FastAPI + replay UI

**Shape.** The web layer is thin; the engine stays pure. Three new pieces, following the
repo's flat-modules-under-`atcdb`, thin-scripts convention:

- `atcdb/replay.py` — pure logic with a DB read at the edge. `build_timeline(conn,
  recording_id, parser, model, transcript_kind, context) -> Timeline`: for each transmission
  k in time order, the transcript used, the events the chosen parser produced, the folded
  state after k, and any conflicts raised at k. A single `get_events(conn, tx, parser, ctx,
  model, model_version)` helper returns cached rows from `events` or parses-and-caches on a
  miss; the precompute script (`scripts/parse_events.py`) and the API share that one code path.
- `atcdb/api.py` — FastAPI app built by `create_app(db_path)` so tests point it at a fixture
  DB. Serves the static front-end and a small JSON API. Run with `uvicorn atcdb.api:app`.
- `atcdb/static/` — `index.html`, `app.js`, `style.css`. Vanilla JS, no build step, no npm.
  All logic that matters lives server-side; the JS only renders.

**Endpoints.**

- `GET /api/recordings` — recordings with `facility = 'Tower'`, ≥4 transmissions and ≥1
  runway mention, ordered by transmission count desc; each with airport, facility,
  transmission count, runway-mention count.
- `GET /api/recordings/{id}/replay?parser=&model=&transcript=&context=` — the whole timeline
  in one response (recordings top out at ~27 transmissions). Defaults: `parser=rule`,
  `transcript=gold`, `context=window`. Client scrubs locally; no per-step calls.
- `GET /api/clips/{transmission_id}` — streams the audio clip (`transmissions.clip_path`).
- `GET /api/capabilities` — which parsers/models are available and whether live mode is
  enabled. UI greys out what the server cannot serve (Claude without an API key, live mode
  without the Whisper model on disk).
- `POST /api/live/{session_id}` (stretch) — accepts an audio blob + speaker role chosen in
  the UI (no diarization). Server writes a temp WAV, runs `make_faster_whisper_transcriber`
  (loaded lazily on first use), `normalize_asr_text`, the selected parser, folds onto the
  in-memory session's event list, returns the new step. Sessions live in memory only.

**Front-end layout.**

```
┌──────────────────────────────────────────────────────────────┐
│ [recording ▾] [parser ▾] [transcript ▾]   ⏮ ◀ ▶ ⏭  ━━━●━━━  │
├──────────────────────────────┬───────────────────────────────┤
│ RUNWAY BOARD                 │ TRANSMISSION FEED             │
│ ┌ 31 ──────────┐ ┌ 13 ─────┐ │ 00:12 CTL  tail 001 cleared   │
│ │ N001  LAND   │ │ (idle)  │ │            to land runway 31  │
│ │ N002  LUAW ⚠ │ │         │ │       ▸ ClearToLand(N001,31) │
│ └──────────────┘ └─────────┘ │ 00:19 PLT  cleared to land 31 │
│                              │            tail 001           │
│ CONFLICTS (this replay)      │       ▸ ReadbackObserved …    │
│ ⚠ 00:41 ALERT rwy 31 …      │ ▶ 00:41 CTL  ...   [♪ play]    │
└──────────────────────────────┴───────────────────────────────┘
```

Runway cards come from the state snapshot at k: reservation badges, red (alert) / amber
(warning) highlight when a conflict involves that runway. The feed shows transmissions up to k
with parsed events as chips beneath each, current one highlighted, click-to-jump,
per-transmission audio play. A banner shows the explanation string for any conflict raised
at k; the conflicts panel keeps the running list. Play auto-advances every 2 s.

**Error handling.** Unknown recording → 404. A parse failure (e.g. API error) records the error
on that step with empty events and the fold continues — a flaky call never breaks a replay.
Failed parses are not cached (Section 1). Live sessions are in-memory only; a server restart
clears them.

**Testing.** `replay.py` unit-tested against the existing in-memory SQLite fixture pattern with
a fake parser: fixture recording in, expected snapshots and conflicts per step out. `api.py`
tested with FastAPI's `TestClient`: recordings list shape, replay shape, 404, clip streaming,
capabilities. JS gets no unit tests — manual smoke run only.

**Dependencies.** Add `fastapi`, `uvicorn`, `python-multipart`, `anthropic` to
`requirements.txt`, pinned like the rest.

**Deferred.** Side-by-side rules-vs-Claude event column in the feed (cheap, since both
timelines are single responses) — not v1. Intersecting-runway geometry — out, as locked.

### Section 3 addendum — phase-2 decisions (approved 2026-09-17)

Settles the API-surface questions the phase-1 review left open. Where this addendum and the text above disagree,
the addendum wins.

- **JSON layer.** New pure module `atcdb/serialize.py` turns `Timeline`, `Step`, `State`, `Conflict` and events into
  plain dicts. No web dependency, so response shapes are unit-tested without HTTP and `atcdb/api.py` stays routing
  only. Each replay step carries the transmission, its events, the conflicts it raised, any parse error, the runway
  board snapshot and the aircraft map. The timeline carries every runway named anywhere in the recording, so the
  board never reflows. The client derives the cumulative conflict list itself.
- **Recordings and errors.** `list_recordings` returns dicts. A new `get_recording` distinguishes an unknown id
  (404) from a known recording with no transcripts of the requested kind (200, empty steps). An unknown parser, an
  unknown context mode or an unknown transcript kind is rejected with 422.
- **Database access.** One SQLite connection per request, opened and closed inside each handler from the path given
  to `create_app(db_path, project_root)`. Not a yield-dependency: FastAPI may run a sync dependency and a sync
  handler on different pool threads, and a connection must not cross threads. No shared connection, no
  `check_same_thread` flag. Module-level `app = create_app()` uses the corpus DB, so `uvicorn atcdb.api:app` works.
- **Transcript pinning.** Gold replays pin the `human` model (865 transmissions also carry an `atco2-xml` gold
  transcript, and the cache key must not drift between runs); any other kind takes its alphabetically first model.
  An explicit `transcript_model` query parameter overrides the default.
- **Cache key.** Unchanged. The app never tunes engine rules, so `parse_events.py --refresh` stays the invalidation
  path; an engine version in the key moves to phase 3, where tuning happens.
- **Front-end.** `atcdb/static/` with `index.html`, `app.js`, `style.css`, served at `/`. Layout as sketched above.
  A runway card lists active reservations, lists aircraft holding short of it in a lighter style, and turns red
  (alert) or amber (warning) when a conflict at the current step names that runway. Play advances every 2 s; the
  left and right arrow keys step; a play button per transmission streams its clip through one shared `<audio>`.
- **Capabilities.** Registered parsers with their model and version, the context modes, the transcript kinds and
  models that exist in the DB, and `live: false`.
- **Testing.** Shape tests for `serialize.py`; API tests with FastAPI's `TestClient` on a seeded temporary DB,
  including a generated WAV for the clip route; manual browser smoke run for the JS.
- **Dependencies.** `fastapi`, `uvicorn`, and `httpx2` (Starlette's test client warns on plain `httpx`), pinned.
  `python-multipart` waits for phase 4 and `anthropic` for phase 3.

## Section 4 — Evaluation plan

**Two levels of gold, both reusing existing machinery.**

- **Engine gold is free.** State is a pure fold, so engine tests are event lists in, expected
  conflicts out. Every cell in the compatibility matrix gets a hand-written case, plus release,
  go-around and staleness cases. This isolates the engine from parser quality entirely.
- **Parser gold is human-verified.** A new labelling sheet of ~200 tower transmissions
  (`scripts/make_event_sheet.py`, same workflow as `make_label_sheet.py`): rules-parser output
  is deliberately hidden, the labeller writes the true events, a second person does a 50-row
  overlap for agreement. **Sample by transmission, not by rules-parser output**, so the rules
  parser does not set the ceiling on what the sheet can find. ATCO2 NER `command`/`callsign`
  spans (~200 each, ATCO2 slice only) are a secondary sanity check, not the gold.

**Five experiments, three scripts, results written to `docs/results/` in the style of the
existing WER and readback reports.**

| Experiment | Proposal question | Method |
|---|---|---|
| Parser accuracy (`scripts/eval_parsers.py`) | Is the LLM better than simpler ML? | Rules vs Claude Haiku vs Claude Sonnet on the verified slice. Exact event-set match per transmission (unordered); per-field precision/recall for event type, callsign, runway. |
| Context ablation (same script, `--context`) | What context helps? | Each parser with `none` / `role` / `window` context. Same metrics. |
| Gold vs ASR input (same script, `--transcript asr`) | Does transcription noise break it? | Rerun on ASR transcripts. Report the accuracy drop per parser; which degrades more gracefully. |
| Conflict detection (`scripts/eval_conflicts.py`) | Does the system catch conflicts? | Real tower sequences with injected conflicts. Recall on injected sequences; false-alarm rate per unperturbed sequence (real conflicts ≈ 0). |
| LLM judge (`scripts/eval_llm_judge.py`) | Is structure worth it? | Whole transcript sequence to Claude: "list conflicting clearances". Scored on the same injected set, reported as a comparison column. |

**Conflict injection is at the text level, not the event level.** A seeded perturbation edits a
real gold transcript so the sequence now contains a conflict: swap a runway designator so a
crossing lands on an occupied runway; upgrade a hold-short to a cross; delete the "runway
vacated" call so a stale reservation collides with the next clearance. Editing text means every
experiment exercises the full pipeline, parser included, and the same perturbed set scores the
LLM judge fairly. Reuses the seeded-perturbation approach from `atcdb/readback.py`. Injected
sequences are loaded into the DB under a separate source (`name='synthetic-conflicts'`,
`kind='corpus'`) as new recordings/transmissions that reuse the original clip paths with
`pcm_sha1` NULL, and gold transcripts with `model='synthetic'`, so they never mix with the
real corpus and double as replay demos.

**Incident case studies are demo material, not metrics.** Two real runway incidents replayed
through the app from public LiveATC archive audio, transcribed by the team: Austin 2023
(FedEx/Southwest — the LUAW/TAKEOFF-vs-LAND pattern) and JFK January 2023 (American/Delta —
a crossing against an active takeoff clearance). Each gets a short write-up of what the engine
flagged and when.

**Mic stretch acceptance.** A team member reads a scripted three-transmission conflict aloud
through push-to-talk and the engine flags it live. Pass/fail, no metric.

**Caveats to state in the report.** The readback sheets (`data/labels/`) are still unlabelled
and the event sheet competes for the same labelling time; the report says which sheet was
prioritised and why. Injected conflicts are synthetic; the case studies are the only real ones.

## Addendum — phase-3 design pass (decided 2026-09-19, written 2026-09-26)

Records the decisions from the phase-3 brainstorm and the findings from running real incident transcripts through
the engine. Where this addendum and anything above disagree, the addendum wins; it amends Sections 1, 2 and 4 and
replaces the build order.

### A.1 Build order

Phase 3 is split, and engine tuning moves ahead of it:

1. ~~Engine core~~ (merged, PR #1). 2. ~~App~~ (merged, PR #2).
3. **2.5 — engine tuning and Section 1 amendments** (A.3). Nothing to do with the Claude parser; lands first so no
   LLM parse or evaluation number is produced against an engine that is about to change.
4. **3a — Claude parser** plus the cache-affecting carry-overs (A.4). Ends with `parser=claude` working in the
   replay UI.
5. **3b — evaluation** (A.5). Gets its own design pass before its plan.
6. **4 — live push-to-talk and incident case studies** (A.6).

### A.2 Findings that constrain the design

Measured on the 309 foldable tower recordings (gold, `human`) and two NTSB incident dockets.

- **Recordings are clips, not sessions.** Median span 23 s, p90 48 s, max 139 s. `STALE_S = 300` has never fired on
  this corpus. 62 of 309 recordings raise at least one conflict; 85 in total (50 RUNWAY, 35 READBACK).
- **Releases are almost never spoken.** About 2% of reservations see a release call inside the clip. The controller
  establishes that a runway is clear by looking; the transmitted proxy is the handoff (`contact ground` 186 times vs
  `cleared to land` 187 times), not `runway vacated` (about 5 genuine pilot reports in 3,767 transmissions, and zero
  controller requests for one). Section 1's choice of the ground handoff as a release is confirmed.
- **Austin 2023 (NTSB DCA23FA149, Attachment 1)** — the verbatim tower transcript, folded through the engine with the
  rules parser, *models* correctly (a TAKEOFF against a held LAND on 18L is the matrix's alert cell) but the parser
  fails three ways: the landing clearance `…one eight left cleared to land` is dropped because the LAND pattern needs
  the token `runway`; US compound-number callsigns (`fedex fourteen thirty-two heavy`, `american nineteen thirteen`)
  extract as `''`, which caps the conflict at warning; the conflict fires 36 s late, at the controller's
  re-confirmation, and only because the takeoff clearance had already put 18L into `window` context. The landing and
  takeoff clearances are **284 s** apart.
- **Single-digit runways do not normalise.** `normalize_runway("four left")` returns `None`; only `zero four left`
  parses. US controllers drop the leading zero. Any US airport with runways 1–9 is affected, whichever extractor
  produced the string.
- **Corpus recording 528 (step 17) is a correct parse and a false alert.** Air France 198R is cleared to cross 13,
  CSA 38W is then cleared to land 13, and the crossing is never released on frequency. Extraction is right; the
  missing information is not in the audio. No parser change fixes it.
- **JFK 2023 (DCA23LA125) is outside the envelope.** Every transmission was lawful; American 106 crossed 4L without a
  clearance that was ever spoken. Surface radar (ASDE-X) caught it. A radio-only system cannot, whatever the
  extractor.
- **Framing.** ICAO Doc 4444 (7.9.2, 7.10.1) governs physical separation; the engine has no position data. It detects
  **incompatible clearances**, a proxy for loss of separation. Reports state this rather than claim ICAO compliance.

### A.3 Phase 2.5 — engine tuning (amends Section 1)

1. **Holding short expires and releases.** `Aircraft` gains the time its `holding_short` was set; `_expire` clears it
   on its own timeout; `RunwayVacated` and a ground or departure handoff clear it.
2. **HoldShort cancels that aircraft's reservation on the named runway.** "Hold short runway 13" after a crossing
   clearance for 13 is a cancellation in real phraseology. A hold-short of a *different* runway does not release
   anything: the transmission that clears Air France across 13 also tells it to hold short of 24, so releasing on
   it would erase the crossing the moment it is issued. Recording 528 therefore stays a false alert, on purpose.
3. **READBACK conflicts carry a runway.** The missing item's own runway value, else `ac.runway`, else
   `ac.holding_short`, so a runway-readback alert highlights a card.
4. **Handoff targets are validated** against `HANDOFF_TARGETS`; an unknown target still releases nothing but is counted.
5. **Dropped-instruction counter** on `Step` and `Timeline` (instructions whose runway will not resolve, unknown
   handoff targets), serialised through the API.
6. **Staleness per kind, mechanism only.** `STALE_S` becomes a dict keyed by reservation kind, every kind defaulting
   to 300 s so behaviour and existing tests are unchanged. A test pins **LAND ≥ 284 s** with Austin as the reason.
   CROSS and LUAW values are chosen in 3b against the false-alarm metric, not guessed.
7. **`normalize_runway` accepts single-digit designators** (`four left` → `04L`). It lives in the engine and every
   extractor's runway string goes through it, so this is a shared bug, not a rules-parser tuning.
8. **ICAO citations.** `phraseology_rules` (empty today) is populated with the Doc 4444 paragraph behind each matrix
   cell: 7.10.2 (landing clearance), 7.9.3.1 (take-off clearance), the 7.10.2 proviso (LAND after LAND is lawful),
   7.9.2 and 7.10.1 (TAKEOFF against LAND). The handoff release and the staleness timeout are recorded as engineering
   heuristics with no ICAO basis. Conflict explanations may cite the paragraph.
9. **Fixtures.** Austin becomes a replay fixture (NTSB records are public; the hand-keyed text is re-checked against
   the PDF before commit): it must raise a RUNWAY conflict on 18L. Recording 528 becomes a regression test that runs
   against `data/atc.sqlite` and skips when the corpus is absent, since UWB-ATCC is CC BY-NC-ND and is not
   redistributed in the repo: it must still raise its alert at step 17.

### A.4 Phase 3a — Claude parser (amends Section 2)

- **Models and configuration.** Haiku 4.5 (`claude-haiku-4-5`) and Sonnet 5 (`claude-sonnet-5`) as the cheap and
  strong arms, configured to match: both do one-shot extraction with thinking off. Haiku at temperature 0; Sonnet 5
  rejects `temperature` with a 400, so it runs with `thinking: {type: "disabled"}` and `effort: "low"`.
  Reproducibility comes from the cache (one parse per key, ever) and a `strict: true` tool schema, not from
  temperature. Section 2's "temperature 0" is superseded.
- **One tool.** `report_events`, taking an `events` array; `kind` enumerated over the ten event kinds, `to` over
  `HANDOFF_TARGETS`; `additionalProperties: false`; forced `tool_choice` (supported on both models). The four fields
  per event — change, runway, callsign, type — match the engine's `Event` one to one.
- **What is cached.** Unchanged contract: API errors and `stop_reason: "refusal"` propagate and cache nothing.
  Individual events that fail validation are dropped and counted (A.3.5); a parse with nothing left stores the NOOP
  row.
- **Registry.** `PARSER_MODELS` becomes `dict[str, list[str]]`. The Claude parser is resolved lazily on first use, so
  importing `atcdb.replay` never needs `anthropic`. `parse_llm.VERSION = "p1"`, bumped by hand whenever the prompt or
  schema changes, like `parse_rules.VERSION`.
- **Capabilities.** One entry per parser-model pair, each with `available: bool` and a `reason` (`anthropic not
  installed`, `ANTHROPIC_API_KEY not set`). The UI lists unavailable parsers disabled, with the reason as a tooltip.
- **API.** A validated `model` query parameter on the replay endpoint; an unknown parser-model pair is a 422 (today
  FastAPI ignores it and silently returns the rules parse).
- **Carry-overs landing here** (they must precede the first cached LLM parse): per-recording transcript pinning, so
  the `synthetic` gold recordings from conflict injection replay; `get_events` re-raises when the re-read after an
  `IntegrityError` is empty; a request token in `app.js`, now load-bearing because a cold Claude replay is one call
  per transmission.
- **Latency.** `window` context depends on the engine state after the previous transmission, so a cold replay is
  sequential (about 30–60 s for recording 528). `none` and `role` can run in parallel; that concurrency belongs to
  3b's evaluation script, not 3a. `parse_events.py` gains `--parser`, `--model`, `--recording` and a `--dry-run`
  that prints the call count and estimated cost before spending.
- **Cost.** The whole tower corpus under both models and all three context modes is about $66; the 200-transmission
  labelled slice about $3.50. Cost does not shape the design; prompt caching is not engineered for.
- **Testing.** The Anthropic client is injected, so a small fake client covers response-to-event mapping, validation,
  dropping and prompt rendering without a mock framework; a few recorded real responses back the mapper; lazy
  registration is tested with `anthropic` absent; one live smoke test skips without a key.

### A.5 Phase 3b — evaluation (amends Section 4)

The written report (section 4, "Technical Investigation Plan") is now the commitment; this spec follows it.

- **Pre-registered primary comparison:** rule-based vs Sonnet, `window` context, human-transcribed input. Factors
  varied around it: extractor (rule, Haiku, Sonnet), context (none, role, last 4), transcript (human, ASR).
- **Level 1, extraction.** About 200 real tower transmissions labelled blind to every parser; 50 labelled twice for
  Cohen's κ; kept as a standing regression test. Metrics: exact event-set match, per-field precision and recall, and
  a consequence-weighted Risk score (Chang et al., 2026) whose weights come from perturbing labelled events (wrong
  runway, wrong type, wrong callsign, missed, spurious) and observing the engine's output change.
- **Level 2, end to end.** Positives: synthetic conflicts injected into real sequences (as in Section 4),
  sequences reconstructed by hand from triaged ASRS narratives, and NTSB-investigated events. Negatives: unperturbed
  real recordings. Metrics: recall, false alarms per hour of real audio, a taxonomy of failure types; κ on the ASRS
  triage and on the adjudication of every alert.
- **Ablation.** The LLM judge (whole sequence in, conflicts out) scored on the Level 2 sets.
- **Reporting.** Bootstrap confidence intervals throughout. The false-alarm rate is a finding, not a parameter to
  tune away; per-kind staleness (A.3.6) is tuned on a split that is not used for the reported numbers.
- **Left for the 3b design pass:** the ASRS triage and reconstruction procedure, the Risk-weight derivation, and
  labelling logistics. **Risk:** Level 1 has no gold until someone labels ~250 rows, and the readback sheets are
  still 0/250. Labelling can run in parallel with 2.5 and 3a and should start now.

### A.6 Phase 4 — case studies (amends Section 4)

LiveATC keeps archives for 30 days, so case-study audio and text come from NTSB dockets. Only major (`FA`/`MA`)
investigations carry a verbatim ATC transcript; smaller ones (Sarasota DCA23LA179, Boston DCA23LA192, JFK
DCA23LA125) hold raw audio and paraphrase in the factual report. Austin is the confirmed case; LaGuardia 2026
(DCA26MA161, the report's motivating incident) is the next candidate once its docket is public. JFK is written up as
the out-of-envelope example.

### A.7 Open questions for review

1. **Freeze the rules parser for the comparison?** Fixing the `runway`-token and US-callsign gaps (A.2) makes a
   fairer baseline, but they were found on Austin, and the report's appendix already shows the v1 behaviour.
   Recommendation: freeze `parse_rules` v1 as the pre-registered baseline and report its gaps as findings; fix only
   `normalize_runway` (A.3.7), which is shared.
2. **Engine version in the cache key?** `window`-mode parses depend on engine state, and 2.5 and 3b both change the
   engine. Today the fix is `parse_events.py --refresh`, which for LLM parses costs a few dollars and silently
   leaves stale rows if forgotten. Recommendation: add a hand-bumped `ENGINE_VERSION` to the key in 3a, before the
   first LLM parse is cached.

## Suggested build order

One spec, one plan, four phases. Each phase leaves the repo runnable and tested.

1. **Engine core**: `engine.py` events + fold + matrix + releases; `events` table in
   `schema.py`; rules parser; `replay.py` + `get_events`; `scripts/parse_events.py`.
   Tests: matrix cells, releases, staleness, replay builder with a fake parser.
2. **App**: `api.py`, static front-end, clips, capabilities. Replay works end-to-end on real
   recordings with the rules parser.
3. **Claude parser + evaluation**: `parse_llm.py` (load `claude-api` skill first), event
   labelling sheet, conflict injection, the three eval scripts, results docs.
4. **Stretch**: live push-to-talk endpoint + mic UI; incident case studies.

## Domain notes worth keeping

- A runway is never formally "declared clear" on frequency — the controller observes it.
  Transcript-observable release signals: "runway vacated", handoff to ground/departure.
- Two successive landing clearances on one runway are legal (anticipated separation) — a naive
  occupied-bit would false-positive constantly; hence the reservation-set + matrix design.
- ADS-B (OpenSky historical, free for research) is the public "radar": aircraft-in-runway-polygon
  (polygons from OSM/OurAirports) gives geometric ground truth for occupancy, independent of
  comms. Positioned as corroboration/eval, not v1 engine input. ATCO2 was built with OpenSky
  callsign data; recordings have airport + timestamp to join on.
