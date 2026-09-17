# Handoff — ATC conflict engine (2026-09-18)

Read this first in a new session. It says where the work stands, what is decided, and what to do next.

## Where things stand

| Piece | State |
|---|---|
| Spec | `docs/superpowers/specs/2026-09-12-conflict-engine-design.md` — Sections 1–4 approved 2026-09-14; Section 3 addendum approved 2026-09-17 |
| Phase 1, engine core | Merged to `main` via PR #1 (2026-09-15). Plan: `docs/superpowers/plans/2026-09-15-conflict-engine-core.md` |
| Phase 2, replay UI | Done on branch `replay-ui`, **not pushed, not merged**. 155 tests passing. Plan: `docs/superpowers/plans/2026-09-17-replay-ui.md` |
| Phase 3, Claude parser + evaluation | Not started. No plan yet |
| Phase 4, live push-to-talk + incident case studies | Not started |

**Pending user decision:** integrate `replay-ui` — merge locally, push and open a PR, or keep the branch. The user chose a
PR for phase 1; ask again, don't assume. Base branch is `main` (fork point `c0cca0e`).

## Run it

```bash
source .venv/bin/activate                      # Python 3.14; fastapi, uvicorn, httpx2 already installed
python -m pytest -q                            # 155 tests
uvicorn atcdb.api:app --reload --port 8010     # port 8000 is usually taken by another process on this machine
# open http://127.0.0.1:8010/?recording=528   (27 steps; one known false-positive ALERT at step 17)
python scripts/show_replay.py uwb-atcc_TWR-DM7AI0
python scripts/parse_events.py [--refresh]     # precompute / invalidate the events cache
```

`data/atc.sqlite` is git-ignored; its `events` cache already holds rules-parser output (mostly `window` context).

## What the system is

ATC transcripts → **parser** (typed events: LAND, TAKEOFF, LUAW, CROSS, HOLD_SHORT, HANDOFF, READBACK, ...) → **pure
engine** (runway reservations, compatibility matrix, releases, 300 s staleness, readback checks) → conflicts (RUNWAY or
READBACK, alert or warning) → **replay** timeline → **FastAPI + vanilla JS page**.

No ML model decides conflicts. Today the parser is regex rules and the engine is deterministic. Phase 3 adds a Claude
tool-use parser (Haiku vs Sonnet) that competes with the rules parser on extraction only; the engine stays
deterministic. Whisper ASR transcripts can be replayed (`transcript=asr`) but Whisper decides nothing. The old
logreg/BERT readback models are not used by the engine.

Key modules: `atcdb/engine.py`, `atcdb/parse_rules.py`, `atcdb/parsing.py`, `atcdb/replay.py`, `atcdb/serialize.py`,
`atcdb/api.py`, `atcdb/static/`.

## Settled decisions — do not re-open

- Approach A: deterministic event-sourced engine; parsers swappable and limited to extraction; LLM-as-judge only as an
  evaluation baseline.
- Runways only (no taxiways, no altitudes); replay-first; readback checking unified into the engine.
- `events` cache keyed by `(transcript_id, parser, model, model_version, context, seq)`; failed parses never cached;
  empty parse stored as one NOOP row; on a write race the first writer's parse wins.
- Runway conflicts involving an unidentified callsign are capped at `warning`.
- API: one SQLite connection opened inside each handler (no yield-dependency); 404 unknown recording, 200 with empty
  steps for a recording with no transcripts of that kind, 422 unknown parser/context/transcript kind, 503 when the
  corpus DB is missing; gold replays pin the `human` transcript model; static mount at `/` registered last.
- Evaluation plan (Section 4): human-verified event slice, text-level conflict injection, parser accuracy, context
  ablation (`none`/`role`/`window`), gold vs ASR, conflict detection, LLM-judge comparison.

## Next steps

1. **Integrate phase 2** — present the merge / PR / keep choice (superpowers:finishing-a-development-branch).
2. **Phase 3 design pass, then plan.** Start with superpowers:brainstorming (architectural path, the spec already
   covers most of it) and read **both** plan docs' "review carry-overs" sections first. Things to settle before any LLM
   parse is cached, because the cache persists:
   - per-recording transcript pinning, so `synthetic` gold recordings from conflict injection replay correctly;
   - `get_events` should re-raise when an `IntegrityError` re-read comes back empty;
   - `PARSER_MODELS` as a list of models per parser, a validated `model` query parameter, one capabilities entry per
     parser-model pair, and lazy registration of the Claude parser (importing `atcdb.replay` must not need `anthropic`);
   - a request token in `app.js` so slow replays can't apply out of order;
   - engine tuning: `holding_short` expiry/release, readback-conflict runway for aircraft holding short, per-kind
     staleness (a crossing should not live 300 s).
   **Load the `claude-api` skill before writing any Anthropic API code.**
3. **Phase 4** after phase 3: live endpoint registered inside `create_app` above the static mount; incident case
   studies (Austin 2023, JFK Jan 2023).

## How this user likes to work

- Brainstorm → approved design sections → spec → plan → subagent-driven development with **Sonnet** implementers and
  reviewers, **Opus** for the final whole-branch review; a single fix wave after the final review.
- Before committing a plan, build and run its code in the scratchpad and rebuild the repo from the plan text to prove
  they match; for UI work, smoke-test in a real browser (Playwright tools; screenshots only under `.playwright-mcp/`,
  deleted afterwards).
- Integration (merge / push / PR) is always the user's call.
- `.superpowers/` (SDD ledgers) is git-ignored and deleted when a plan finishes; the rulings from each run are summarised
  in the final message and the carry-overs live in the plan docs.
