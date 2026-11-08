"""The recordings where two arms disagree, and what each one extracted there (report Appendix A).

The aggregate comparison hides the interesting part: rules and Sonnet agree on 83 of 98 positives and 306 of 309
negatives, so the whole difference between them rests on about ten recordings. This prints those recordings with the
events each arm extracted, which is what turns "5 against 2" into a mechanism.

Reads only the stored rows and the two label sheets: no database, no API call, nothing paid. That matters because the
events cache and the injected recordings do not survive on every machine, while the rows do.

    python scripts/divergent_cases.py
    python scripts/divergent_cases.py --b llm-claude-haiku-5-5-window-gold
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from atcdb.evaluate import alert_keys, detection, read_verdicts, usable  # noqa: E402

ROWS = ROOT / "data/eval/conflicts"
LABELS = ROOT / "data/labels"
RELEASES = ("VACATED", "GOAROUND", "HANDOFF")


def load(arm: str, valid: set[int]) -> dict[int, dict]:
    """The arm's rows by recording, positives limited to the injections the human check accepted."""
    rows = (json.loads(line) for line in (ROWS / f"{arm}.jsonl").open())
    return {r["recording_id"]: r for r in rows if r["set"] != "positives" or r["recording_id"] in valid}


def caught(row: dict) -> bool:
    return detection(row) in ("strict", "lenient")


def false_alarms(row: dict, verdicts: dict[str, str]) -> set[str]:
    """The arm's RUNWAY alerts on this recording that adjudication did not call genuine."""
    return {k for k in alert_keys(row, "RUNWAY") if verdicts.get(k) != "genuine"}


def on_runway(row: dict, runway: str) -> list[tuple[int, list]]:
    """Every event this arm extracted that touches `runway`, plus the releases, with the step it came from."""
    return [(step, e) for step, events in enumerate(row["events"]) for e in events
            if e[2] == runway or e[0] in RELEASES]


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--a", default="rule-rules-window-gold")
    ap.add_argument("--b", default="llm-claude-sonnet-5-window-gold")
    args = ap.parse_args()

    valid = {int(r["recording_id"]) for r in csv.DictReader((LABELS / "injection_check.csv").open())
             if (r.get("valid") or "").strip() == "yes"}
    verdicts = read_verdicts(list(csv.DictReader((LABELS / "adjudication_A.csv").open())))
    a, b = load(args.a, valid), load(args.b, valid)
    both = [rid for rid in sorted(a) if rid in b and usable(a[rid]) and usable(b[rid])]

    print(f"{args.a}  vs  {args.b}\n")
    print("=== positives where exactly one arm caught the injected conflict ===")
    for rid in [r for r in both if a[r]["set"] == "positives" and caught(a[r]) != caught(b[r])]:
        truth = a[rid]["truth"]
        print(f"\nrecording {rid}  runway {truth['runway']}  ({truth['edit_kind']})"
              f"  {args.a}={detection(a[rid])}  {args.b}={detection(b[rid])}")
        for name, row in ((args.a, a[rid]), (args.b, b[rid])):
            print(f"  {name}")
            for step, e in on_runway(row, truth["runway"]):
                print(f"    step {step:>3}  {e[0]:<10} runway={str(e[2]):<5} callsign={e[1]!r}")

    print("\n\n=== negatives where exactly one arm raised a false alarm ===")
    for rid in [r for r in both if a[r]["set"] == "negatives"
                and bool(false_alarms(a[r], verdicts)) != bool(false_alarms(b[r], verdicts))]:
        print(f"\nrecording {rid}  false alarm on "
              f"{args.a if false_alarms(a[rid], verdicts) else args.b} only")
        for name, row in ((args.a, a[rid]), (args.b, b[rid])):
            conflicts = [(c["severity"], c["runway"], c["callsigns"]) for c in row["conflicts"] if c["type"] == "RUNWAY"]
            seen = sorted(alert_keys(row, "RUNWAY"))
            print(f"  {name}")
            print(f"    RUNWAY conflicts: {conflicts or 'none'}")
            print(f"    verdicts:         {[verdicts.get(k, 'unadjudicated') for k in seen] or 'none'}")


if __name__ == "__main__":
    main()
