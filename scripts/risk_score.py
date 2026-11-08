"""Consequence weights for extraction errors, by perturbing stored events and re-folding them (Milestone 1, section 4).

Each perturbation edits one event in a recording's stored event stream the way an extractor could plausibly get it
wrong, re-folds the stream through the engine, and records what happened to the RUNWAY alerts. The weight of an error
kind is then measured, not assumed: how often an error of that kind reaches the engine's output at all, how often it
loses a true detection, and how often it creates a false alarm.

No parse is repeated and no API call is made: this reads the stored rows from `eval_conflicts.py run`, like the
staleness sweep does. Perturbations are deterministic, so a re-run reproduces the table.

    python scripts/risk_score.py                                   # the pre-registered arm
    python scripts/risk_score.py --arm llm-claude-sonnet-5-window-gold
    python scripts/risk_score.py --all --out docs/results/risk-score.md
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from atcdb.engine import reciprocal  # noqa: E402  (re-exported: the other end of the same strip)
from atcdb.evaluate import alert_key, detection, refold, usable  # noqa: E402

ROWS = Path("data/eval/conflicts")
PRIMARY_ARM = "rule-rules-window-gold"

RESERVATIONS = ("LAND", "TAKEOFF", "LUAW", "CROSS")
RELEASES = ("VACATED", "GOAROUND", "HANDOFF")
# The rotation a wrong_type perturbation follows. Deterministic so the run reproduces.
NEXT_KIND = {"LAND": "TAKEOFF", "TAKEOFF": "LUAW", "LUAW": "CROSS", "CROSS": "LAND"}

KINDS = ("wrong_runway", "wrong_type", "wrong_callsign", "dropped", "spurious_inuse", "spurious_other")


def perturbations(row: dict) -> list[tuple[str, list[list]]]:
    """Every (kind, events) pair for one recording: the perturbed event stream, one edit each.

    `events` keeps the row's shape — one list of [kind, callsign, runway, extra] per transmission — so the result goes
    straight back through `refold`."""
    events = row["events"]
    runways = [e[2] for step in events for e in step if e[2]]
    callsigns = [e[1] for step in events for e in step if e[1]]
    primary = Counter(runways).most_common(1)[0][0] if runways else None
    out: list[tuple[str, list[list]]] = []

    def edited(i: int, j: int, new: list | None) -> list[list]:
        """The stream with event j of step i replaced by `new`, or dropped when `new` is None."""
        step = events[i][:j] + ([] if new is None else [new]) + events[i][j + 1:]
        return events[:i] + [step] + events[i + 1:]

    for i, step in enumerate(events):
        for j, (kind, callsign, runway, extra) in enumerate(step):
            if kind in RESERVATIONS or kind == "HOLD_SHORT":
                if runway:   # the other end of the same strip: the realistic confusion (an ASR digit error)
                    out.append(("wrong_runway", edited(i, j, [kind, callsign, reciprocal(runway), extra])))
                if kind in RESERVATIONS:
                    out.append(("wrong_type", edited(i, j, [NEXT_KIND[kind], callsign, runway, extra])))
            if kind in RESERVATIONS or kind in RELEASES:
                other = next((c for c in callsigns if c and c != callsign), None)
                if other:
                    out.append(("wrong_callsign", edited(i, j, [kind, other, runway, extra])))
                out.append(("dropped", edited(i, j, None)))

    # A spurious event is an invented clearance on a line that carried none: the LLM's observed failure (an approach
    # clearance read as a landing clearance). Inserted as a LAND for the nearest callsign the engine has already heard,
    # on a transmission whose events are all non-runway. `_inuse` puts it on the recording's busiest runway designator
    # and `_other` on that designator's reciprocal: the same strip entered from its other end, which the engine checks
    # against the same reservations (head-on for two landings). Before the engine treated the two ends as one strip,
    # `_other` met no reservation at all and read as a 0% floor; on a corpus of one strip there is no genuinely unused
    # runway to put an invention on.
    if primary:
        seen = ""
        for i, step in enumerate(events):
            for _, callsign, _, _ in step:
                seen = callsign or seen
            if seen and all(e[0] not in RESERVATIONS and e[0] != "HOLD_SHORT" for e in step):
                for name, rwy in (("spurious_inuse", primary), ("spurious_other", reciprocal(primary))):
                    out.append((name, events[:i] + [step + [["LAND", seen, rwy, None]]] + events[i + 1:]))
    return out


def outcome(row: dict, base: list[dict], new: list[dict]) -> dict:
    """What one perturbation did to this recording's RUNWAY output."""
    def alerts(conflicts: list[dict]) -> set[str]:
        return {alert_key(row["recording_id"], c) for c in conflicts if c["severity"] == "alert"}

    def severities(conflicts: list[dict]) -> dict[str, str]:
        return {alert_key(row["recording_id"], c): c["severity"] for c in conflicts}

    a, b = alerts(base), alerts(new)
    lost, gained = a - b, b - a
    sev_changed = any(severities(base).get(k) != severities(new).get(k)
                      for k in set(severities(base)) & set(severities(new)))

    if lost and gained:
        label = "both"
    elif lost:
        label = "lost_alert"
    elif gained:
        label = "gained_alert"
    elif sev_changed:
        label = "severity_only"
    else:
        label = "no_change"

    res = {"label": label, "changed": label != "no_change", "lost": len(lost), "gained": len(gained)}
    if row["set"] == "positives":
        before = detection({**row, "conflicts": base})
        after = detection({**row, "conflicts": new})
        caught = {"strict", "lenient"}
        res["broke_detection"] = before in caught and after not in caught
        res["fixed_detection"] = before not in caught and after in caught
    else:
        res["new_false_alarm"] = len(gained) > 0
    return res


