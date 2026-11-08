"""The Level 2 results doc (spec 2026-09-29-evaluation-3b1-design.md, section 10).

`summarize` turns every arm's rows, the adjudication verdicts, the injection check verdicts and the adjudication kappa
into plain numbers; `render` writes them as Markdown in the style of docs/results/. Both are pure. A false-alarm rate
whose alerts are not all adjudicated is reported as pending, never as a number. No em dashes: the text goes into the
report.
"""
from collections import Counter

from atcdb.evaluate import (PRIMARY, PRIMARY_ASR, VERDICTS, Pending, alert_keys, bootstrap, detection,
                            false_alarm_units, paired_bootstrap, per_hour, rate, recall, sweep, usable)
from atcdb.inject import EDIT_KINDS


def _recall_units(rows: list[dict]) -> dict[int, float]:
    """recording_id -> 1.0 for a lenient hit, 0.0 otherwise, over usable scorable positives."""
    out = {}
    for r in rows:
        if r["set"] == "positives" and usable(r):
            d = detection(r)
            if d != "unscorable":
                out[r["recording_id"]] = 1.0 if d in ("strict", "lenient") else 0.0
    return out


def _fa_units(rows: list[dict], verdicts: dict[str, str], conflict_type: str) -> dict[int, tuple[float, float]] | None:
    """recording_id -> (false alarms, span_s) over usable negatives, or None while some alert is unadjudicated."""
    negatives = [r for r in rows if r["set"] == "negatives" and usable(r)]
    try:
        units = false_alarm_units(negatives, verdicts, conflict_type)
    except Pending:
        return None
    return {r["recording_id"]: u for r, u in zip(negatives, units)}


def arm_summary(rows: list[dict], verdicts: dict[str, str]) -> dict:
    """Recall (strict, lenient with CI, partial), RUNWAY false alarms per hour (with CI, or None when pending), READBACK
    alerts per hour (raw, with CI: they are not adjudicated), and the counts behind them, for one arm's rows."""
    positives = [r for r in rows if r["set"] == "positives"]
    negatives = [r for r in rows if r["set"] == "negatives"]
    hits = _recall_units(rows)
    out = {"recall": recall(positives), "recall_ci": bootstrap(list(hits.values()), rate),
           "incomplete": sum(r["incomplete"] for r in rows),
           "unscored": sum(not usable(r) for r in rows),
           "hours": sum(r["span_s"] for r in negatives if usable(r)) / 3600,
           "by_kind": {k: recall([r for r in positives if r["truth"]["edit_kind"] == k]) for k in EDIT_KINDS}}
    units = _fa_units(rows, verdicts, "RUNWAY")
    out["fa_RUNWAY"] = None if units is None else per_hour(list(units.values()))
    out["fa_RUNWAY_ci"] = None if units is None else bootstrap(list(units.values()), per_hour)
    raw = [(float(len(alert_keys(r, "READBACK"))), r["span_s"]) for r in negatives if usable(r)]
    out["readback_raw"], out["readback_raw_ci"] = per_hour(raw), bootstrap(raw, per_hour)
    return out


def _cases(pairs: list[tuple[bool, bool]]) -> dict[str, int]:
    """How many recordings both arms, only the first, only the second or neither got (a hit, or a false alarm)."""
    out = {"both": 0, "first only": 0, "second only": 0, "neither": 0}
    for a, b in pairs:
        out["both" if a and b else "first only" if a else "second only" if b else "neither"] += 1
    return out


def _primary_block(summary: dict, pair_key: str, diff_key: str) -> list[str]:
    """One primary-comparison table: the two arms side by side, their paired difference, and the case-by-case line."""
    a, b = summary[pair_key]
    sa, sb, d = summary["arms"][a], summary["arms"][b], summary[diff_key]
    return ["| | " + a + " | " + b + " | Difference, first minus second (95% CI) |", "|---|---|---|---|",
            f"| Lenient recall | {_recall_cell(sa)} | {_recall_cell(sb)} | {_diff_cell(d['recall'], True)} "
            f"over {d['recall_n']} positives |",
            f"| RUNWAY false alarms / h | {_fa_cell(sa)} | {_fa_cell(sb)} | {_diff_cell(d['fa'], False)} "
            f"over {d['fa_n']} negatives |", "",
            f"Case by case, positives caught: {_cases_text(d['recall_cases'], a, b)}. Negatives with a RUNWAY "
            f"false alarm: {_cases_text(d['fa_cases'], a, b)}.", ""]


