#!/usr/bin/env python3
"""Replay the two 2026 real-incident reconstructions (Goa, Houston) through each extractor.

Both cases were reconstructed from published reporting into `data/labels/real_2026_cases_{A,B}.csv`, so they are
quotations rather than complete transcripts and carry no rate (Milestone 1 feedback, suggestion 3). They are not in
the corpus database, so nothing here is cached and the LLM arms are billed on every run — use --dry-run first.

The rules arm is local and free and needs no key. It is the arm that establishes the §4.5 finding: the engine
recognises four reservation kinds (LAND, TAKEOFF, LUAW, CROSS) and *none* of these 7 transmissions maps to any of
them, so no alert can be raised whatever the extractor does. Goa is a backtrack incursion and Houston is a
callsign-confusion event; neither is an incompatible pair of runway clearances.

What the LLM arms add is the hallucination check: given "expect backtrack" and "entering runway", does the model
invent a TAKEOFF or a LAND that was never issued? Recording 242 showed two models converging on the same
fabrication, so this is a direct test of that mechanism on real text rather than injected text.

Reproducibility works two ways, and the second is the one that makes the first trustworthy:

  * **Keyless.** The LLM arms are recorded to `data/eval/real_2026/` and committed, so the table reproduces with no
    key and no spend.
  * **With a key.** `--verify` re-derives the arm from the API and checks it against the recording, so the committed
    file is a falsifiable claim rather than hardcoded data. It exits non-zero if the check fails.

Verification is deliberately not byte-equality. The report retracts Milestone 1's temperature-0 determinism claim
(§2): Sonnet 5 rejects a `temperature` parameter, so identical prompts need not give identical replies, and a strict
diff would fail for reasons that say nothing about the finding. So --verify separates two things:

  * the **invariant** the report actually cites — that no arm produces a runway reservation on these rows, which is
    what makes §4.5's claim about the framing rather than about a parser. A breach here fails the check.
  * **drift** — any other difference from the recording, per row. Reported in full and not a failure, but it means
    the recording should be refreshed with --record so the committed file matches what the API now returns.

    python scripts/real_2026_cases.py                       # every recorded arm: free, no key
    python scripts/real_2026_cases.py --dry-run             # what a re-derivation would cost, free
    python scripts/real_2026_cases.py --verify --model claude-sonnet-5   # billed; checks the recording
    python scripts/real_2026_cases.py --record --model claude-sonnet-5   # billed; (re)writes the recording
"""
import argparse
import csv
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from atcdb import parse_llm, parse_rules  # noqa: E402
from atcdb.engine import NoOp, RESERVATION_KINDS, State  # noqa: E402
from atcdb.incidents import fold_window as fold  # noqa: E402
from atcdb.parsing import Transmission  # noqa: E402
from atcdb.replay import build_context  # noqa: E402
from atcdb.serialize import event_dict  # noqa: E402

SHEET = ROOT / "data/labels/real_2026_cases_A.csv"
RECORDED = ROOT / "data/eval/real_2026"


def recording_path(model: str) -> Path:
    return RECORDED / f"events-{model}.json"


# How a recording's events came to be. A recording seeded by hand from a run someone pasted into a session holds
# real output, but it is a transcription: it can carry a typo, and the terminal view it was read from is lossy (it
# prints `runway or to`, so the two fields have to be inferred back). Anything citing a recording needs to be able to
# tell the difference, and `--record` is what turns a transcribed one into an API-written one.
PROVENANCE_API = "api"
PROVENANCE_TRANSCRIBED = "transcribed"


def derive(model: str, by_case: dict[str, list[Transmission]]) -> dict:
    """Call the API and shape the reply exactly as a recording, so --record and --verify share one derivation."""
    parse = parse_llm.make_parser(model)
    out = {"model": model, "parse_version": parse_llm.VERSION, "sheet": SHEET.name,
           "provenance": PROVENANCE_API, "cases": {}}
    for case, txs in by_case.items():
        out["cases"][case] = [{"text": tx.text, "role": tx.role,
                               "events": [event_dict(e) for e in events if not isinstance(e, NoOp)]}
                              for tx, events, _ in fold(txs, parse)]
    return out


