"""Does the divergence story hold for a second model and for ASR transcripts, or only for rules-vs-Sonnet-gold?

`divergent_cases.py` reads one pair of arms at a time and prints their events, which is what turned "5 against 2"
into the two mechanisms in the report's Appendix A. That inspection covered rules vs Sonnet 5 on human transcripts
only, and the report lists the gap as a limitation: a mechanism seen in one pair of arms on one transcript kind is an
anecdote until it replicates.

This script runs the same comparison across every extractor arm at once and asks three questions:

  1. Does the failure taxonomy hold? `parse_error` is the only verdict the choice of extractor can move, so its
     count per arm is the report's central claim stated as a count rather than as an interval.
  2. Does the contingency hold? Rules vs each LLM, on gold and on ASR.
  3. Do the mechanisms hold? Every divergent positive is classified automatically (see `classify`), so the
     mechanism claim is reproducible rather than read off by hand. Appendix A named two, read off one arm pair by
     hand; the classifier splits the first in two, because an unresolved callsign on the aircraft already holding
     the runway and one on the conflicting clearance itself have the same engine consequence but different causes.

Reads only the stored rows and the two label sheets: no database, no API call, nothing paid. That matters because
the events cache and the injected recordings do not survive on every machine, while the rows do. Runway state is
re-derived by folding the stored events through `engine.apply`, so this never second-guesses the engine.

    python scripts/cross_arm_replication.py
    python scripts/cross_arm_replication.py --markdown > docs/results/cross-arm-replication.md
"""
from __future__ import annotations

import argparse
import csv
import datetime
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from atcdb import engine  # noqa: E402
from atcdb.engine import State  # noqa: E402
from atcdb.evaluate import (alert_keys, caught, false_alarms, read_rows, read_verdicts,  # noqa: E402
                            row_to_event, scored, usable)

ROWS = ROOT / "data/eval/conflicts"
LABELS = ROOT / "data/labels"

# A reservation holds a runway until something releases it; everything else leaves runway state alone.
RESERVATIONS = ("LUAW", "TAKEOFF", "LAND", "CROSS")

ARMS = (
    "rule-rules-window-gold",
    "llm-claude-sonnet-5-window-gold",
    "llm-claude-haiku-5-5-window-gold",
    "rule-rules-window-asr",
    "llm-claude-sonnet-5-window-asr",
    "llm-claude-haiku-5-5-window-asr",
)
# Rules is the pre-registered baseline, so every pair compares an LLM against it on the same transcript kind.
PAIRS = tuple(
    (f"rule-rules-window-{kind}", f"llm-{model}-window-{kind}")
    for kind in ("gold", "asr")
    for model in ("claude-sonnet-5", "claude-haiku-5-5")
)
VERDICT_ORDER = ("parse_error", "missing_release", "other_frequency", "engine_rule", "genuine")
# An alert nobody has judged yet is counted under this name, so it can never be folded silently into a
# total: READBACK alerts were never adjudicated by decision, and a new arm can raise a new alert key.
UNADJUDICATED = "unadjudicated"


def load(arm: str, valid: set[int]) -> dict[int, dict]:
    """The arm's stored rows by recording, positives limited to the injections the human check accepted."""
    return scored(read_rows(ROWS / f"{arm}.jsonl"), valid)


def reservations_on(row: dict, runway: str) -> list[tuple[int, str, str]]:
    """Every reservation this arm *extracted* for `runway`, as (step, kind, callsign), in order.

    This is extraction, not state: a reservation here may since have been released. Use `holders` for what the engine
    believes is open.

    Both ends of the strip count: `engine.apply` checks a new clearance against reservations held from either end
    (13 and 31 are one piece of tarmac), so a function that matched the designator string alone would report no
    extracted reservation behind a conflict the engine really did raise -- and every divergent positive here is on
    13/31. `holders` needs no equivalent change: it folds through `engine.apply` and so inherits the rule.
    """
    ends = {runway, engine.reciprocal(runway)}
    return [(step, e[0], e[1]) for step, events in enumerate(row["events"]) for e in events
            if e[0] in RESERVATIONS and e[2] in ends]


def trigger_step(row: dict) -> int | None:
    """The step index of the transmission that carries the injected conflicting clearance."""
    try:
        return row["tx_ids"].index(row["truth"]["trigger_tx"])
    except (ValueError, KeyError):
        return None


