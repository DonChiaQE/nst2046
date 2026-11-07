from atcdb.eval_report import arm_summary, case_tables, primary_differences, render, summarize, taxonomy
from atcdb.evaluate import PRIMARY

TRUTH = {"runway": "31", "trigger_tx": 3, "edit_kind": "splice"}


def _c(step, severity="alert", runway="31", type_="RUNWAY"):
    return {"type": type_, "severity": severity, "runway": runway, "callsigns": ["a", "b"], "step": step, "tx_id": step + 1}


def _row(rid, set_name, conflicts, all_test=True, span=1800.0):
    events = [[["LAND", "a", "31", None]], [], [["CROSS", "b", "31", None]], []]
    return {"recording_id": rid, "set": set_name, "truth": TRUTH if set_name == "positives" else None, "span_s": span,
            "all_test": all_test, "clean_asr": all_test, "n_tx": 4, "n_test": 4 if all_test else 1, "incomplete": False, "missing_transcripts": 0, "dropped": 0, "tx_ids": [1, 2, 3, 4],
            "t": [0.0, 10.0, 20.0, 30.0], "events": events, "conflicts": conflicts}


RULES = [_row(1, "positives", [_c(2)]), _row(2, "positives", []), _row(10, "negatives", [_c(1)]),
         _row(11, "negatives", [], all_test=False)]
SONNET = [_row(1, "positives", [_c(2)]), _row(2, "positives", [_c(3)]), _row(10, "negatives", []),
          _row(11, "negatives", [], all_test=False)]
VERDICTS = {"10:RUNWAY:31:2": "missing_release"}
VALID = [{"recording_id": 1, "edit_kind": "splice", "valid": "yes"}, {"recording_id": 2, "edit_kind": "splice", "valid": "yes"}]


def test_arm_summary_counts_recall_and_false_alarms():
    s = arm_summary(RULES, VERDICTS)
    assert s["recall"] == {"n": 2, "strict": 1, "lenient": 1, "partial": 0, "miss": 1}
    assert s["fa_RUNWAY"] == 1.0 and s["hours"] == 1.0 and s["readback_raw"] == 0.0
    assert s["by_kind"]["splice"]["n"] == 2 and s["by_kind"]["runway_swap"]["n"] == 0
    assert arm_summary(RULES, {})["fa_RUNWAY"] is None   # an unadjudicated alert: pending, not a number
    # READBACK alerts are not adjudicated (decision 2026-10-25): every one counts, with or without a verdict
    rb = arm_summary([_row(10, "negatives", [_c(1, type_="READBACK")])], {})
    assert rb["readback_raw"] == 2.0 and rb["fa_RUNWAY"] == 0.0


def test_primary_differences_are_paired_over_common_recordings():
    d = primary_differences(RULES, SONNET, VERDICTS)
    assert d["recall"][0] == -0.5 and d["recall_n"] == 2
    assert d["fa"][0] == 1.0 and d["fa_n"] == 2
    assert primary_differences(RULES, SONNET, {})["fa"] is None
    # case by case: recording 1 both hit, recording 2 only the second; negative 10 only the first alarms, 11 neither
    assert d["recall_cases"] == {"both": 1, "first only": 0, "second only": 1, "neither": 0}
    assert d["fa_cases"] == {"both": 0, "first only": 1, "second only": 0, "neither": 1}


def test_taxonomy_counts_verdicts_of_the_arms_own_alerts():
    assert taxonomy(RULES, VERDICTS) == {"missing_release": 1}
    assert taxonomy(RULES, {}) == {"unadjudicated": 1}
    assert taxonomy([_row(10, "negatives", [_c(1), _c(2, type_="READBACK")])], {}) == {"unadjudicated": 1}   # RUNWAY only


