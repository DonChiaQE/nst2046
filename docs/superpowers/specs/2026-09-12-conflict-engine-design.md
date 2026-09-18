# ATC conflict engine — design

**Status: APPROVED 2026-09-14; Section 3 addendum approved 2026-09-17.** Phase 1 (engine core) merged. Next step: phase-2 implementation
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
