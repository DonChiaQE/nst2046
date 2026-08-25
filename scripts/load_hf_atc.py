#!/usr/bin/env python3
"""Load data/jacktol-atc/transcripts_enriched.csv into the corpus database (default data/atc.sqlite).

Usage:
    python scripts/load_hf_atc.py [--csv data/jacktol-atc/transcripts_enriched.csv] [--db data/atc.sqlite]

Idempotent: safe to re-run after regenerating the CSV.
"""
import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from atcdb.loader import load_enriched_csv  # noqa: E402
from atcdb.schema import init_db  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--csv", type=Path, default=ROOT / "data/jacktol-atc/transcripts_enriched.csv")
    ap.add_argument("--db", type=Path, default=ROOT / "data/atc.sqlite")
    args = ap.parse_args()
    conn = init_db(args.db)
    stats = load_enriched_csv(conn, args.csv, project_root=ROOT)
    print("rows touched:", stats)
    for t in ["sources", "recordings", "transmissions", "transcripts", "annotations"]:
        print(f"  {t:14s} {conn.execute(f'SELECT count(*) FROM {t}').fetchone()[0]:>7}")
    print(f"db: {args.db}")


if __name__ == "__main__":
    main()
