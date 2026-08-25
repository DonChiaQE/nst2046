"""Database schema for the ATC corpus. Portable SQL (SQLite now, Postgres later)."""
import sqlite3
from pathlib import Path

TABLES = ["sources", "recordings", "transmissions", "transcripts", "annotations", "phraseology_rules"]

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS sources (
    id          INTEGER PRIMARY KEY,
    name        TEXT NOT NULL UNIQUE,
    kind        TEXT NOT NULL CHECK (kind IN ('corpus', 'feed')),
    licence     TEXT,
    url         TEXT,
    notes       TEXT
);

CREATE TABLE IF NOT EXISTS recordings (
    id              INTEGER PRIMARY KEY,
    source_id       INTEGER NOT NULL REFERENCES sources(id),
    external_id     TEXT NOT NULL,
    airport_icao    TEXT,
    facility        TEXT,
    frequency_mhz   REAL,
    started_at_utc  TEXT,
    path            TEXT,
    notes           TEXT,
    UNIQUE (source_id, external_id)
);

CREATE TABLE IF NOT EXISTS transmissions (
    id              INTEGER PRIMARY KEY,
    recording_id    INTEGER NOT NULL REFERENCES recordings(id),
    external_id     TEXT NOT NULL,
    start_s         REAL,
    end_s           REAL,
    duration_s      REAL,
    speaker_role    TEXT NOT NULL DEFAULT 'unknown'
                    CHECK (speaker_role IN ('pilot', 'controller', 'mixed', 'unknown')),
    speaker_label   TEXT,
    pilot_callsign  TEXT,
    clip_path       TEXT,
    sample_rate     INTEGER,
    pcm_sha1        TEXT UNIQUE,
    split           TEXT CHECK (split IN ('train', 'test') OR split IS NULL),
    UNIQUE (recording_id, external_id)
);
CREATE INDEX IF NOT EXISTS ix_transmissions_recording_time ON transmissions (recording_id, start_s);
CREATE INDEX IF NOT EXISTS ix_transmissions_role ON transmissions (speaker_role);

CREATE TABLE IF NOT EXISTS transcripts (
    id                INTEGER PRIMARY KEY,
    transmission_id   INTEGER NOT NULL REFERENCES transmissions(id),
    kind              TEXT NOT NULL CHECK (kind IN ('gold', 'asr', 'llm')),
    model             TEXT NOT NULL,
    model_version     TEXT NOT NULL DEFAULT '',
    raw_text          TEXT NOT NULL,
    normalized_text   TEXT NOT NULL,
    confidence        REAL,
    words_json        TEXT,
    created_at_utc    TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    UNIQUE (transmission_id, kind, model, model_version)
);
CREATE INDEX IF NOT EXISTS ix_transcripts_transmission_kind ON transcripts (transmission_id, kind);

CREATE TABLE IF NOT EXISTS phraseology_rules (
    id           TEXT PRIMARY KEY,
    document     TEXT NOT NULL,
    section      TEXT,
    category     TEXT NOT NULL,
    pattern      TEXT,
    description  TEXT
);

CREATE TABLE IF NOT EXISTS annotations (
    id              INTEGER PRIMARY KEY,
    transcript_id   INTEGER NOT NULL REFERENCES transcripts(id),
    start_word      INTEGER NOT NULL,
    end_word        INTEGER NOT NULL,
    category        TEXT NOT NULL,
    standard_form   TEXT,
    provenance      TEXT NOT NULL CHECK (provenance IN ('human', 'llm', 'rule')),
    annotator       TEXT,
    rule_id         TEXT REFERENCES phraseology_rules(id),
    notes           TEXT,
    created_at_utc  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    UNIQUE (transcript_id, start_word, end_word, category, provenance, annotator)
);
CREATE INDEX IF NOT EXISTS ix_annotations_transcript ON annotations (transcript_id);
CREATE INDEX IF NOT EXISTS ix_annotations_category ON annotations (category);
"""


def connect(path: Path | str) -> sqlite3.Connection:
    conn = sqlite3.connect(str(path))
    conn.execute("PRAGMA foreign_keys = ON")
    conn.row_factory = sqlite3.Row
    return conn


def init_db(path: Path | str) -> sqlite3.Connection:
    """Create the schema if missing and return an open connection. Safe to call repeatedly."""
    conn = connect(path)
    conn.executescript(SCHEMA_SQL)
    conn.commit()
    return conn
