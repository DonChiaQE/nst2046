#!/usr/bin/env python3
"""Join speaker role + recording metadata from the original ATCO2-1h and UWB-ATCC
corpora onto the jacktol/atc-dataset clips.

Matching to the HF originals: sha1 of decoded int16 PCM (robust to WAV-header
differences), falling back to (normalised text, duration rounded to 10 ms).

Speaker roles:
  * UWB-ATCC: encoded in the id suffix  _PI (pilot) / _AT (controller) / _PIAT (both).
  * ATCO2-1h: the letter in the HF id is a per-recording speaker index, NOT a role.
    Roles come from the original tarball's XML (<speaker_label>): "ATCO ..." =
    controller, a callsign = pilot, "UNK-n"/blank = unknown, "Crosstalk" = mixed.

Usage:
    python scripts/enrich_hf_atc.py

Reads:  data/jacktol-atc/transcripts.csv, data/jacktol-atc/clips/**.wav
        data/orig-atco2-1h/data/*.parquet, data/orig-uwb-atcc/data/*.parquet
        data/orig-atco2-1h-src/ATCO2-ASRdataset-v1_beta/DATA/*.xml
Writes: data/jacktol-atc/transcripts_enriched.csv
"""
import csv
import glob
import re
import sys
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict
from pathlib import Path

import pyarrow.parquet as pq

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from atcdb.audio import pcm_sha1 as _pcm_sha1  # noqa: E402

ROOT = Path("data/jacktol-atc")
ATCO2_XML_DIR = Path("data/orig-atco2-1h-src/ATCO2-ASRdataset-v1_beta/DATA")

ATCO2_RE = re.compile(
    r"^atco2_test-set-1h_(?P<rec>(?P<icao>[A-Z]{4})_(?P<name>[A-Za-z]+)_(?P<facility>.+?)_"
    r"(?P<f1>\d+)_(?P<f2>\d+)MHz_(?P<date>\d{8})_(?P<time>\d{6}))-(?P<spk>[A-Z]*)__(?P<s>\d+)-(?P<e>\d+)$"
)
UWB_RE = re.compile(r"^uwb-atcc_(?P<facility>[A-Z]+)-(?P<rec>[A-Za-z0-9]+)_(?P<s>\d+)_(?P<e>\d+)_(?P<role>PI|AT|PIAT)$")
UWB_ROLE = {"PI": "pilot", "AT": "controller", "PIAT": "mixed"}
UWB_FACILITY = {"TWR": "Tower", "ACCU": "Area Control (ACC)", "APP": "Approach"}

EXTRA = ["match_method", "source_corpus", "source_id", "speaker_role", "speaker_label", "pilot_callsign",
         "speaker_index", "airport_icao", "airport_name", "facility", "frequency_mhz", "recorded_at_utc",
         "recording_id", "seg_start_s", "seg_end_s", "orig_text", "ner_text", "correct_transcript"]


def pcm_hash(wav_bytes: bytes) -> str:
    return _pcm_sha1(wav_bytes)[0]


def norm_text(t: str) -> str:
    return " ".join((t or "").lower().split())


def role_from_label(label: str) -> str:
    l = label.strip()
    if not l or l.upper().startswith("UNK"):
        return "unknown"
    if l.lower().startswith("atco"):
        return "controller"
    if l.lower() == "crosstalk":
        return "mixed"
    return "pilot"  # label is the aircraft callsign


def load_atco2_xml() -> dict:
    """recording name -> list of segments with role info from the original XML."""
    segs = defaultdict(list)
    for f in ATCO2_XML_DIR.glob("*.xml"):
        for seg in ET.parse(f).getroot().iter("segment"):
            label = (seg.findtext("speaker_label") or "").strip()
            role = role_from_label(label)
            segs[f.stem].append({
                "start": float(seg.findtext("start") or 0), "end": float(seg.findtext("end") or 0),
                "speaker_index": (seg.findtext("speaker") or "").strip(),
                "speaker_label": label, "speaker_role": role,
                "pilot_callsign": label if role == "pilot" else "",
                "ner_text": (seg.findtext("text") or "").strip(),
                "correct_transcript": (seg.findtext("tags/correct_transcript") or "").strip(),
            })
    return segs


