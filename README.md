# Listening for Contradictions

**Rule-based vs LLM extraction of runway clearances from ATC speech.** NST2046 group project, Don Chia and Jennifer Liu, 2026.

The system turns tower radio audio into runway-conflict alerts in three stages:

1. A Whisper model fine-tuned on ATC audio transcribes each transmission (`atcdb/asr.py`).
2. An extractor turns each line into typed events such as a landing clearance or a crossing. It is either a rules parser (`atcdb/parse_rules.py`) or Claude Sonnet 5 / Haiku 5.5 (`atcdb/parse_llm.py`).
3. A deterministic conflict engine (`atcdb/engine.py`) tracks which runways are reserved and raises an alert when two clearances clash.

Only the extractor changes between conditions, so the project asks whether using an LLM changes what the system catches, what it misses, and what kind of errors it makes.

**Main result.** On human transcripts the two extractors are statistically indistinguishable: recall is 87% (rules) vs 90% (Sonnet 5), and false alarms are 4.1 vs 5.3 per hour, with both paired confidence intervals including zero. On speech-recognition transcripts, Sonnet raises significantly more false alarms (6.4 vs 4.5 per hour). Most false alarms come from runway releases nobody said on the radio, not from extraction errors.

| Where | What |
|---|---|
| [Appendices to the submitted report](https://github.com/DonChiaQE/nst2046/blob/milestone2-appendices/docs/milestone2-appendices.md) | Appendices A–K, on the `milestone2-appendices` branch: divergent cases, prompts, matrices, adjudication, logs, contribution statement |
| [`notebooks/milestone2_pipeline_walkthrough.ipynb`](notebooks/milestone2_pipeline_walkthrough.ipynb) | A runnable walkthrough: one recording through the pipeline, then the headline numbers recomputed live |
| [`docs/results/`](docs/results/) | Every results table: `conflict-eval.md`, `cross-arm-replication.md`, `risk-score.md`, `extraction-pair-events.md`, `wer-baseline.md` |
| [`docs/logs/`](docs/logs/) | The AI-use log and the decision log |
| [`data/eval/conflicts/`](data/eval/conflicts/), [`data/labels/`](data/labels/) | Every arm's stored output, and the human labels and adjudication sheets |

## Reproduce the results (free, no API key)

The paid part of the study (the Claude parses) ran once and is stored, so every number in the report can be recomputed without spending anything. `env -u ANTHROPIC_API_KEY` makes sure nothing can call the API.

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# The corpus database is not on main (size, and it contains UWB-ATCC transcripts). Fetch it once:
git fetch origin runway-watch-app
git cat-file -p origin/runway-watch-app:data/atc.sqlite > data/atc.sqlite

env -u ANTHROPIC_API_KEY python scripts/eval_conflicts.py report     # §4.1, §4.2, §4.4 -> docs/results/conflict-eval.md
env -u ANTHROPIC_API_KEY python scripts/cross_arm_replication.py --markdown > docs/results/cross-arm-replication.md
env -u ANTHROPIC_API_KEY python scripts/risk_score.py                 # §4.3 consequence weights (risk-score.md)
env -u ANTHROPIC_API_KEY python scripts/divergent_cases.py            # Appendix A1
env -u ANTHROPIC_API_KEY python scripts/real_2026_cases.py            # §4.5, the Goa and Houston cases
env -u ANTHROPIC_API_KEY python scripts/pending_sensitivity.py        # confirms every alert has a verdict
env -u ANTHROPIC_API_KEY pytest -q                                    # 430 pass, 2 skip (the live-app smoke tests)
```

The regenerated docs should differ from the committed ones only in their date line.

**The notebook** recomputes the headline tables directly from the committed rows, and its Section 5 needs neither the database nor an API key. To open it:

```bash
pip install notebook ipykernel matplotlib
python -m ipykernel install --user --name nst2046-venv --display-name "NST2046 (.venv)"
env -u ANTHROPIC_API_KEY jupyter notebook notebooks/milestone2_pipeline_walkthrough.ipynb
```

## Build everything from scratch

This rebuilds the database from the public corpora and re-runs the evaluation. The LLM steps call the Claude API and cost money, so always run `--dry-run` first.

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# 1. datasets (~1.6 GB) and the original corpora with speaker roles / metadata
hf download jacktol/atc-dataset --repo-type dataset --local-dir data/jacktol-atc
hf download Jzuluaga/atco2_corpus_1h --repo-type dataset --include "data/*.parquet" --local-dir data/orig-atco2-1h
hf download Jzuluaga/uwb_atcc --repo-type dataset --include "data/*.parquet" --local-dir data/orig-uwb-atcc
mkdir -p data/orig-atco2-1h-src && curl -L -o data/orig-atco2-1h-src/atco2.tgz https://www.replaywell.com/atco2/download/ATCO2-ASRdataset-v1_beta.tgz
tar -xzf data/orig-atco2-1h-src/atco2.tgz -C data/orig-atco2-1h-src

# 2. build the database (data/atc.sqlite)
python scripts/expand_hf_atc.py     # Parquet -> per-clip WAVs + transcripts.csv
python scripts/enrich_hf_atc.py     # + speaker roles, airport/facility/frequency, NER tags
python scripts/load_hf_atc.py       # -> data/atc.sqlite

# 3. ASR baseline (optional, ~3.5 h on an M-series CPU for the test split)
hf download jacktol/whisper-medium.en-fine-tuned-for-ATC-faster-whisper --local-dir data/models/whisper-medium.en-atc-ct2
python scripts/run_asr.py --split test
python scripts/score_wer.py --report docs/results/wer-baseline.md

# 4. conflict engine (phase 1): parse transmissions into runway events, replay a recording, flag conflicts
python scripts/parse_events.py                     # cache rules-parser events for every replayable tower recording
python scripts/show_replay.py uwb-atcc_TWR-DM7AI0  # step through one recording: events, conflicts, runway board

# 5. replay UI: step through a recording in the browser (runway board, transmissions, conflicts, audio)
uvicorn atcdb.api:app --reload                     # then open http://127.0.0.1:8000/?recording=528

# 6. Claude parser (phase 3a): Haiku 5.5 and Sonnet 5 through one forced tool call; needs ANTHROPIC_API_KEY.
#    Without a key the page lists it disabled, and replays already in the cache still work.
python scripts/parse_events.py --parser llm --model claude-sonnet-5 --recording 528 --dry-run   # count and cost first
python scripts/parse_events.py --parser llm --model claude-sonnet-5 --recording 528             # parse and cache

# 7. evaluation, Level 2 (phase 3b-1): synthetic conflicts, every arm, adjudication, results doc.
#    See docs/superpowers/specs/2026-09-29-evaluation-3b1-design.md. Dry-run before every paid run.
python scripts/make_event_sheet.py                  # Level 1 labelling sheets -> data/labels/event_sheet_{A,B}.csv
python scripts/run_asr.py --split train --replayable  # ASR for the eval recordings (~2 h CPU); before injecting
python scripts/inject_conflicts.py                  # store 100 synthetic-conflict recordings; refuses while ASR is
#    incomplete on a chosen original. Never run run_asr.py after injecting: the synthetic copies keep the split, so it
#    would transcribe them and give an edited trigger Whisper's text of the unedited audio.
python scripts/inject_conflicts.py --sheet data/labels/injection_check.csv        # then fill `valid` and
python scripts/inject_conflicts.py --apply-sheet data/labels/injection_check.csv  # record the verdicts
python scripts/eval_conflicts.py run --dry-run      # uncached calls and cost per arm; then without --dry-run
python scripts/eval_conflicts.py adjudicate         # alert verdicts -> data/labels/adjudication_{A,B}.csv
python scripts/eval_conflicts.py report             # -> docs/results/conflict-eval.md

# 8. live demo helper (Runway Watch): the Mac app starts it; see docs/superpowers/specs/2026-10-20-live-demo-app-design.md.
python scripts/bench_whisper.py                     # once: fetch the GPU Whisper weights (1.5 GB) and check the gate
uvicorn atcdb.api:app --host 127.0.0.1 --port 8020  # /api/live/health, /api/live/sessions, ... (Claude needs a key)

pytest   # the live smoke tests skip without ANTHROPIC_API_KEY; run `env -u ANTHROPIC_API_KEY pytest` to spend nothing
```

See `docs/` for the sourcing research and the database design spec.