def primary_differences(rows_a: list[dict], rows_b: list[dict], verdicts: dict[str, str]) -> dict:
    """Paired (point, low, high) differences, first arm minus second, over the recordings both arms scored: lenient
    recall, and RUNWAY false alarms per hour (None while pending); and the case-by-case counts behind each."""
    ha, hb = _recall_units(rows_a), _recall_units(rows_b)
    common = sorted(set(ha) & set(hb))
    out = {"recall": paired_bootstrap([(ha[k], hb[k]) for k in common], rate) if common else None, "recall_n": len(common),
           "recall_cases": _cases([(ha[k] > 0, hb[k] > 0) for k in common])}
    fa, fb = _fa_units(rows_a, verdicts, "RUNWAY"), _fa_units(rows_b, verdicts, "RUNWAY")
    if fa is None or fb is None:
        out["fa"], out["fa_n"], out["fa_cases"] = None, 0, None
    else:
        both = sorted(set(fa) & set(fb))
        out["fa"] = paired_bootstrap([(fa[k], fb[k]) for k in both], per_hour) if both else None
        out["fa_n"] = len(both)
        out["fa_cases"] = _cases([(fa[k][0] > 0, fb[k][0] > 0) for k in both])
    return out


def case_tables(rows_by_arm: dict[str, list[dict]], verdicts: dict[str, str], injections: list[dict]) -> dict[str, list[dict]]:
    """Each recording's outcome under every arm, ids and outcomes only (no corpus text), for case-by-case comparison.
    `positives`: an accepted injection's kind, runway and clean_asr flag, then each arm's detection. `negatives`: the
    span, then each arm's RUNWAY false alarms, `pending` while one of its alerts has no verdict. A row an arm could not
    score (or did not run) is `not_scored`."""
    valid = {i["recording_id"] for i in injections if i.get("valid") == "yes"}
    by_arm = {name: {(r["set"], r["recording_id"]): r for r in rows} for name, rows in sorted(rows_by_arm.items())}
    first: dict[tuple[str, int], dict] = {}
    for rows in by_arm.values():
        for k, r in rows.items():
            first.setdefault(k, r)

    def positive(r: dict | None) -> str:
        return detection(r) if r and usable(r) else "not_scored"

    def negative(r: dict | None) -> int | str:
        if not r or not usable(r):
            return "not_scored"
        keys = alert_keys(r, "RUNWAY")
        if any(k not in verdicts for k in keys):
            return "pending"
        return sum(verdicts[k] != "genuine" for k in keys)

    out = {"positives": [], "negatives": []}
    for (set_name, rid), r in sorted(first.items(), key=lambda kv: (kv[0][0], kv[0][1])):
        if set_name == "positives" and rid in valid:
            out["positives"].append({"recording_id": rid, "edit_kind": r["truth"]["edit_kind"], "runway": r["truth"]["runway"],
                                     "clean_asr": r.get("clean_asr"),
                                     **{name: positive(rows.get(("positives", rid))) for name, rows in by_arm.items()}})
        elif set_name == "negatives":
            out["negatives"].append({"recording_id": rid, "span_s": r["span_s"],
                                     **{name: negative(rows.get(("negatives", rid))) for name, rows in by_arm.items()}})
    return out


def taxonomy(rows: list[dict], verdicts: dict[str, str]) -> Counter:
    """Verdict counts over the distinct RUNWAY alerts one arm raised on usable negatives (`unadjudicated` for none yet)."""
    keys = set().union(*[alert_keys(r, "RUNWAY") for r in rows if r["set"] == "negatives" and usable(r)])
    return Counter(verdicts.get(k, "unadjudicated") for k in keys)


