"""Load data/jacktol-atc/transcripts_enriched.csv (see scripts/enrich_hf_atc.py) into the corpus DB.

Idempotent: every insert is keyed on a natural unique key, so re-running updates in place.
"""
import csv
import sqlite3
from collections import Counter
from pathlib import Path

from atcdb.audio import pcm_sha1
from atcdb.ner import parse_ner_text

SOURCES = {
    "atco2-1h": dict(kind="corpus", licence="MIT (ATCO2 test-set-1h, free subset)",
                     url="https://huggingface.co/datasets/Jzuluaga/atco2_corpus_1h"),
    "uwb-atcc": dict(kind="corpus", licence="Free for research (University of West Bohemia)",
                     url="https://huggingface.co/datasets/Jzuluaga/uwb_atcc"),
}


def _none_if_blank(v: str | None):
    return v if v not in (None, "") else None


def _float_or_none(v: str | None):
    v = _none_if_blank(v)
    return float(v) if v is not None else None


def _upsert_source(conn: sqlite3.Connection, name: str) -> int:
    meta = SOURCES.get(name, dict(kind="corpus", licence=None, url=None))
    conn.execute("INSERT OR IGNORE INTO sources (name, kind, licence, url) VALUES (?, ?, ?, ?)",
                 (name, meta["kind"], meta["licence"], meta["url"]))
    return conn.execute("SELECT id FROM sources WHERE name = ?", (name,)).fetchone()[0]


def _upsert_recording(conn: sqlite3.Connection, source_id: int, row: dict) -> int:
    conn.execute(
        """INSERT INTO recordings (source_id, external_id, airport_icao, facility, frequency_mhz, started_at_utc)
           VALUES (?, ?, ?, ?, ?, ?)
           ON CONFLICT (source_id, external_id) DO UPDATE SET
               airport_icao = excluded.airport_icao, facility = excluded.facility,
               frequency_mhz = excluded.frequency_mhz, started_at_utc = excluded.started_at_utc""",
        (source_id, row["recording_id"], _none_if_blank(row["airport_icao"]), _none_if_blank(row["facility"]),
         _float_or_none(row["frequency_mhz"]), _none_if_blank(row["recorded_at_utc"])))
    return conn.execute("SELECT id FROM recordings WHERE source_id = ? AND external_id = ?",
                        (source_id, row["recording_id"])).fetchone()[0]


def _upsert_transmission(conn: sqlite3.Connection, recording_id: int, row: dict, clip_path: str, sha1: str, sr: int) -> int:
    conn.execute(
        """INSERT INTO transmissions (recording_id, external_id, start_s, end_s, duration_s, speaker_role, speaker_label,
                                      pilot_callsign, clip_path, sample_rate, pcm_sha1, split)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT (recording_id, external_id) DO UPDATE SET
               start_s = excluded.start_s, end_s = excluded.end_s, duration_s = excluded.duration_s,
               speaker_role = excluded.speaker_role, speaker_label = excluded.speaker_label,
               pilot_callsign = excluded.pilot_callsign, clip_path = excluded.clip_path,
               sample_rate = excluded.sample_rate, pcm_sha1 = excluded.pcm_sha1, split = excluded.split""",
        (recording_id, row["source_id"], _float_or_none(row["seg_start_s"]), _float_or_none(row["seg_end_s"]),
         _float_or_none(row["duration_s"]), row["speaker_role"] or "unknown", _none_if_blank(row["speaker_label"]),
         _none_if_blank(row["pilot_callsign"]), clip_path, sr, sha1, _none_if_blank(row["split"])))
    return conn.execute("SELECT id FROM transmissions WHERE recording_id = ? AND external_id = ?",
                        (recording_id, row["source_id"])).fetchone()[0]


def _upsert_gold_transcript(conn: sqlite3.Connection, transmission_id: int, text: str, model: str = "human") -> int:
    conn.execute(
        """INSERT OR IGNORE INTO transcripts (transmission_id, kind, model, model_version, raw_text, normalized_text)
           VALUES (?, 'gold', ?, '', ?, ?)""", (transmission_id, model, text, text))
    return conn.execute("SELECT id FROM transcripts WHERE transmission_id = ? AND kind = 'gold' AND model = ?",
                        (transmission_id, model)).fetchone()[0]


def _insert_ner_annotations(conn: sqlite3.Connection, transcript_id: int, spans: list) -> int:
    n = 0
    for start, end, category in spans:
        cur = conn.execute(
            """INSERT OR IGNORE INTO annotations (transcript_id, start_word, end_word, category, provenance, annotator)
               VALUES (?, ?, ?, ?, 'human', 'atco2')""", (transcript_id, start, end, category))
        n += cur.rowcount
    return n


def load_enriched_csv(conn: sqlite3.Connection, csv_path: Path, project_root: Path) -> dict:
    """Load every row of the enriched CSV. Returns a Counter of rows touched per table."""
    csv_path, project_root = Path(csv_path), Path(project_root).resolve()
    stats: Counter = Counter()
    source_ids: dict[str, int] = {}
    with csv_path.open(newline="") as fh:
        for row in csv.DictReader(fh):
            name = row["source_corpus"]
            if name not in source_ids:
                source_ids[name] = _upsert_source(conn, name)
                stats["sources"] += 1
            recording_id = _upsert_recording(conn, source_ids[name], row)
            wav = (csv_path.parent / row["path"]).resolve()
            sha1, sr = pcm_sha1(wav.read_bytes())
            clip_path = wav.relative_to(project_root).as_posix() if wav.is_relative_to(project_root) else str(wav)
            transmission_id = _upsert_transmission(conn, recording_id, row, clip_path, sha1, sr)
            stats["transmissions"] += 1
            _upsert_gold_transcript(conn, transmission_id, " ".join(row["text"].split()))
            stats["transcripts"] += 1
            if row.get("ner_text"):
                # The XML text is tokenised differently from jacktol's text (hyphens, hesitation markers,
                # language tags), so it gets its own gold transcript and the spans index THAT text.
                xml_text, spans = parse_ner_text(row["ner_text"])
                xml_transcript_id = _upsert_gold_transcript(conn, transmission_id, xml_text, model="atco2-xml")
                stats["transcripts"] += 1
                stats["annotations"] += _insert_ner_annotations(conn, xml_transcript_id, spans)
    conn.commit()
    return dict(stats)
