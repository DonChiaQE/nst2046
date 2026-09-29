#!/usr/bin/env python3
"""Report inter-rater agreement between two labelling sheets.

Usage:
    python scripts/score_agreement.py SHEET_A SHEET_B --key pair_id --columns human_label
    python scripts/score_agreement.py data/labels/asrs_triage_A.csv data/labels/asrs_triage_B.csv \
        --key acn --columns space,comm_trace,convertible

Prints n, Cohen's kappa, raw agreement and the label distribution per column. Rows blank in either
sheet, or missing from one sheet, are excluded.
"""
import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from atcdb.agreement import agreement_report  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("sheet_a", type=Path)
    ap.add_argument("sheet_b", type=Path)
    ap.add_argument("--key", required=True)
    ap.add_argument("--columns", required=True, help="comma-separated label columns")
    args = ap.parse_args()
    report = agreement_report(args.sheet_a, args.sheet_b, args.key, args.columns.split(","))
    for col, r in report.items():
        print(f"{col}: n={r['n']} kappa={r['kappa']:.3f} raw={r['raw_agreement']:.3f}")
        print(f"  A: {r['labels_a']}")
        print(f"  B: {r['labels_b']}")


if __name__ == "__main__":
    main()
