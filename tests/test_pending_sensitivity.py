"""Bounding what an unadjudicated alert could do to the false-alarm comparison (report §4.2).

`evaluate.false_alarm_units` refuses to return a rate while any alert lacks a verdict. This script says how much
the missing verdicts could matter, so the three treatments have to bracket the possibilities correctly: `skip` must
be the low end (the alert was right), `count` the high end (it was wrong), and `drop` must remove the recording
rather than the alert.
"""
from scripts.pending_sensitivity import TREATMENTS, paired_interval, unjudged_keys


def _rows(spans, alerts):
    """One negatives row per span; `alerts` gives each row's RUNWAY alert tx_ids."""
    return [{"recording_id": i, "set": "negatives", "span_s": span, "incomplete": False,
             "tx_ids": [1], "missing_transcripts": [], "truth": None,
             "conflicts": [{"type": "RUNWAY", "severity": "alert", "runway": "13", "tx_id": t, "step": 0}
                           for t in txs]}
            for i, (span, txs) in enumerate(zip(spans, alerts), start=1)]


def test_the_three_treatments_bracket_the_possible_verdicts(monkeypatch, tmp_path):
    """`count` can only raise the arm's own rate, so a pending alert on the *second* arm widens a negative gap."""
    import scripts.pending_sensitivity as ps
    a = _rows([3600.0, 3600.0], [[], []])              # arm A: no alerts
    b = _rows([3600.0, 3600.0], [[1], []])             # arm B: one pending alert on recording 1
    monkeypatch.setattr(ps, "read_rows", lambda path: a if "arm_a" in str(path) else b)
    pending = {"1:RUNWAY:13:1"}
    out = {t: ps.paired_interval("arm_a", "arm_b", {}, pending, t)[0] for t in TREATMENTS}
    assert out["skip"] == 0.0, "a skipped alert should count for neither arm"
    assert out["count"] < 0.0, "counting it as a false alarm must widen the gap against arm B"
    assert ps.paired_interval("arm_a", "arm_b", {}, pending, "drop")[3] == 1, "drop removes the recording, not the alert"


def test_unjudged_keys_is_empty_once_every_alert_has_a_verdict(monkeypatch):
    import scripts.pending_sensitivity as ps
    rows = _rows([3600.0], [[7]])
    monkeypatch.setattr(ps, "read_rows", lambda path: rows)
    monkeypatch.setattr(ps.Path, "glob", lambda self, pat: [ps.ROWS / "one.jsonl"])
    assert ps.unjudged_keys({}) == {"1:RUNWAY:13:7"}
    assert ps.unjudged_keys({"1:RUNWAY:13:7": "genuine"}) == set()