def summarize(rows_by_arm: dict[str, list[dict]], verdicts: dict[str, str], injections: list[dict],
              kappa: tuple[float, int] | None) -> dict:
    """Everything the results doc reports. `injections` are the stored injections with their check verdicts (atcdb.inject
    .synthetic_recordings); a positive row whose injection is no longer accepted (`valid` not yes) is dropped and
    counted per arm. `kappa` is the adjudication agreement, or None before a second adjudicator has started. The ASR
    headline keeps the `clean_asr` rows of every arm whose rows carry the flag, human-transcript arms included, and
    `leakage` is (test-split transmissions, transmissions) over the negatives of the first such arm that has any
    (an arm run on positives only is skipped, not treated as having none)."""
    valid = {i["recording_id"] for i in injections if i.get("valid") == "yes"}
    stale = {name: sum(r["set"] == "positives" and r["recording_id"] not in valid for r in rows)
             for name, rows in sorted(rows_by_arm.items())}
    rows_by_arm = {name: [r for r in rows if r["set"] != "positives" or r["recording_id"] in valid]
                   for name, rows in rows_by_arm.items()}
    arms = {name: arm_summary(rows, verdicts) for name, rows in sorted(rows_by_arm.items())}
    flagged = {name: rows for name, rows in sorted(rows_by_arm.items()) if rows and all("clean_asr" in r for r in rows)}
    headline = {name: arm_summary([r for r in rows if r["clean_asr"]], verdicts) for name, rows in flagged.items()}
    negatives = next((ns for rows in flagged.values() if (ns := [r for r in rows if r["set"] == "negatives"])), [])
    leakage = (sum(r["n_test"] for r in negatives), sum(r["n_tx"] for r in negatives)) if negatives else None
    primary = [a.name for a in PRIMARY]
    primary_asr = [a.name for a in PRIMARY_ASR]
    have_asr = all(p in rows_by_arm for p in primary_asr)
    checks = {k: Counter(i.get("valid") or "unchecked" for i in injections if i["edit_kind"] == k) for k in EDIT_KINDS}
    return {
        "arms": arms, "asr_headline": headline, "leakage": leakage, "stale_positives": stale, "kappa": kappa,
        "checks": checks,
        "primary": primary if all(p in rows_by_arm for p in primary) else None,
        "primary_diff": primary_differences(rows_by_arm[primary[0]], rows_by_arm[primary[1]], verdicts)
        if all(p in rows_by_arm for p in primary) else None,
        "primary_asr": primary_asr if have_asr else None,
        "primary_asr_diff": primary_differences(rows_by_arm[primary_asr[0]], rows_by_arm[primary_asr[1]], verdicts)
        if have_asr else None,
        "taxonomy": {name: taxonomy(rows, verdicts) for name, rows in sorted(rows_by_arm.items())},
        "sweep": {p: sweep(rows_by_arm[p]) for p in primary if p in rows_by_arm},
    }


def _pct(x: float) -> str:
    return f"{100 * x:.0f}%"


def _recall_cell(s: dict) -> str:
    r = s["recall"]
    if not r["n"]:
        return "n/a"
    lo, hi = s["recall_ci"]
    return f"{_pct(r['lenient'] / r['n'])} ({_pct(lo)} to {_pct(hi)})"


def _fa_cell(s: dict, key: str = "fa_RUNWAY") -> str:
    if not s["hours"]:
        return "n/a"
    if s[key] is None:
        return "pending"
    lo, hi = s[f"{key}_ci"]
    return f"{s[key]:.1f} ({lo:.1f} to {hi:.1f})"


def _diff_cell(d: tuple[float, float, float] | None, pct: bool) -> str:
    if d is None:
        return "pending"
    fmt = (lambda x: f"{100 * x:+.0f} pts") if pct else (lambda x: f"{x:+.1f}")
    return f"{fmt(d[0])} ({fmt(d[1])} to {fmt(d[2])})"


def _cases_text(c: dict[str, int] | None, a: str, b: str) -> str:
    if c is None:
        return "pending"
    return f"both {c['both']}, {a} only {c['first only']}, {b} only {c['second only']}, neither {c['neither']}"


