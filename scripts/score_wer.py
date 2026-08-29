#!/usr/bin/env python3
"""Score an ASR model against gold transcripts; print tables and optionally write a markdown report.

Usage:
    python scripts/score_wer.py [--model whisper-medium.en-atc] [--model-version jacktol-ct2]
                                [--db data/atc.sqlite] [--report docs/results/<file>.md]
"""
import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from atcdb.schema import connect  # noqa: E402
from atcdb.wer import score_model  # noqa: E402

# informal / confusion markers whose survival through ASR we care about
MARKERS = ["ok", "okay", "yeah", "bye", "hello", "thank", "thanks", "good", "please", "sorry",
           "say", "again", "confirm", "correction", "[hes]"]


def fmt(w):
    return "-" if w is None else f"{100 * w:.1f}%"


def render(res: dict, model: str, version: str) -> str:
    lines = [f"# WER: {model} / {version}", "",
             f"Scored transmissions: **{res['n']}** — overall WER **{fmt(res['wer'])}**", ""]
    for key, groups in res["by"].items():
        lines += [f"## by {key}", "", "| value | n | WER |", "|---|---:|---:|"]
        for k, g in sorted(groups.items(), key=lambda kv: -kv[1]["n"]):
            lines.append(f"| {k or '(none)'} | {g['n']} | {fmt(g['wer'])} |")
        lines.append("")
    lines += ["## marker survival (gold occurrences reproduced by ASR in the same transmission)", "",
              "| word | gold | asr | survival |", "|---|---:|---:|---:|"]
    for m, s in res["markers"].items():
        lines.append(f"| `{m}` | {s['gold']} | {s['asr']} | {fmt(s['survival'])} |")
    return "\n".join(lines) + "\n"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", type=Path, default=ROOT / "data/atc.sqlite")
    ap.add_argument("--model", default="whisper-medium.en-atc")
    ap.add_argument("--model-version", default="jacktol-ct2")
    ap.add_argument("--report", type=Path)
    args = ap.parse_args()
    res = score_model(connect(args.db), args.model, args.model_version, markers=MARKERS)
    text = render(res, args.model, args.model_version)
    print(text)
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(text)
        print(f"report written to {args.report}")


if __name__ == "__main__":
    main()
