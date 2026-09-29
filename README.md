# nst2046

ATC (air traffic control) speech → transcripts → database, for analysing potentially ambiguous / non-standard phraseology. The conflict engine (`atcdb/engine.py`) turns parsed clearances into runway reservations and flags incompatible ones; see `docs/superpowers/specs/2026-09-12-conflict-engine-design.md`.

## Setup

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

# 6. Claude parser (phase 3a): Haiku 4.5 and Sonnet 5 through one forced tool call; needs ANTHROPIC_API_KEY.
#    Without a key the page lists it disabled, and replays already in the cache still work.
python scripts/parse_events.py --parser llm --model claude-sonnet-5 --recording 528 --dry-run   # count and cost first
python scripts/parse_events.py --parser llm --model claude-sonnet-5 --recording 528             # parse and cache

pytest   # 215 tests; the live smoke test skips without ANTHROPIC_API_KEY
```

See `docs/` for the sourcing research and the database design spec.
