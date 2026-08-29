#!/usr/bin/env python3
"""Write the human labelling sheets for readback consistency.

Usage:
    python scripts/make_label_sheet.py [--out data/labels] [--n-consistent 100] [--n-inconsistent 80]
                                       [--n-unmatched 20] [--overlap 50] [--seed 0]

Produces:
  <out>/readback_sheet_A.csv   full sheet (annotator A)
  <out>/readback_sheet_B.csv   first <overlap> rows of A (annotator B), for agreement
Fill `human_label` with: consistent | inconsistent | cant_tell
"""
import argparse
import csv
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from atcdb.readback import sample_label_sheet  # noqa: E402
from atcdb.schema import connect  # noqa: E402

COLUMNS = ["pair_id", "instruction", "readback", "items", "human_label", "notes", "instruction_clip", "readback_clip", "recording_id"]


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", type=Path, default=ROOT / "data/atc.sqlite")
    ap.add_argument("--out", type=Path, default=ROOT / "data/labels")
    ap.add_argument("--n-consistent", type=int, default=100)
    ap.add_argument("--n-inconsistent", type=int, default=80)
    ap.add_argument("--n-unmatched", type=int, default=20)
    ap.add_argument("--overlap", type=int, default=50)
    ap.add_argument("--seed", type=int, default=0)
    args = ap.parse_args()
    rows = sample_label_sheet(connect(args.db), args.n_consistent, args.n_inconsistent, args.n_unmatched, seed=args.seed)
    args.out.mkdir(parents=True, exist_ok=True)
    for name, subset in (("A", rows), ("B", rows[: args.overlap])):
        path = args.out / f"readback_sheet_{name}.csv"
        with path.open("w", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=COLUMNS)
            w.writeheader()
            w.writerows({c: r[c] for c in COLUMNS} for r in subset)
        print(f"wrote {path} ({len(subset)} rows)")


if __name__ == "__main__":
    main()