def _arm_table(arms: dict[str, dict]) -> list[str]:
    lines = ["| Arm | Positives | Strict | Lenient recall (95% CI) | Warning only | RUNWAY false alarms / h (95% CI) "
             "| READBACK alerts / h, not adjudicated (95% CI) | Hours | Incomplete | Not scored |",
             "|---|---:|---:|---|---:|---|---|---:|---:|---:|"]
    for name, s in arms.items():
        r = s["recall"]
        lines.append(f"| {name} | {r['n']} | {r['strict']} | {_recall_cell(s)} | {r['partial']} | {_fa_cell(s)} "
                     f"| {_fa_cell(s, 'readback_raw')} | {s['hours']:.2f} | {s['incomplete']} | {s['unscored']} |")
    return lines


def render(summary: dict, date: str) -> str:
    """The results doc as Markdown."""
    out = [f"# Conflict detection, Level 2 ({date})", "",
           "Positives are synthetic conflicts injected into real tower recordings and accepted by a human check; negatives "
           "are the unperturbed real recordings. Recall is lenient (an alert on the injected runway at or after the "
           "trigger transmission) unless marked strict (at the trigger). A false alarm is an alert on a negative that "
           "adjudication did not find genuine; rates are per hour of recording span. Intervals are 95% percentile "
           "bootstrap intervals over recordings (2,000 resamples, seed 0).", ""]
    if summary["primary"]:
        out += ["## Primary comparison (pre-registered)", ""]
        out += _primary_block(summary, "primary", "primary_diff")
        if summary.get("primary_asr"):
            out += ["The same pair on ASR transcripts. Milestone 1 argued an LLM extractor would be the more robust "
                    "of the two under ASR noise, so this is the comparison that tests that motivation; read it with "
                    "the leakage caveat below, which makes any degradation a lower bound.", ""]
            out += _primary_block(summary, "primary_asr", "primary_asr_diff")
    else:
        out += ["## Primary comparison (pre-registered)", "", "Not run yet: both primary arms are needed.", ""]
    stale = ", ".join(f"{name} {n}" for name, n in summary["stale_positives"].items() if n) or "none"
    out += ["## All arms, human and ASR transcripts", ""] + _arm_table(summary["arms"]) + [""]
    out += [f"Positives whose injection the check no longer accepts, not scored: {stale}.", "",
            "Each recording's outcome under every arm, ids and outcomes only (no corpus text), is in "
            "`conflict-cases-positives.csv` and `conflict-cases-negatives.csv` beside this doc.", ""]
    leakage = summary["leakage"]
    share = (f"In the real recordings, {leakage[0]} of the {leakage[1]} transmissions ({_pct(leakage[0] / leakage[1])}) "
             f"are test split; the other {_pct(1 - leakage[0] / leakage[1])} were in its training data. "
             if leakage and leakage[1] else "")
    positives_note = ("the positives whose trigger transmission is test split (the anchor may still be train split, "
                       "so a splice's earlier clearance can still be leaked audio)")
    headline_hours = sum(s["hours"] for s in summary["asr_headline"].values())
    if summary["asr_headline"] and not headline_hours:
        headline_text = ("No real recording is entirely in the test split, so the headline reports recall only: it "
                          "keeps " + positives_note + ", for the human-transcript arms and the ASR arms alike. ASR "
                          "false alarms appear only in the all-recordings table above, where the leakage makes the "
                          "reported degradation a lower bound.")
    elif summary["asr_headline"]:
        headline_text = ("These rows keep the negatives whose every transmission is test split and " + positives_note +
                          ", for the human-transcript arms and the ASR arms alike, so each ASR arm can be compared "
                          "with its human-transcript twin on the same recordings. The ASR rows above use all "
                          "recordings and their degradation is a lower bound.")
    else:
        headline_text = ""
    out += ["## ASR headline: recordings in the ASR model's test split", "",
            "The Whisper model was fine-tuned on the corpus's train split, so ASR over train-split clips is optimistic. "
            + share + headline_text, ""]
    out += _arm_table(summary["asr_headline"]) + [""] if summary["asr_headline"] else ["No arm has run yet.", ""]
    out += ["## Recall by injection kind (lenient hits / scored)", "",
            "| Arm | " + " | ".join(EDIT_KINDS) + " |", "|---|" + "---:|" * len(EDIT_KINDS)]
    for name, s in summary["arms"].items():
        out.append(f"| {name} | " + " | ".join(f"{s['by_kind'][k]['lenient']}/{s['by_kind'][k]['n']}" for k in EDIT_KINDS) + " |")
    out += ["", "## Failure taxonomy of RUNWAY alerts on real recordings", "",
            "| Arm | " + " | ".join((*VERDICTS, "unadjudicated")) + " |", "|---|" + "---:|" * (len(VERDICTS) + 1)]
    for name, t in summary["taxonomy"].items():
        out.append(f"| {name} | " + " | ".join(str(t.get(v, 0)) for v in (*VERDICTS, "unadjudicated")) + " |")
    kappa = summary["kappa"]
    out += ["", "## Agreement and generator precision", "",
            f"Adjudication agreement: Cohen's kappa {kappa[0]:.2f} over {kappa[1]} alerts labelled by both adjudicators."
            if kappa and kappa[1] else "Adjudication agreement: no alert has been labelled by both adjudicators yet.", "",
            "| Injection kind | Accepted | Rejected | Not checked |", "|---|---:|---:|---:|"]
    for k, c in summary["checks"].items():
        out.append(f"| {k} | {c.get('yes', 0)} | {c.get('no', 0)} | {c.get('unchecked', 0)} |")
    out += ["", "## CROSS and LUAW staleness sensitivity (a finding, not a tuning)", "",
            "The longest real recording spans 139 s, so on the real recordings no timeout of 139 s or more can change "
            "anything; spliced positives can span up to about 280 s, so longer values can still change recall. Values "
            "are shown for sensitivity only, re-folding the stored events without new parses, so window arms keep the "
            "context they were parsed with at 300 s. `engine.STALE_S` stays at 300 s.", ""]
    for arm, rows in summary["sweep"].items():
        out += [f"{arm}:", "", "| CROSS and LUAW timeout | Lenient recall | RUNWAY alerts on negatives (raw) |",
                "|---:|---|---:|"]
        out += [f"| {r['stale_s']:.0f} s | {r['recall']['lenient']}/{r['recall']['n']} | {r['negative_alerts']} |" for r in rows]
        out.append("")
    out += ["## Caveats", "",
            "- The positives are synthetic. Most are splices: one real recording ending with a runway reservation, "
            "followed by another real recording from the same airport with a conflicting clearance. The rest are single "
            "edits of real text. Only the incident case studies (phase 4) are real conflicts.",
            "- Injection sites come from a keyword scan of clearance phrases with a runway. Conflicts phrased in ways "
            "the scan misses are not represented, which favours parsers that handle the same phrasing.",
            "- For text edits, the edited transmission's audio still says the original words, so its ASR transcript is "
            "the edited gold text; the ASR arms test noise on the rest of the sequence only.",
            "- The engine treats runway designators as separate runways, so a clearance for 13 and one for 31 (the two "
            "ends of one strip) never conflict.",
            "- The judge reports no severity; every conflict it reports is scored as an alert.",
            "- Adjudicators see the human transcript, not what an ASR arm heard, so an ASR arm's alert is judged against "
            "what was said.",
            "- One verdict is applied to every arm that raised the same alert (same recording, type, runway and "
            "trigger transmission), whatever callsigns each arm extracted.",
            "- A judge READBACK report without a normalisable runway is dropped, which shapes the judge's READBACK "
            "numbers.",
            "- READBACK alerts were not adjudicated (decision log, 2026-10-25). Their column counts every READBACK alert "
            "on the real recordings, so it bounds READBACK false alarms from above, and the failure taxonomy covers "
            "RUNWAY alerts only.",
            "- Lenient recall credits any later alert on the injected runway, which favours noisier arms; compare it "
            "with strict recall.", ""]
    return "\n".join(out)
