#!/usr/bin/env python3
"""Level 2 conflict evaluation (spec 2026-09-29-evaluation-3b1-design.md, sections 5 to 10).

Usage:
    python scripts/eval_conflicts.py run [--parser rule|llm|judge] [--model M] [--context C] [--transcript gold|asr]
                                         [--set negatives|positives] [--workers N] [--dry-run]
    python scripts/eval_conflicts.py adjudicate [--kappa]
    python scripts/eval_conflicts.py sweep [--values 30 60 90 120 300]

`run` replays every recording of the evaluation sets under each selected arm (the 18 structured arms and the two
judge arms by default; `--parser judge` for the judge only) and writes one JSONL per arm to data/eval/conflicts/.
Parses and judgments come from their caches, so a re-run is free; always `--dry-run` first, which prints the uncached
calls and a rough cost per arm and spends nothing.

`adjudicate` pools every alert the arms raised on the negatives into data/labels/adjudication_A.csv (verdicts already
given are kept) and writes the second adjudicator's overlap, adjudication_B.csv. Fill `verdict` with genuine,
parse_error (the extraction was wrong), missing_info (extraction right, the release was never spoken) or engine_rule
(extraction right, the matrix is too strict). Re-run it after new arms have run. `--kappa` reports agreement instead.

`sweep` re-folds every structured arm's stored events with the CROSS and LUAW timeouts set to each value and prints
lenient recall and raw negative alerts per value. A finding only: engine.STALE_S is not changed.
"""
import argparse
import csv
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from atcdb.evaluate import (ADJUDICATION_COLUMNS, ARMS, JUDGE_ARMS, SWEEP_VALUES, adjudication_kappa,  # noqa: E402
                            adjudication_rows, evaluation_sets, overlap_rows, read_rows, run_arm, sweep, uncached,
                            write_rows)
from atcdb.schema import init_db  # noqa: E402

OUT = ROOT / "data/eval/conflicts"
SHEET_A = ROOT / "data/labels/adjudication_A.csv"
SHEET_B = ROOT / "data/labels/adjudication_B.csv"


def read_sheet(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with path.open(newline="") as fh:
        return list(csv.DictReader(fh))


def write_sheet(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=ADJUDICATION_COLUMNS)
        w.writeheader()
        w.writerows(rows)


def arm_rows(out: Path) -> dict[str, list[dict]]:
    """Every arm's rows that `run` (or the judge) has written, by arm name."""
    return {p.stem: read_rows(p) for p in sorted(out.glob("*.jsonl"))}


def selected_arms(args: argparse.Namespace) -> list:
    return [a for a in ARMS + JUDGE_ARMS
            if all(getattr(args, f) in (None, getattr(a, f)) for f in ("parser", "model", "context", "transcript"))]


def cmd_run(args: argparse.Namespace) -> None:
    conn = init_db(args.db)
    items = [it for it in evaluation_sets(conn) if args.set in (None, it[1])]
    arms = selected_arms(args)
    if not arms:
        sys.exit("no arm matches the filters")
    if args.dry_run:
        total = 0.0
        for arm in arms:
            n, cost = uncached(conn, arm, [rid for rid, _, _ in items])
            total += cost
            print(f"  {arm.name:<40} {n:>5} uncached calls  ${cost:.2f}")
        print(f"dry run: {len(items)} recordings, {len(arms)} arms, estimated ${total:.2f}")
        return
    for arm in arms:
        rows = run_arm(args.db, arm, items, workers=args.workers)
        write_rows(args.out / f"{arm.name}.jsonl", rows)
        incomplete = sum(r["incomplete"] for r in rows)
        print(f"  {arm.name:<40} {len(rows)} recordings, {incomplete} incomplete", flush=True)


def cmd_adjudicate(args: argparse.Namespace) -> None:
    sheet_a, sheet_b = read_sheet(args.sheet_a), read_sheet(args.sheet_b)
    if args.kappa:
        kappa, n = adjudication_kappa(sheet_a, sheet_b)
        print(f"Cohen's kappa {kappa:.2f} over {n} alerts both adjudicators labelled")
        return
    sheet_a = adjudication_rows(init_db(args.db), arm_rows(args.out), existing=sheet_a)
    sheet_b = overlap_rows(sheet_a, existing_b=sheet_b)
    write_sheet(args.sheet_a, sheet_a)
    write_sheet(args.sheet_b, sheet_b)
    todo = sum(not r["verdict"] for r in sheet_a)
    print(f"wrote {args.sheet_a} ({len(sheet_a)} alerts, {todo} without a verdict) and {args.sheet_b} ({len(sheet_b)} alerts)")


def cmd_sweep(args: argparse.Namespace) -> None:
    print(f"  {'arm':<40} " + "  ".join(f"{v:>5.0f}s recall/alerts" for v in args.values))
    for name, rows in arm_rows(args.out).items():
        if name.startswith("judge-"):
            continue   # the judge has no events to re-fold
        cells = [f"{r['recall']['lenient']:>5}/{r['recall']['n']:<4}{r['negative_alerts']:>9}" for r in sweep(rows, args.values)]
        print(f"  {name:<40} " + "  ".join(cells))


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", type=Path, default=ROOT / "data/atc.sqlite")
    ap.add_argument("--out", type=Path, default=OUT)
    sub = ap.add_subparsers(dest="command", required=True)
    run = sub.add_parser("run", help="replay the evaluation sets under each arm")
    run.add_argument("--parser", choices=["rule", "llm", "judge"])
    run.add_argument("--model")
    run.add_argument("--context", choices=["none", "role", "window", "sequence"])
    run.add_argument("--transcript", choices=["gold", "asr"])
    run.add_argument("--set", choices=["negatives", "positives"])
    run.add_argument("--workers", type=int, default=4)
    run.add_argument("--dry-run", action="store_true")
    run.set_defaults(func=cmd_run)
    adj = sub.add_parser("adjudicate", help="write or update the alert adjudication sheets")
    adj.add_argument("--sheet-a", type=Path, default=SHEET_A)
    adj.add_argument("--sheet-b", type=Path, default=SHEET_B)
    adj.add_argument("--kappa", action="store_true", help="report agreement between the two sheets")
    adj.set_defaults(func=cmd_adjudicate)
    sw = sub.add_parser("sweep", help="CROSS/LUAW staleness sensitivity (a finding, not a tuning)")
    sw.add_argument("--values", type=float, nargs="+", default=list(SWEEP_VALUES))
    sw.set_defaults(func=cmd_sweep)
    args = ap.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