def holders(row: dict, runway: str, upto: int) -> list[tuple[str, str]]:
    """What the engine has open on `runway` just before step `upto`, as (kind, callsign) in the order reserved.

    Folded through `engine.apply` rather than read off the event list, because holding a runway is engine state, not
    a property of an event: a hold-short for the same runway, a `VACATED`, a go-around or a handoff to ground or
    departure all release a reservation ([`engine.py`](../atcdb/engine.py) `_release`), and a reservation can also go
    stale. Re-deriving that here would be a second implementation of the engine that could drift from the real one.
    Pure: reads the stored events only, and leaves `engine.STALE_S` untouched (unlike `evaluate.refold`).
    """
    state = State()
    for step, (t, events) in enumerate(zip(row["t"], row["events"])):
        if step >= upto:
            break
        for kind, callsign, rwy, extra in events:
            state, _ = engine.apply(state, row_to_event(kind, callsign, rwy, extra, t=t))
    return [(r.kind, r.callsign) for r in state.runways.get(runway, ())]


def trigger_event(row: dict, runway: str, trigger: int) -> tuple[str, str] | None:
    """The (kind, callsign) of the conflicting clearance itself, as this arm read it.

    Extraction rather than state, deliberately: the question is how the two arms read the same transmission.
    """
    at = [(k, c) for s, k, c in reservations_on(row, runway) if s == trigger]
    return at[-1] if at else None


def anonymous(holding: list[tuple[str, str]]) -> bool:
    """Whether any aircraft holding the runway is unidentified, which is what caps a conflict at `warning`."""
    return any(not c.strip() for _, c in holding)


def classify(a: dict, b: dict, runway: str) -> str:
    """Why exactly one of these two arms caught the injected conflict.

    A RUNWAY conflict has two parties: the *trigger*, the conflicting clearance the injection added, and the
    aircraft already *holding* that runway when it arrives. `engine.apply` caps the conflict at `warning` if
    **either** party's callsign is unknown — "an unidentified aircraft may be the same aircraft"
    ([`engine.py`](../atcdb/engine.py)) — and it keys reservations by exact callsign string, so "the same aircraft"
    inside one arm is exact string identity. Both facts set the rules below, which need no fuzzy matching:

      `identity_holder`   Both arms read the trigger the same way, and they differ in whether an aircraft *holding*
                          the runway is named. Resolving it requires carrying an aircraft's identity across
                          transmissions, which is what the `window` context exists to supply.

      `identity_trigger`  The arms differ on the callsign of the *conflicting clearance itself* — one reads it off
                          the line in front of it, the other leaves it blank. Same engine consequence, but it needs
                          no memory of earlier transmissions, so it is counted separately. It does not run one way:
                          on recording 3291 the regex resolves a bare-numeric callsign that Haiku 5.5 drops, so the
                          mechanism is identity resolution, not model class.

      `supersession`      The arm that misses gave one aircraft two kinds of hold on this runway before the trigger,
                          where the arm that caught gave it one. A new reservation replaces that aircraft's previous
                          one, so the invented clearance rewrites the *kind* of hold open and the compatibility
                          matrix rates the rewritten pair lower, downgrading the conflict or removing it. This is an
                          invented clearance suppressing a true detection rather than raising a false alarm.

    Anything these rules do not explain is returned as `unclassified` rather than forced into one, so the counts
    stay honest about their own coverage.
    """
    ta, tb = trigger_step(a), trigger_step(b)
    if ta is None or tb is None:
        return "unclassified"

    missing, catching = (a, b) if caught(b) else (b, a)
    tm, tc = (ta, tb) if caught(b) else (tb, ta)

    # `supersession` is checked first: where it applies, an anonymous holder is a consequence of the rewritten hold
    # rather than an independent cause, so reporting both would double-count one divergence.
    before_m = [(k, c) for s, k, c in reservations_on(missing, runway) if s < tm]
    before_c = [(k, c) for s, k, c in reservations_on(catching, runway) if s < tc]
    for kind, cs in before_m:
        if not cs.strip():
            continue
        rewrote = any(k != kind and c == cs for k, c in before_m)       # same aircraft, two kinds of hold
        if rewrote and sum(1 for _, c in before_c if c == cs) < sum(1 for _, c in before_m if c == cs):
            return "supersession"

    trig_m, trig_c = trigger_event(missing, runway, tm), trigger_event(catching, runway, tc)
    if trig_m and trig_c and trig_m[0] == trig_c[0] and not trig_m[1].strip() and trig_c[1].strip():
        return "identity_trigger"

    # The engine's own view of who holds the runway, so a released or stale reservation is not mistaken for a holder.
    # Asked as a set question, because more than one aircraft can hold a runway at once: recording 3260 holds both a
    # LUAW and a TAKEOFF, and recording 3230's Sonnet arm sees a second aircraft the rules arm never names. The test
    # is the engine's own condition and nothing more — the arm that missed has an unidentified holder, the arm that
    # caught has none — so the two arms need not have seen the same number of aircraft for the mechanism to be this.
    held_m, held_c = holders(missing, runway, tm), holders(catching, runway, tc)
    if held_m and held_c and anonymous(held_m) and not anonymous(held_c):
        return "identity_holder"

    return "unclassified"


