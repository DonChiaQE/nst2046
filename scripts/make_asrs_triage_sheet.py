#!/usr/bin/env python3
"""Build the ASRS incident triage sheets from an ASRS Database Online CSV export.

Usage:
    python scripts/make_asrs_triage_sheet.py data/incidents/asrs-export-2026-09-20.csv \
        [--out data/labels] [--overlap 25] [--limit 100] [--seed 0]

Produces:
  <out>/asrs_triage_A.csv   full sheet (labeller A)
  <out>/asrs_triage_B.csv   first <overlap> rows of A (labeller B), for agreement

Fill, per row (see docs/labelling-protocol.md for definitions):
  space        runway | taxiway | airborne | other
  comm_trace   wrong_readback | query | correction | none | cant_tell
  convertible  yes | no   (does the narrative quote enough phraseology to reconstruct a transmission sequence?)
"""
import argparse
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from atcdb.asrs import read_asrs_export, triage_rows, write_sheets  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("export", type=Path)
    ap.add_argument("--out", type=Path, default=ROOT / "data/labels")
    ap.add_argument("--overlap", type=int, default=25)
    ap.add_argument("--limit", type=int, default=100)
    ap.add_argument("--seed", type=int, default=0)
    args = ap.parse_args()
    rows = triage_rows(read_asrs_export(args.export))
    random.Random(args.seed).shuffle(rows)
    rows = rows[: args.limit]
    for path in write_sheets(rows, args.out, args.overlap):
        print(f"wrote {path}")


if __name__ == "__main__":
    main()
