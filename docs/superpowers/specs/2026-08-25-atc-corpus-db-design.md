# ATC corpus database — design (2026-08-25)

Status: approved in chat (SQLite now, Postgres-portable schema; schema + loader only in this pass).

## Purpose
One store for every ATC transmission the project touches — public corpora now, LiveATC
captures later — with gold/ASR/LLM transcripts and span-level phraseology annotations,
so the "casual / non-standard phraseology" work can query by speaker role, facility,
airport and time.

## Decisions
- **SQLite** file at `data/atc.sqlite` for now. Schema uses only portable SQL (TEXT/INTEGER/REAL,
  no SQLite-specific types, ISO-8601 timestamps, JSON in TEXT) so a Postgres move is mechanical.
- **Audio stays on disk**; the DB stores paths relative to the project root plus a sha1 of the
  decoded PCM (dedup key across sources).
- **Transcripts are versioned by `kind` + `model`**: gold (human), asr (model id), llm (model id +
  prompt version). Never overwrite; add rows.
- **Annotations are spans over a transcript's tokens** (word index start/end inclusive) with a
  category, an optional standard-form rewrite, and a provenance (`human` | `llm` | `rule`).
- The NST loader is **idempotent**: re-running upserts by natural keys and never duplicates.

## Schema
```
sources        id, name (unique), kind ('corpus'|'feed'), licence, url, notes
recordings     id, source_id, external_id (unique per source), airport_icao, facility,
               frequency_mhz, started_at_utc, path, notes
transmissions  id, recording_id, external_id (unique per recording), start_s, end_s, duration_s,
               speaker_role ('pilot'|'controller'|'mixed'|'unknown'), speaker_label,
               pilot_callsign, clip_path, sample_rate, pcm_sha1 (unique), split ('train'|'test'|NULL)
transcripts    id, transmission_id, kind ('gold'|'asr'|'llm'), model, model_version,
               raw_text, normalized_text, confidence, words_json, created_at_utc
               unique (transmission_id, kind, model, model_version)
annotations    id, transcript_id, start_word, end_word, category, standard_form,
               provenance ('human'|'llm'|'rule'), annotator, rule_id, notes, created_at_utc
phraseology_rules  id (text, e.g. 'FAA-7110.65-2-4-17'), document, section, category,
               pattern, description
```
Indexes: transmissions(recording_id, start_s); transmissions(speaker_role);
transcripts(transmission_id, kind); annotations(transcript_id); annotations(category).

## Loader (`scripts/load_hf_atc.py`)
Input `data/jacktol-atc/transcripts_enriched.csv` (+ clip WAVs).
- sources: `atco2-1h`, `uwb-atcc` (from `source_corpus`).
- recordings: one per `recording_id`, carrying airport/facility/frequency/recorded_at.
- transmissions: one per clip; external_id = `source_id`; pcm_sha1 computed from the WAV.
- transcripts: one `gold` row per clip (raw_text = normalized_text = CSV `text`, model='human').
- **ATCO2 rows with `ner_text` get a second gold transcript, model='atco2-xml'**, holding the
  XML-derived text. Reason (found during implementation): the XML tokenises differently from
  jacktol's text (`x-ray`/`xray`, `val-d'annivier`/`val d annivier`, `koreanair`/`korean air`) and
  keeps markers jacktol stripped, so word-index spans must index the XML text, not jacktol's.
- annotations attach to the `atco2-xml` transcript: NER categories callsign|command|value|unnamed,
  plus marker categories derived from the XML: `hesitation` (`[hes]`, kept as the token `[hes]`),
  `nonenglish` (from `[NE-French]…[/NE]`-style regions, one span per region), `noise`,
  `speaker_change` (`[spk]`), `crosstalk` (`[XT]`), `unintelligible` (`[ukn]`).
  Provenance 'human', annotator 'atco2'.

## Tests (`tests/test_db.py`, `tests/test_loader.py`)
- schema creates on an empty DB and is idempotent.
- loader on a 6-row fixture CSV: correct counts per table; re-run → identical counts.
- ATCO2 NER tag parsing → correct word spans on a known example; tag stripping yields the
  gold text.
- A query reconstructs a full recording's exchange in time order with roles.

## Result of this pass (2026-08-25)
Loaded: 2 sources, 3,200 recordings, 14,795 transmissions, 15,660 transcripts (14,795 human +
865 atco2-xml), 1,090 annotations. 20 tests green. DB: `data/atc.sqlite` (8.5 MB).

## Out of scope (this pass)
ASR runs, LLM labelling, LiveATC ingestion, Postgres deployment, web UI.
