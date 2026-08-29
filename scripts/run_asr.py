#!/usr/bin/env python3
"""Transcribe transmissions with a faster-whisper model and store `kind='asr'` transcripts.

Usage:
    python scripts/run_asr.py [--split test] [--limit N] [--model-dir data/models/whisper-medium.en-atc-ct2]
                              [--model-name whisper-medium.en-atc] [--model-version jacktol-ct2]
                              [--device cpu] [--compute-type int8] [--db data/atc.sqlite]

Idempotent per (model-name, model-version): re-running only transcribes what is missing.
"""
import argparse
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from atcdb.asr import make_faster_whisper_transcriber, run_asr  # noqa: E402
from atcdb.schema import init_db  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", type=Path, default=ROOT / "data/atc.sqlite")
    ap.add_argument("--model-dir", type=Path, default=ROOT / "data/models/whisper-medium.en-atc-ct2")
    ap.add_argument("--model-name", default="whisper-medium.en-atc")
    ap.add_argument("--model-version", default="jacktol-ct2")
    ap.add_argument("--split", default="test")
    ap.add_argument("--limit", type=int)
    ap.add_argument("--device", default="cpu")
    ap.add_argument("--compute-type", default="int8")
    ap.add_argument("--cpu-threads", type=int, default=0, help="0 = let CTranslate2 choose")
    ap.add_argument("--beam-size", type=int, default=5)
    args = ap.parse_args()

    conn = init_db(args.db)
    transcriber = make_faster_whisper_transcriber(args.model_dir, device=args.device, compute_type=args.compute_type,
                                                  beam_size=args.beam_size, cpu_threads=args.cpu_threads)
    t0 = time.time()

    def progress(done, total):
        rate = done / (time.time() - t0)
        print(f"  {done}/{total} clips  ({rate:.1f} clips/s, ~{(total - done) / rate / 60:.0f} min left)", flush=True)

    n = run_asr(conn, args.model_name, args.model_version, transcriber, ROOT, split=args.split, limit=args.limit, progress=progress)
    print(f"wrote {n} asr transcripts for {args.model_name}/{args.model_version} in {time.time() - t0:.0f}s")


if __name__ == "__main__":
    main()
