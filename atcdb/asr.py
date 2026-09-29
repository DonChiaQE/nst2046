"""Run an ASR model over transmissions and store the output as `kind='asr'` transcripts.

The model is injected as a callable ``transcriber(clip_path) -> dict`` so the DB logic is
testable without a model. ``make_faster_whisper_transcriber`` builds the real one.
"""
import json
import re
import sqlite3
from pathlib import Path
from typing import Callable

_DIGIT_WORDS = {"0": "zero", "1": "one", "2": "two", "3": "three", "4": "four",
                "5": "five", "6": "six", "7": "seven", "8": "eight", "9": "nine"}

Transcriber = Callable[[Path], dict]


def normalize_asr_text(text: str) -> str:
    """Bring model output onto the gold-transcript convention: lowercase, no punctuation,
    digits spelled out one by one, '.' between digits -> 'decimal', hyphens split."""
    t = (text or "").lower()
    t = re.sub(r"(?<=\d)\.(?=\d)", " decimal ", t)
    t = t.replace("-", " ")
    t = re.sub(r"\d", lambda m: f" {_DIGIT_WORDS[m.group()]} ", t)
    t = re.sub(r"[^\w\s']", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def run_asr(conn: sqlite3.Connection, model_name: str, model_version: str, transcriber: Transcriber,
            project_root: Path, split: str | None = None, limit: int | None = None,
            progress: Callable[[int, int], None] | None = None, recording_ids: list[int] | None = None) -> int:
    """Transcribe every transmission (optionally one split, optionally only the given recordings) lacking an asr
    transcript for this model+version. Returns the number of transcripts written."""
    sql = """SELECT x.id, x.clip_path FROM transmissions x
             WHERE NOT EXISTS (SELECT 1 FROM transcripts t WHERE t.transmission_id = x.id
                               AND t.kind = 'asr' AND t.model = ? AND t.model_version = ?)"""
    params: list = [model_name, model_version]
    if split is not None:
        sql += " AND x.split = ?"
        params.append(split)
    if recording_ids is not None:
        sql += f" AND x.recording_id IN ({','.join('?' * len(recording_ids)) or 'NULL'})"
        params.extend(recording_ids)
    sql += " ORDER BY x.id"
    if limit is not None:
        sql += " LIMIT ?"
        params.append(limit)
    todo = conn.execute(sql, params).fetchall()
    n = 0
    for row in todo:
        result = transcriber(Path(project_root) / row["clip_path"])
        raw = (result.get("text") or "").strip()
        conn.execute(
            """INSERT OR IGNORE INTO transcripts (transmission_id, kind, model, model_version, raw_text,
                                                  normalized_text, confidence, words_json)
               VALUES (?, 'asr', ?, ?, ?, ?, ?, ?)""",
            (row["id"], model_name, model_version, raw, normalize_asr_text(raw),
             result.get("avg_logprob"), json.dumps(result.get("words")) if result.get("words") is not None else None))
        n += 1
        if n % 50 == 0:
            conn.commit()
            if progress:
                progress(n, len(todo))
    conn.commit()
    return n


def make_faster_whisper_transcriber(model_dir: Path | str, device: str = "cpu", compute_type: str = "int8",
                                    beam_size: int = 5, cpu_threads: int = 0) -> Transcriber:
    """Real transcriber backed by faster-whisper (CTranslate2). Decoding/resampling to 16 kHz is
    done by faster-whisper itself. cpu_threads=0 lets CTranslate2 pick."""
    from faster_whisper import WhisperModel  # imported lazily: heavy

    model = WhisperModel(str(model_dir), device=device, compute_type=compute_type, cpu_threads=cpu_threads)

    def transcribe(clip_path: Path) -> dict:
        segments, _info = model.transcribe(str(clip_path), language="en", beam_size=beam_size,
                                           word_timestamps=True, vad_filter=False,
                                           condition_on_previous_text=False)
        segments = list(segments)
        words = [{"word": w.word.strip(), "start": w.start, "end": w.end, "probability": w.probability}
                 for s in segments for w in (s.words or [])]
        text = " ".join(s.text.strip() for s in segments)
        logprobs = [s.avg_logprob for s in segments]
        return {"text": text,
                "avg_logprob": sum(logprobs) / len(logprobs) if logprobs else None,
                "no_speech_prob": max((s.no_speech_prob for s in segments), default=None),
                "words": words}

    return transcribe