def best_xml_segment(segs: list, spk: str, s: float, e: float) -> dict | None:
    """Pick the XML segment with the greatest time overlap; prefer the same speaker index."""
    best, best_ov = None, 0.0
    for cand in segs:
        ov = min(e, cand["end"]) - max(s, cand["start"])
        if ov <= 0:
            continue
        score = ov + (1.0 if cand["speaker_index"] == spk else 0.0)
        if score > best_ov:
            best, best_ov = cand, score
    return best


def parse_meta(source: str, sid: str, atco2_xml: dict) -> dict:
    if source == "atco2-1h":
        m = ATCO2_RE.match(sid)
        if not m:
            return {"speaker_role": "unknown"}
        g = m.groupdict()
        s, e = int(g["s"]) / 100, int(g["e"]) / 100
        meta = {
            "speaker_role": "unknown", "speaker_index": g["spk"],
            "airport_icao": g["icao"], "airport_name": g["name"].title(),
            "facility": g["facility"].replace("-", " / "),
            "frequency_mhz": f"{int(g['f1'])}.{g['f2']}",
            "recorded_at_utc": f"{g['date'][:4]}-{g['date'][4:6]}-{g['date'][6:]}T{g['time'][:2]}:{g['time'][2:4]}:{g['time'][4:]}",
            "recording_id": g["rec"], "seg_start_s": f"{s:.2f}", "seg_end_s": f"{e:.2f}",
        }
        x = best_xml_segment(atco2_xml.get(g["rec"], []), g["spk"], s, e)
        if x:
            meta.update({k: x[k] for k in ["speaker_role", "speaker_label", "pilot_callsign", "ner_text", "correct_transcript"]})
        return meta
    m = UWB_RE.match(sid)
    if not m:
        return {"speaker_role": "unknown"}
    g = m.groupdict()
    return {
        "speaker_role": UWB_ROLE[g["role"]],
        "airport_name": "Czech airspace (undisclosed)",
        "facility": UWB_FACILITY.get(g["facility"], g["facility"]),
        "recording_id": f"uwb-atcc_{g['facility']}-{g['rec']}",
        "seg_start_s": f"{int(g['s'])/100:.2f}", "seg_end_s": f"{int(g['e'])/100:.2f}",
    }


def load_originals(atco2_xml: dict) -> tuple[dict, dict]:
    by_hash, by_text_dur = {}, {}
    for source, pattern in [("atco2-1h", "data/orig-atco2-1h/data/*.parquet"),
                            ("uwb-atcc", "data/orig-uwb-atcc/data/*.parquet")]:
        n = 0
        for f in sorted(glob.glob(pattern)):
            pf = pq.ParquetFile(f)
            for batch in pf.iter_batches(batch_size=256, columns=["id", "audio", "text", "duration"]):
                audio_bytes = [a["bytes"] for a in batch.column("audio").to_pylist()]
                for sid, b, text, dur in zip(batch.column("id").to_pylist(), audio_bytes,
                                             batch.column("text").to_pylist(), batch.column("duration").to_pylist()):
                    rec = {"source_corpus": source, "source_id": sid, "orig_text": norm_text(text),
                           **parse_meta(source, sid, atco2_xml)}
                    by_hash.setdefault(pcm_hash(b), rec)
                    by_text_dur.setdefault((norm_text(text), round(float(dur), 2)), rec)
                    n += 1
        print(f"loaded {n} originals from {source}", flush=True)
    return by_hash, by_text_dur


def main() -> None:
    atco2_xml = load_atco2_xml()
    print(f"loaded ATCO2 XML for {len(atco2_xml)} recordings, {sum(map(len, atco2_xml.values()))} segments")
    by_hash, by_text_dur = load_originals(atco2_xml)
    rows = list(csv.DictReader((ROOT / "transcripts.csv").open()))
    stats = Counter()
    out = ROOT / "transcripts_enriched.csv"
    with out.open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()) + EXTRA)
        w.writeheader()
        for r in rows:
            rec = by_hash.get(pcm_hash((ROOT / r["path"]).read_bytes()))
            method = "pcm_hash" if rec else None
            if rec is None:
                rec = by_text_dur.get((norm_text(r["text"]), round(float(r["duration_s"]), 2)))
                method = "text+duration" if rec else "unmatched"
            stats[method] += 1
            row = {**r, **{k: "" for k in EXTRA}, "match_method": method}
            if rec:
                row.update({k: rec.get(k, "") for k in EXTRA if k in rec})
                if rec["orig_text"] != norm_text(r["text"]):
                    stats["text_differs_from_original"] += 1
            w.writerow(row)
    print("match stats:", dict(stats))
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