def test_the_report_covers_every_section_and_uses_no_em_dash():
    rows = {PRIMARY[0].name: RULES, PRIMARY[1].name: SONNET, "rule-rules-window-asr": RULES}
    injections = VALID + [{"recording_id": 3, "edit_kind": "splice", "valid": "no"},
                          {"recording_id": 4, "edit_kind": "runway_swap"}]
    summary = summarize(rows, VERDICTS, injections, (0.8, 12))
    assert summary["checks"]["splice"] == {"yes": 2, "no": 1} and summary["checks"]["runway_swap"] == {"unchecked": 1}
    assert list(summary["asr_headline"]) == sorted(rows)   # gold arms beside the ASR arm
    assert summary["asr_headline"]["rule-rules-window-asr"]["hours"] == 0.5   # recording 11 is not all test split
    text = render(summary, "29 Sep 2026")
    for heading in ("Primary comparison", "All arms", "ASR headline", "Recall by injection kind", "Failure taxonomy",
                    "Agreement and generator precision", "staleness sensitivity", "Caveats"):
        assert heading in text
    assert "Cohen's kappa 0.80 over 12 alerts" in text and "-50 pts" in text
    assert "both 1, rule-rules-window-gold only 0, llm-claude-sonnet-5-window-gold only 1, neither 0" in text
    assert "conflict-cases-positives.csv" in text and "conflict-cases-negatives.csv" in text
    assert "| Arm | genuine | parse_error | missing_release | other_frequency | engine_rule | unadjudicated |" in text
    assert "READBACK alerts / h, not adjudicated" in text and "READBACK alerts were not adjudicated" in text
    assert "\u2014" not in text
    assert "trigger transmission is test split" in text and "reports recall only" not in text   # a usable headline negative is present
    pending = render(summarize(rows, {}, VALID, None), "29 Sep 2026")
    assert "pending" in pending and "no alert has been labelled by both" in pending
    no_asr = summarize({"rule-rules-window-asr": [{**r, "missing_transcripts": 1} for r in RULES]}, {}, VALID, None)
    no_asr_text = render(no_asr, "x")
    assert no_asr["arms"]["rule-rules-window-asr"]["hours"] == 0 and "| n/a | 0 | n/a | n/a | 0.00 |" in no_asr_text
    assert "reports recall only" in no_asr_text and "trigger transmission is test split" in no_asr_text
    assert "Not run yet" in render(summarize({"rule-rules-none-gold": RULES}, VERDICTS, VALID, None), "29 Sep 2026")


def test_the_headline_states_the_leakage_share_and_the_doc_its_caveats():
    rows = {PRIMARY[0].name: RULES, PRIMARY[1].name: SONNET, "rule-rules-window-asr": RULES,
            "old-arm": [{k: v for k, v in r.items() if k not in ("clean_asr", "n_tx", "n_test")} for r in RULES],
            "aaa-positives-only": [RULES[0], RULES[1]]}   # alphabetically first flagged arm, no negatives at all
    summary = summarize(rows, VERDICTS, VALID, None)
    assert "old-arm" not in summary["asr_headline"] and summary["leakage"] == (5, 8)
    assert summary["asr_headline"][PRIMARY[0].name]["hours"] == 0.5
    text = render(summary, "29 Sep 2026")
    assert "5 of the 8 transmissions (62%)" in text and "trigger transmission is test split" in text
    assert "anchor may still be train split" in text
    assert "over 2 negatives" in text                                  # the n behind the false-alarm difference
    assert "on the real recordings" in text and "280 s" in text and "parsed with at 300 s" in text
    for caveat in ("not what an ASR arm heard", "every arm that raised the same alert",
                   "without a normalisable runway is dropped", "favours noisier arms"):
        assert caveat in text
    assert "not scored: none" in text


def test_positives_no_longer_accepted_are_dropped_and_counted():
    summary = summarize({PRIMARY[0].name: RULES}, VERDICTS, VALID[:1] + [{**VALID[1], "valid": "no"}], None)
    assert summary["arms"][PRIMARY[0].name]["recall"]["n"] == 1 and summary["stale_positives"] == {PRIMARY[0].name: 1}
    assert f"{PRIMARY[0].name} 1" in render(summary, "29 Sep 2026")


def test_case_tables_give_each_recordings_outcome_under_every_arm_and_no_text():
    unusable = {**SONNET[3], "incomplete": True}
    rows = {"rules": RULES, "sonnet": SONNET[:3] + [unusable]}
    tables = case_tables(rows, VERDICTS, VALID[:1] + [{**VALID[1], "valid": "no"}])
    assert tables["positives"] == [{"recording_id": 1, "edit_kind": "splice", "runway": "31", "clean_asr": True,
                                    "rules": "strict", "sonnet": "strict"}]   # recording 2 is no longer accepted
    assert tables["negatives"] == [{"recording_id": 10, "span_s": 1800.0, "rules": 1, "sonnet": 0},
                                   {"recording_id": 11, "span_s": 1800.0, "rules": 0, "sonnet": "not_scored"}]
    assert case_tables(rows, {}, VALID)["negatives"][0]["rules"] == "pending"   # an alert without a verdict
    assert case_tables({"rules": RULES}, VERDICTS, VALID)["positives"][1]["rules"] == "miss"
    assert not any("callsigns" in r or "events" in r for t in tables.values() for r in t)