def taxonomy(rows: dict[int, dict], verdicts: dict[str, str]) -> Counter:
    """Adjudicated verdicts for every RUNWAY alert this arm raised on the real recordings."""
    counts: Counter = Counter()
    for row in rows.values():
        if row["set"] != "negatives" or not usable(row):
            continue
        for key in alert_keys(row, "RUNWAY"):
            counts[verdicts.get(key, UNADJUDICATED)] += 1
    return counts


def contingency(a: dict, b: dict, verdicts: dict[str, str]) -> dict:
    """How the two arms split the positives they catch and the negatives they false-alarm on."""
    shared = [r for r in sorted(a) if r in b and usable(a[r]) and usable(b[r])]
    out: dict = {}
    for name, members, hit in (("positives", "positives", caught),
                               ("negatives", "negatives", lambda r: bool(false_alarms(r, verdicts)))):
        ids = [r for r in shared if a[r]["set"] == members]
        out[name] = {
            "n": len(ids),
            "both": [r for r in ids if hit(a[r]) and hit(b[r])],
            "a_only": [r for r in ids if hit(a[r]) and not hit(b[r])],
            "b_only": [r for r in ids if hit(b[r]) and not hit(a[r])],
            "neither": [r for r in ids if not hit(a[r]) and not hit(b[r])],
        }
    return out


def mechanisms(a: dict, b: dict, cont: dict) -> list[dict]:
    """Classify every divergent positive, recording which arm caught it and why."""
    out = []
    for rid in sorted(cont["positives"]["a_only"] + cont["positives"]["b_only"]):
        runway = a[rid]["truth"]["runway"]
        out.append({
            "recording": rid,
            "runway": runway,
            "caught_by": "a" if rid in cont["positives"]["a_only"] else "b",
            "mechanism": classify(a[rid], b[rid], runway),
        })
    return out


def short(arm: str) -> str:
    """`llm-claude-sonnet-5-window-gold` -> `Sonnet 5 / gold`."""
    kind = "gold" if arm.endswith("gold") else "ASR"
    model = ("rules" if arm.startswith("rule-") else
             arm.replace("llm-claude-", "").rsplit("-window-", 1)[0].replace("-", " ").title()
             .replace("Haiku 5 5", "Haiku 5.5"))
    return f"{model} / {kind}"


