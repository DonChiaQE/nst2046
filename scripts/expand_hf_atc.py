#!/usr/bin/env python3
"""Expand the jacktol/atc-dataset Parquet files into per-clip WAVs + transcripts.csv.

Usage:
    python scripts/expand_hf_atc.py [--src data/jacktol-atc/data] [--out data/jacktol-atc]

Output layout:
    <out>/clips/<split>/<split>_<index:05d>.wav
    <out>/transcripts.csv   columns: split, clip_id, path, sample_rate, duration_s, text

Audio bytes are written as-is (they are already WAV); soundfile is only used to
read sample rate / duration for the CSV.
"""
import argparse
import csv
import io
import sys
from pathlib import Path

import pyarrow.parquet as pq
import soundfile as sf


def split_of(parquet_path: Path) -> str:
    # e.g. train-00000-of-00002.parquet -> "train"
    return parquet_path.name.split("-")[0]


def expand(src: Path, out: Path) -> dict:
    parquets = sorted(src.glob("*.parquet"))
    if not parquets:
        sys.exit(f"no .parquet files found in {src}")

    csv_path = out / "transcripts.csv"
    counts: dict[str, int] = {}
    next_index: dict[str, int] = {}

    with csv_path.open("w", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(["split", "clip_id", "path", "sample_rate", "duration_s", "text"])

        for parquet in parquets:
            split = split_of(parquet)
            clip_dir = out / "clips" / split
            clip_dir.mkdir(parents=True, exist_ok=True)
            pf = pq.ParquetFile(parquet)
            print(f"{parquet.name}: {pf.metadata.num_rows} rows -> {clip_dir}", flush=True)

            for batch in pf.iter_batches(batch_size=512, columns=["audio", "text"]):
                for audio, text in zip(batch.column("audio").to_pylist(), batch.column("text").to_pylist()):
                    data = audio["bytes"]
                    if not data.startswith(b"RIFF"):
                        sys.exit(f"unexpected audio format in {parquet.name} (not RIFF/WAV)")
                    idx = next_index.get(split, 0)
                    next_index[split] = idx + 1
                    clip_id = f"{split}_{idx:05d}"
                    wav_path = clip_dir / f"{clip_id}.wav"
                    wav_path.write_bytes(data)
                    info = sf.info(io.BytesIO(data))
                    writer.writerow([
                        split, clip_id, wav_path.relative_to(out).as_posix(),
                        info.samplerate, f"{info.duration:.3f}", (text or "").strip(),
                    ])
                    counts[split] = counts.get(split, 0) + 1
    return counts


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--src", type=Path, default=Path("data/jacktol-atc/data"))
    ap.add_argument("--out", type=Path, default=Path("data/jacktol-atc"))
    args = ap.parse_args()
    counts = expand(args.src, args.out)
    for split, n in counts.items():
        print(f"{split}: {n} clips")
    print(f"wrote {args.out / 'transcripts.csv'}")


if __name__ == "__main__":
    main()