def reservations_in(data: dict) -> list[tuple[str, dict]]:
    """Every runway reservation in a derived or recorded arm. The report's §4.5 claim is that this is empty."""
    return [(case, e) for case, rows in data["cases"].items()
            for row in rows for e in row["events"] if e["kind"] in RESERVATION_KINDS]


def drift(recorded: dict, fresh: dict) -> list[str]:
    """Per-row differences between a recording and a fresh derivation, as readable lines."""
    out = []
    for case in sorted(set(recorded["cases"]) | set(fresh["cases"])):
        old, new = recorded["cases"].get(case, []), fresh["cases"].get(case, [])
        if len(old) != len(new):
            out.append(f"{case}: {len(old)} rows recorded, {len(new)} derived")
            continue
        for i, (o, n) in enumerate(zip(old, new), start=1):
            if o["events"] != n["events"]:
                out.append(f"{case} row {i}: recorded {_brief(o['events'])} -> derived {_brief(n['events'])}")
    return out


def _brief(events: list[dict]) -> str:
    return "; ".join(f"{e['kind']}{' ' + e['runway'] if e['runway'] else ''}[{e['callsign']}]"
                     for e in events) or "-"


def record(model: str, by_case: dict[str, list[Transmission]]) -> dict:
    """Parse every row with `model` and write the events to disk, so a keyless run can reproduce the table.

    Keyed by `parse_llm.VERSION`: a recording made under an older prompt is still readable but is flagged on load,
    because the report cites these events and a silent prompt change would make the citation wrong.
    """
    out = derive(model, by_case)
    RECORDED.mkdir(parents=True, exist_ok=True)
    recording_path(model).write_text(json.dumps(out, indent=2) + "\n")
    return out


def load_recorded(model: str) -> dict | None:
    """The committed recording for `model`, or None if it was never recorded."""
    path = recording_path(model)
    if not path.exists():
        return None
    data = json.loads(path.read_text())
    if data.get("parse_version") != parse_llm.VERSION:
        print(f"  ! {path.name} was recorded under parse version {data.get('parse_version')!r}, "
              f"but parse_llm.VERSION is {parse_llm.VERSION!r}: re-record before citing it.")
    if data.get("provenance") != PROVENANCE_API:
        print(f"  ! {path.name} is a {data.get('provenance')!r} recording, not written by this script against the "
              f"API. Its events are real output but transcribed by hand; run --record to replace it.")
    return data


def cases(sheet: Path) -> dict[str, list[Transmission]]:
    """The sheet's normalised text as transmissions, grouped by case, in row order."""
    out: dict[str, list[Transmission]] = {}
    for i, r in enumerate(csv.DictReader(sheet.open())):
        rows = out.setdefault(r["case"], [])
        rows.append(Transmission(id=i, transcript_id=i, text=r["normalized_text"],
                                 role=r["role"], start_s=float(10 * len(rows))))
    return out


def _rows_from_fold(steps: list[tuple]) -> list[dict]:
    return [{"text": tx.text, "role": tx.role,
             "events": [event_dict(e) for e in events if not isinstance(e, NoOp)],
             "conflicts": [(c.type, c.severity, c.runway, list(c.callsigns)) for c in conflicts]}
            for tx, events, conflicts in steps]


