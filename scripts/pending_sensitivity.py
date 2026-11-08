"""How much an unadjudicated alert could move the false-alarm comparison (report §4.2).

`evaluate.false_alarm_units` raises `Pending` when any RUNWAY alert has no adjudication verdict, so the rate is
refused rather than guessed. That is the right default -- the alternatives each bias in a known direction -- but
refusing says nothing about *how much* the missing verdicts could matter. This bounds it by recomputing the paired
interval under the three treatments, which between them bracket every possible verdict:

    skip        the alert is not counted (what a `genuine` verdict would do: the alert was correct)
    drop        the whole recording leaves the comparison (selection on the outcome -- shown for comparison, not
                recommended: it removes a negative *because* an arm alerted on it, which flatters the arm)
    count       the alert counts as a false alarm (what any non-`genuine` verdict would do)

If the conclusion is the same under all three, the pending verdicts cannot change it and the interval can be
reported with this bound beside it. If it differs, the comparison genuinely has to wait for the adjudication.

Reads the stored rows and sheet A only: no database, no API call, nothing paid.

    python scripts/pending_sensitivity.py
"""
from __future__ import annotations

import csv
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from atcdb.evaluate import (PRIMARY, PRIMARY_ASR, alert_keys, per_hour, paired_bootstrap,  # noqa: E402
                            read_rows, read_verdicts, usable)

ROWS = ROOT / "data/eval/conflicts"
LABELS = ROOT / "data/labels"
TREATMENTS = ("skip", "drop", "count")


def unjudged_keys(verdicts: dict[str, str]) -> set[str]:
    """Every RUNWAY alert key in any stored arm that adjudication has not ruled on."""
    out = set()
    for path in sorted(ROWS.glob("*.jsonl")):
        for row in read_rows(path):
            if row["set"] == "negatives" and usable(row):
                out |= {k for k in alert_keys(row, "RUNWAY") if k not in verdicts}
    return out


def paired_interval(a_arm: str, b_arm: str, verdicts: dict[str, str], pending: set[str], treatment: str):
    """(point, low, high, negatives compared) for a_arm - b_arm false alarms per hour under one treatment."""
    a = {r["recording_id"]: r for r in read_rows(ROWS / f"{a_arm}.jsonl") if r["set"] == "negatives"}
    b = {r["recording_id"]: r for r in read_rows(ROWS / f"{b_arm}.jsonl") if r["set"] == "negatives"}

    def unit(row: dict) -> tuple[float, float]:
        keys = alert_keys(row, "RUNWAY")
        n = sum(verdicts.get(k) != "genuine" for k in keys - pending)
        if treatment == "count":
            n += len(keys & pending)
        return (float(n), row["span_s"])

    pairs = []
    for rid in sorted(set(a) & set(b)):
        ra, rb = a[rid], b[rid]
        if not (usable(ra) and usable(rb)):
            continue
        if treatment == "drop" and (alert_keys(ra, "RUNWAY") | alert_keys(rb, "RUNWAY")) & pending:
            continue
        pairs.append((unit(ra), unit(rb)))
    point, low, high = paired_bootstrap(pairs, per_hour)
    return point, low, high, len(pairs)


def main() -> None:
    verdicts = read_verdicts(list(csv.DictReader((LABELS / "adjudication_A.csv").open())))
    pending = unjudged_keys(verdicts)
    print(f"{len(verdicts)} verdicts on file; {len(pending)} alert key(s) awaiting one")
    for key in sorted(pending):
        print(f"   {key}")
    if not pending:
        print("\nNothing pending: the published interval is the interval.")
        return

    for label, (a, b) in (("primary pair, gold", PRIMARY), ("primary pair, ASR", PRIMARY_ASR)):
        print(f"\n== {label}: {a.name} minus {b.name} ==")
        verdicts_excl = []
        for treatment in TREATMENTS:
            point, low, high, n = paired_interval(a.name, b.name, verdicts, pending, treatment)
            excludes = (low < 0 and high < 0) or (low > 0 and high > 0)
            verdicts_excl.append(excludes)
            print(f"   {treatment:<6} {point:+.2f} ({low:+.2f} to {high:+.2f}) per hour over {n} negatives"
                  f"   {'excludes zero' if excludes else 'includes zero'}")
        same = len(set(verdicts_excl)) == 1
        print(f"   -> the pending verdict{'s' if len(pending) > 1 else ''} "
              f"{'cannot change this conclusion' if same else 'COULD change this conclusion'}")


if __name__ == "__main__":
    main()
