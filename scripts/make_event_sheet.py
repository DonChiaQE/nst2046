#!/usr/bin/env python3
"""Write the Level 1 event labelling sheets (spec 2026-09-29-evaluation-3b1-design.md, section 8).

Usage:
    python scripts/make_event_sheet.py [--out data/labels] [--n 200] [--overlap 50] [--seed 0] [--db data/atc.sqlite]
    python scripts/make_event_sheet.py --check data/labels/event_sheet_A.csv

Produces:
  <out>/event_sheet_A.csv   full sheet (annotator A)
  <out>/event_sheet_B.csv   first <overlap> rows of A (annotator B), for Cohen's kappa
Fill `events` with one event per line (see atcdb/event_labels.py), or `noop`. `--check` reads a filled sheet back and
lists every cell that does not parse; unfilled rows are counted, not errors.
"""
import argparse
import csv
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from atcdb.event_labels import COLUMNS, parse_event_cell, sample_event_sheet  # noqa: E402
from atcdb.schema import connect  # noqa: E402


def check(path: Path) -> int:
    """Print the unparseable cells of a filled sheet; returns how many there are."""
    bad = blank = 0
    with path.open(newline="") as fh:
        for row in csv.DictReader(fh):
            if not row["events"].strip():
                blank += 1
                continue
            try:
                parse_event_cell(row["events"])
            except ValueError as e:
                bad += 1
                print(f"row {row['row_id']}: {e}")
    print(f"{path}: {bad} unparseable cells, {blank} rows not yet labelled")
    return bad


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", type=Path, default=ROOT / "data/atc.sqlite")
    ap.add_argument("--out", type=Path, default=ROOT / "data/labels")
    ap.add_argument("--n", type=int, default=200)
    ap.add_argument("--overlap", type=int, default=50)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--check", type=Path, help="validate a filled sheet instead of writing new ones")
    args = ap.parse_args()
    if args.check:
        sys.exit(1 if check(args.check) else 0)
    existing = [p for p in (args.out / "event_sheet_A.csv", args.out / "event_sheet_B.csv") if p.exists()]
    if existing:
        sys.exit(f"{existing[0]} exists; it may hold labels. Move it away first.")
    rows = sample_event_sheet(connect(args.db), n=args.n, seed=args.seed)
    args.out.mkdir(parents=True, exist_ok=True)
    for name, subset in (("A", rows), ("B", rows[:args.overlap])):
        path = args.out / f"event_sheet_{name}.csv"
        with path.open("w", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=COLUMNS)
            w.writeheader()
            w.writerows(subset)
        print(f"wrote {path} ({len(subset)} rows)")


if __name__ == "__main__":
    main()