def show(title: str, rows: list[dict]) -> int:
    """Print one arm's reading of a case and return how many runway reservations it produced."""
    print(f"\n== {title} ==")
    reservations = 0
    for row in rows:
        shown = []
        for e in row["events"]:
            arg = e["runway"] or e["to"] or ""
            shown.append(" ".join(p for p in (e["kind"], arg, f"[{e['callsign']}]") if p))
            reservations += e["kind"] in RESERVATION_KINDS
        print(f"  [{row['role']}] {row['text']}")
        print(f"      events: {'; '.join(shown) or '-'}")
        for kind, severity, runway, callsigns in row.get("conflicts", []):
            print(f"      CONFLICT {kind} {severity} runway {runway} "
                  f"{' vs '.join(cs or '?' for cs in callsigns)}")
    print(f"  --> {reservations} runway reservation(s); "
          f"{'an alert is possible' if reservations >= 2 else 'no conflict can be raised'}")
    return reservations


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--sheet", type=Path, default=SHEET)
    ap.add_argument("--model", action="append", choices=parse_llm.MODELS,
                    help="limit to these LLM arms (default: every arm that has a committed recording)")
    ap.add_argument("--record", action="store_true",
                    help="call the API and (re)write the recording for each --model (billed)")
    ap.add_argument("--verify", action="store_true",
                    help="call the API and check each --model against its recording (billed); non-zero on failure")
    ap.add_argument("--dry-run", action="store_true", help="price a re-record without calling the API")
    args = ap.parse_args()

    by_case = cases(args.sheet)
    print(f"{args.sheet.name}: {sum(len(v) for v in by_case.values())} transmissions "
          f"across {len(by_case)} cases ({', '.join(by_case)})")
    print(f"engine reservation kinds: {', '.join(RESERVATION_KINDS)}")

    if args.dry_run:
        for m in args.model or list(parse_llm.MODELS):
            prompts = [parse_llm.render_prompt(tx, build_context("window", tx, txs[:k], State()))
                       for txs in by_case.values() for k, tx in enumerate(txs)]
            print(f"  {m}: {len(prompts)} uncached parses, about ${parse_llm.estimate_cost(m, prompts):.2f}")
        return

    if args.record and args.verify:
        ap.error("--record rewrites the recording and --verify checks it; pick one")
    if (args.record or args.verify) and not args.model:
        ap.error("--record and --verify need at least one --model, so a billed run is always explicit")

    if args.record:
        for m in args.model:
            record(m, by_case)
            print(f"  recorded {recording_path(m).relative_to(ROOT)}")

    if args.verify:
        failed = False
        for m in args.model:
            recorded = load_recorded(m)
            print(f"\n== verifying {m} against {recording_path(m).name} ==")
            if recorded is None:
                print("  FAIL: nothing recorded for this model; run --record first")
                failed = True
                continue
            fresh = derive(m, by_case)

            found = reservations_in(fresh)
            if found:
                print(f"  FAIL: the re-derivation produced {len(found)} runway reservation(s), so \u00a74.5's claim")
                print("        that no extractor can raise an alert on these rows no longer holds:")
                for case, e in found:
                    print(f"          {case}: {_brief([e])}")
                failed = True
            else:
                print("  OK: no runway reservation in the re-derivation "
                      "(\u00a74.5's invariant holds, independently of the recording)")

            differences = drift(recorded, fresh)
            if differences:
                print(f"  DRIFT: {len(differences)} row(s) differ from the recording. Not a failure \u2014 the API is")
                print("         not deterministic (\u00a72) \u2014 but re-record so the committed file matches:")
                for line in differences:
                    print(f"           {line}")
            else:
                print("  OK: every row matches the recording exactly")
        if failed:
            sys.exit(1)
        return

    # Every LLM arm with a committed recording, so the default run is free and reproducible without a key.
    arms = {}
    for m in args.model or parse_llm.MODELS:
        data = load_recorded(m)
        if data:
            arms[m] = data
    if not arms:
        print("\n  (no LLM arm recorded yet; run with --record --model <model> and a key to add one)")

    totals = {}
    for case, txs in by_case.items():
        totals[(case, "rules")] = show(f"{case}, rules", _rows_from_fold(fold(txs, parse_rules.parse)))
        for m, data in arms.items():
            rows = data["cases"].get(case)
            if rows is None:
                print(f"\n== {case}, {m} ==\n  (not in {recording_path(m).name}; re-record)")
                continue
            totals[(case, m)] = show(f"{case}, {m}", rows)

    print("\n== summary ==")
    worst = max(totals.values()) if totals else 0
    if worst == 0:
        print("  Every arm produces 0 runway reservations on both cases, so no alert can be raised by any extractor.")
    else:   # a single reservation already falsifies the sentence above, so it must not be printed alongside it
        print(f"  ! An arm produced {worst} runway reservation(s), so the \u00a74.5 claim below no longer holds as")
        print("    written: with a reservation open, an extractor can raise an alert. Re-check before citing it.")
    print("  The engine recognises only LAND, TAKEOFF, LUAW and CROSS; Goa is a backtrack incursion and Houston is")
    print("  a callsign-confusion event, so both lie outside what the conflict model represents (report \u00a74.5).")
    print(f"  max reservations in any arm: {worst}")


if __name__ == "__main__":
    main()