def study(rows: list[dict]) -> dict[str, dict]:
    """Aggregate every perturbation of every usable recording, by error kind."""
    agg: dict[str, dict] = {k: Counter() for k in KINDS}
    for row in rows:
        if not usable(row):
            continue
        base = refold(row, {})
        for kind, events in perturbations(row):
            o = outcome(row, base, refold({**row, "events": events}, {}))
            c = agg[kind]
            c["n"] += 1
            c["changed"] += o["changed"]
            c[o["label"]] += 1
            if row["set"] == "positives":
                c["positives"] += 1
                c["broke_detection"] += o["broke_detection"]
            else:
                c["negatives"] += 1
                c["new_false_alarm"] += o["new_false_alarm"]
    return {k: dict(v) for k, v in agg.items()}


def pct(num: int, den: int) -> str:
    return f"{100 * num / den:.0f}%" if den else "n/a"


def table(name: str, agg: dict[str, dict]) -> str:
    lines = [f"### {name}", "",
             "| Error kind | Perturbations | Changed the output | Lost a true detection | Created a false alarm |",
             "|---|---:|---|---|---|"]
    for k in KINDS:
        c = agg[k]
        if not c.get("n"):
            continue
        lines.append(f"| `{k}` | {c['n']} | {pct(c['changed'], c['n'])} "
                     f"| {pct(c.get('broke_detection', 0), c.get('positives', 0))} "
                     f"| {pct(c.get('new_false_alarm', 0), c.get('negatives', 0))} |")
    return "\n".join(lines)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--arm", default=PRIMARY_ARM)
    ap.add_argument("--all", action="store_true", help="every non-judge arm on gold transcripts")
    ap.add_argument("--out", type=Path, help="write a markdown section here instead of stdout")
    args = ap.parse_args()

    arms = ([p.stem for p in sorted(ROWS.glob("*-gold.jsonl")) if not p.name.startswith("judge-")]
            if args.all else [args.arm])
    blocks = []
    for arm in arms:
        rows = [json.loads(l) for l in (ROWS / f"{arm}.jsonl").open()]
        blocks.append(table(arm, study(rows)))
        print(blocks[-1], "\n")
    if args.out:
        args.out.write_text("\n\n".join(blocks) + "\n")


if __name__ == "__main__":
    main()