def render(data: dict, markdown: bool) -> str:
    bullet, h2 = ("- ", "## ") if markdown else ("  ", "=== ")
    out: list[str] = []
    if markdown:
        out += [f"# Cross-arm replication of the divergence analysis ({data['date']})", "",
                "Generated by `scripts/cross_arm_replication.py` from the stored evaluation rows "
                "(`data/eval/conflicts/*.jsonl`) and the two label sheets. No database and no API call, so this "
                "reproduces anywhere the repo is checked out.", "",
                "The report's Appendix A inspects rules vs Sonnet 5 on human transcripts. This asks whether the same "
                "story holds for a second model (Haiku 5.5) and a second transcript kind (ASR).", ""]

    # Only show the unadjudicated column if something is unadjudicated, so the Total always equals the visible row.
    columns = list(VERDICT_ORDER)
    if any(c.get(UNADJUDICATED) for c in data["taxonomy"].values()):
        columns.append(UNADJUDICATED)

    out += [f"{h2}1. Invented conflicts per arm" + ("" if markdown else " ==="), ""]
    if markdown:
        out += ["`parse_error` is the only verdict the choice of extractor can move: the other verdicts describe the "
                "channel or the engine's framing, not the parse. Counting it per arm states the report's central "
                "claim as a count rather than as a confidence interval.", "",
                "| Arm | " + " | ".join(v.replace("_", " ") for v in columns) + " | Total |",
                "|---|" + "---:|" * (len(columns) + 1)]
    for arm in ARMS:
        c = data["taxonomy"][arm]
        cells = [str(c.get(v, 0)) for v in columns]
        total = str(sum(c.values()))
        out.append(f"| {short(arm)} | " + " | ".join(cells) + f" | {total} |" if markdown
                   else f"  {short(arm):<22}" + "".join(f"{x:>16}" for x in cells) + f"{total:>8}")
    out.append("")

    out += [f"{h2}2. Contingency, rules vs each LLM" + ("" if markdown else " ==="), ""]
    if markdown:
        out += ["Each row compares the pre-registered baseline against one LLM arm on the same transcript kind. "
                "\"Both\" plus \"neither\" is the shared mass no choice of extractor affects.", "",
                "| Comparison | Set | n | Both | Rules only | LLM only | Neither |",
                "|---|---|---:|---:|---:|---:|---:|"]
    for a_arm, b_arm in PAIRS:
        cont = data["contingency"][(a_arm, b_arm)]
        for s in ("positives", "negatives"):
            c = cont[s]
            label = f"rules vs {short(b_arm)}"
            row = [str(c["n"]), str(len(c["both"])), str(len(c["a_only"])), str(len(c["b_only"])),
                   str(len(c["neither"]))]
            out.append(f"| {label} | {s} | " + " | ".join(row) + " |" if markdown
                       else f"  {label:<34}{s:<11}" + "".join(f"{x:>9}" for x in row))
    out.append("")

    out += [f"{h2}3. Mechanism behind every divergent positive" + ("" if markdown else " ==="), ""]
    if markdown:
        out += ["Classified by `classify()` from the two parties to a RUNWAY conflict: the *trigger*, the injected "
                "conflicting clearance, and the *prior holder*, the reservation already open on that runway. "
                "`engine.apply` caps the conflict at `warning` when either party's callsign is unknown, so an arm "
                "that resolves a callsign the other leaves blank catches a conflict the other only warns about — "
                "on the holder (`identity (holder)`, which needs identity carried across transmissions) or on the "
                "trigger itself (`identity (trigger)`, which does not). `supersession` is one aircraft given two "
                "kinds of hold, where the later invented one rewrites the earlier and the matrix rates the "
                "rewritten pair lower. `unclassified` is counted rather than explained away.", "",
                "| Comparison | Caught by rules only | Caught by LLM only | identity (holder) "
                "| identity (trigger) | supersession | unclassified |",
                "|---|---:|---:|---:|---:|---:|---:|"]
    for a_arm, b_arm in PAIRS:
        mech = data["mechanisms"][(a_arm, b_arm)]
        counts = Counter(m["mechanism"] for m in mech)
        row = [str(sum(1 for m in mech if m["caught_by"] == "a")),
               str(sum(1 for m in mech if m["caught_by"] == "b")),
               str(counts.get("identity_holder", 0)), str(counts.get("identity_trigger", 0)),
               str(counts.get("supersession", 0)), str(counts.get("unclassified", 0))]
        out.append(f"| rules vs {short(b_arm)} | " + " | ".join(row) + " |" if markdown
                   else f"  rules vs {short(b_arm):<24}" + "".join(f"{x:>14}" for x in row))
    out.append("")

    if markdown:
        out += ["### Every divergent positive, by recording", "",
                "| Comparison | Rec | Rwy | Caught by | Mechanism |", "|---|---:|---:|---|---|"]
        for a_arm, b_arm in PAIRS:
            for m in data["mechanisms"][(a_arm, b_arm)]:
                who = "rules" if m["caught_by"] == "a" else short(b_arm).split(" / ")[0]
                out.append(f"| rules vs {short(b_arm)} | {m['recording']} | {m['runway']} | {who} "
                           f"| `{m['mechanism']}` |")
        out.append("")

        out += ["### Divergent negatives, by recording", "",
                "| Comparison | Rec | False alarm on | Verdict |", "|---|---:|---|---|"]
        for a_arm, b_arm in PAIRS:
            cont = data["contingency"][(a_arm, b_arm)]
            for rid in sorted(cont["negatives"]["a_only"] + cont["negatives"]["b_only"]):
                who = "rules" if rid in cont["negatives"]["a_only"] else short(b_arm).split(" / ")[0]
                arm = a_arm if rid in cont["negatives"]["a_only"] else b_arm
                keys = sorted(false_alarms(data["rows"][arm][rid], data["verdicts"]))
                vs = ", ".join(f"`{data['verdicts'].get(k, 'unadjudicated')}`" for k in keys)
                out.append(f"| rules vs {short(b_arm)} | {rid} | {who} only | {vs} |")
        out.append("")

    return "\n".join(out)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--markdown", action="store_true", help="render as the results doc instead of a terminal table")
    ap.add_argument("--date", default=datetime.date.today().strftime("%d %b %Y"),
                    help="the date in the doc heading; defaults to today, as eval_conflicts does")
    args = ap.parse_args()

    valid = {int(r["recording_id"]) for r in csv.DictReader((LABELS / "injection_check.csv").open())
             if (r.get("valid") or "").strip() == "yes"}
    verdicts = read_verdicts(list(csv.DictReader((LABELS / "adjudication_A.csv").open())))
    rows = {arm: load(arm, valid) for arm in ARMS}

    data = {
        "date": args.date,
        "rows": rows,
        "verdicts": verdicts,
        "taxonomy": {arm: taxonomy(rows[arm], verdicts) for arm in ARMS},
        "contingency": {p: contingency(rows[p[0]], rows[p[1]], verdicts) for p in PAIRS},
    }
    data["mechanisms"] = {p: mechanisms(rows[p[0]], rows[p[1]], data["contingency"][p]) for p in PAIRS}
    print(render(data, args.markdown))


if __name__ == "__main__":
    main()
