"""Score an ASR model's transcripts against gold, with slices and informal-marker survival."""
import sqlite3
from collections import defaultdict

import jiwer

SLICE_KEYS = ["speaker_role", "source_corpus", "facility", "sample_rate"]


def _pairs(conn: sqlite3.Connection, model: str, model_version: str, gold_model: str) -> list[sqlite3.Row]:
    return conn.execute(
        """SELECT g.normalized_text AS ref, a.normalized_text AS hyp, x.speaker_role, x.sample_rate,
                  r.facility, s.name AS source_corpus
           FROM transcripts a
           JOIN transmissions x ON x.id = a.transmission_id
           JOIN recordings r ON r.id = x.recording_id
           JOIN sources s ON s.id = r.source_id
           JOIN transcripts g ON g.transmission_id = x.id AND g.kind = 'gold' AND g.model = ?
           WHERE a.kind = 'asr' AND a.model = ? AND a.model_version = ?""",
        (gold_model, model, model_version)).fetchall()


def _wer(refs: list[str], hyps: list[str]) -> float | None:
    refs2, hyps2 = zip(*[(r, h) for r, h in zip(refs, hyps) if r.strip()]) if any(r.strip() for r in refs) else ([], [])
    return jiwer.wer(list(refs2), list(hyps2)) if refs2 else None


def score_model(conn: sqlite3.Connection, model: str, model_version: str = "", gold_model: str = "human",
                markers: list[str] | None = None) -> dict:
    rows = _pairs(conn, model, model_version, gold_model)
    refs = [r["ref"] for r in rows]
    hyps = [r["hyp"] for r in rows]
    out: dict = {"n": len(rows), "wer": _wer(refs, hyps), "by": {}, "markers": {}}
    for key in SLICE_KEYS:
        groups: dict = defaultdict(lambda: ([], []))
        for r in rows:
            groups[r[key]][0].append(r["ref"])
            groups[r[key]][1].append(r["hyp"])
        out["by"][key] = {str(k) if k is not None else "": {"n": len(g[0]), "wer": _wer(g[0], g[1])}
                          for k, g in groups.items()}
    for m in markers or []:
        gold = sum(r["ref"].split().count(m) for r in rows)
        asr = sum(r["hyp"].split().count(m) for r in rows)
        survived = sum(min(r["ref"].split().count(m), r["hyp"].split().count(m)) for r in rows)
        out["markers"][m] = {"gold": gold, "asr": asr, "survival": (survived / gold) if gold else None}
    return out
