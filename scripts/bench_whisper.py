#!/usr/bin/env python3
"""Week-1 gate for the live demo app (spec 2026-10-20-live-demo-app-design.md, Section 9): is Whisper on the GPU fast
enough, and does it read clips at least as accurately as the evaluation's CTranslate2 model?

Usage:
    python scripts/bench_whisper.py [--clips 20] [--model-dir data/models/whisper-medium.en-atc-hf]

Downloads the Hugging Face weights into --model-dir if they are missing (about 1.5 GB, free), then transcribes the first
--clips test-split clips of 2 to 8 s with both models, after one warm-up call. Prints each clip's GPU time and both
texts beside the human transcript, then the gate: median GPU time at most 2.0 s, and a word error rate against the human
transcripts at most 2 points above the CTranslate2 model's. (Planning, 2026-10-20: the spec's first gate, the same text
as the CTranslate2 model on 18 of 20 clips, measured decoding differences rather than accuracy: on the clips where the
two disagreed, the GPU model was as often right as wrong.)
"""
import argparse
import csv
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import jiwer  # noqa: E402
import soundfile as sf  # noqa: E402

from atcdb.asr import (HF_WHISPER_REPO, hf_whisper_transcriber, load_hf_whisper, make_faster_whisper_transcriber,  # noqa: E402
                       normalize_asr_text)

MAX_MEDIAN_S = 2.0
MAX_WER_GAP = 0.02   # GPU word error rate at most 2 points above the CTranslate2 model's


def test_clips(clips_dir: Path, n: int) -> list[Path]:
    """The first `n` clips, in name order, lasting 2 to 8 s (a typical transmission)."""
    out = []
    for p in sorted(clips_dir.glob("*.wav")):
        if 2.0 <= sf.info(str(p)).duration <= 8.0:
            out.append(p)
            if len(out) == n:
                break
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--clips", type=int, default=20)
    ap.add_argument("--model-dir", type=Path, default=ROOT / "data/models/whisper-medium.en-atc-hf")
    ap.add_argument("--ct2-dir", type=Path, default=ROOT / "data/models/whisper-medium.en-atc-ct2")
    ap.add_argument("--clips-dir", type=Path, default=ROOT / "data/jacktol-atc/clips/test")
    ap.add_argument("--transcripts", type=Path, default=ROOT / "data/jacktol-atc/transcripts.csv")
    ap.add_argument("--device", default="mps")
    args = ap.parse_args()

    if not (args.model_dir / "model.safetensors").exists():
        from huggingface_hub import snapshot_download
        print(f"downloading {HF_WHISPER_REPO} into {args.model_dir} (about 1.5 GB)", flush=True)
        snapshot_download(HF_WHISPER_REPO, local_dir=str(args.model_dir))
    clips = test_clips(args.clips_dir, args.clips)
    if not clips:
        sys.exit(f"no 2 to 8 s clips in {args.clips_dir}")
    with args.transcripts.open(newline="") as fh:
        human = {Path(r["path"]).name: normalize_asr_text(r["text"]) for r in csv.DictReader(fh)}

    t0 = time.perf_counter()
    gpu = hf_whisper_transcriber(*load_hf_whisper(args.model_dir, args.device), device=args.device)
    print(f"GPU model loaded in {time.perf_counter() - t0:.1f} s", flush=True)
    cpu = make_faster_whisper_transcriber(args.ct2_dir)
    gpu(clips[0])   # warm-up: the first call compiles the GPU kernels

    times, refs, gpus, cpus = [], [], [], []
    for clip in clips:
        t0 = time.perf_counter()
        g = normalize_asr_text(gpu(clip)["text"])
        times.append(time.perf_counter() - t0)
        c = normalize_asr_text(cpu(clip)["text"])
        refs.append(human[clip.name])
        gpus.append(g)
        cpus.append(c)
        print(f"{clip.name}  {sf.info(str(clip)).duration:4.1f} s audio  {times[-1]:4.2f} s GPU  "
              f"{'same' if g == c else 'differs'}\n    human: {refs[-1]}\n    gpu:   {g}\n    cpu:   {c}", flush=True)
    median = statistics.median(times)
    wer_gpu, wer_cpu = jiwer.wer(refs, gpus), jiwer.wer(refs, cpus)
    ok = median <= MAX_MEDIAN_S and wer_gpu <= wer_cpu + MAX_WER_GAP
    print(f"\nmedian GPU time {median:.2f} s (gate {MAX_MEDIAN_S} s); word error rate GPU {wer_gpu:.1%}, "
          f"CTranslate2 {wer_cpu:.1%} (gate: GPU at most {MAX_WER_GAP:.0%} above); same text on "
          f"{sum(g == c for g, c in zip(gpus, cpus))}/{len(clips)}; gate {'PASSED' if ok else 'FAILED'}")


if __name__ == "__main__":
    main()
