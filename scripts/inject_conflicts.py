#!/usr/bin/env python3
"""Inject synthetic runway conflicts into real tower recordings (spec 2026-09-29-evaluation-3b1-design.md, section 4).

Usage:
    python scripts/inject_conflicts.py [--n 100] [--seed 0] [--dry-run] [--db data/atc.sqlite]
    python scripts/inject_conflicts.py --sheet data/labels/injection_check.csv
    python scripts/inject_conflicts.py --apply-sheet data/labels/injection_check.csv

The first form stores up to N injections under the `synthetic-conflicts` source (re-running with the same seed changes
nothing); run ASR on the originals first, since each synthetic recording copies their ASR transcripts. `--dry-run`
prints the candidates per edit kind and what would be chosen, and writes nothing. `--sheet` writes the human check
sheet (verdicts already recorded are kept); fill `valid` with yes or no:

    yes = B is addressed to a different aircraft from A, A has not been released or cancelled before B (for
          release_delete: the deleted transmission was A's own release; for splice: nothing at the end of the first
          recording lets A's aircraft off the runway), and B still reads as plausible phraseology.

`--apply-sheet` records the verdicts; only `valid=yes` injections are scored as positives.
"""
import argparse
import csv
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from atcdb.inject import CHECK_COLUMNS, EDIT_KINDS, apply_check, check_rows, pool, select, write_injection  # noqa: E402
from atcdb.replay import real_recordings  # noqa: E402
from atcdb.schema import init_db  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", type=Path, default=ROOT / "data/atc.sqlite")
    ap.add_argument("--n", type=int, default=100)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--dry-run", action="store_true", help="count candidates and the selection, write nothing")
    ap.add_argument("--sheet", type=Path, help="write the human check sheet to this CSV")
    ap.add_argument("--apply-sheet", type=Path, help="record the verdicts in this filled check sheet")
    args = ap.parse_args()
    conn = init_db(args.db)

    if args.sheet:
        rows = check_rows(conn)
        args.sheet.parent.mkdir(parents=True, exist_ok=True)
        with args.sheet.open("w", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=CHECK_COLUMNS)
            w.writeheader()
            w.writerows(rows)
        print(f"wrote {args.sheet} ({len(rows)} injections)")
        return
    if args.apply_sheet:
        with args.apply_sheet.open(newline="") as fh:
            counts = apply_check(conn, list(csv.DictReader(fh)))
        print(f"recorded: {counts['yes']} valid, {counts['no']} rejected, {counts['']} not yet checked")
        return

    candidates = pool(conn, [r["id"] for r in real_recordings(conn)])
    chosen = select(candidates, args.n, args.seed)
    available = Counter(c.edit_kind for c in candidates)
    picked = Counter(c.edit_kind for c in chosen)
    for kind in EDIT_KINDS:
        print(f"  {kind:<20} {available[kind]:>4} candidates, {picked[kind]:>3} chosen")
    if args.dry_run:
        print(f"dry run: {len(chosen)} injections would be stored")
        return
    ids = [write_injection(conn, inj, args.seed, i) for i, inj in enumerate(chosen)]
    print(f"stored {len(ids)} synthetic recordings (source synthetic-conflicts); next: --sheet")


if __name__ == "__main__":
    main()
