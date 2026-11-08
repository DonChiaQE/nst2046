import pytest

from scripts.risk_score import KINDS, outcome, perturbations, reciprocal, study


def _row(events, set_name="negatives", truth=None):
    """One stored evaluation row: `events` is a list per transmission, each a list of [kind, callsign, runway, extra]."""
    return {"recording_id": 1, "set": set_name, "truth": truth, "span_s": 100.0,
            "incomplete": False, "missing_transcripts": 0, "dropped": 0,
            "tx_ids": list(range(len(events))), "t": [10.0 * i for i in range(len(events))],
            "events": events, "conflicts": []}


CROSS_THEN_LAND = [
    [["CROSS", "air france one", "13", None]],
    [["NOOP", "", None, None]],
    [["LAND", "csa two", "13", None]],
]


@pytest.mark.parametrize("runway, expected", [
    ("13", "31"), ("31", "13"), ("04", "22"), ("18L", "36R"), ("36R", "18L"), ("09C", "27C"),
])
def test_reciprocal_is_the_other_end_of_the_same_strip(runway, expected):
    assert reciprocal(runway) == expected


def test_reciprocal_is_its_own_inverse():
    for r in ("13", "04", "18L", "27C"):
        assert reciprocal(reciprocal(r)) == r


def test_a_runway_that_does_not_normalise_is_left_alone():
    assert reciprocal("") == ""


def test_every_perturbation_edits_exactly_one_event():
    base = sum(len(step) for step in CROSS_THEN_LAND)
    for kind, events in perturbations(_row(CROSS_THEN_LAND)):
        n = sum(len(step) for step in events)
        assert n == base - 1 if kind == "dropped" else n == base + (kind.startswith("spurious"))


def test_the_perturbation_kinds_generated_are_the_ones_reported():
    assert {k for k, _ in perturbations(_row(CROSS_THEN_LAND))} <= set(KINDS)


def test_a_spurious_event_lands_on_the_busiest_runway_or_its_reciprocal():
    by_kind = {k: e for k, e in perturbations(_row(CROSS_THEN_LAND)) if k.startswith("spurious")}
    inserted = {k: [e for step in ev for e in step if e[0] == "LAND" and e[1] == "air france one"][0]
                for k, ev in by_kind.items()}
    assert inserted["spurious_inuse"][2] == "13"
    assert inserted["spurious_other"][2] == "31"


def test_dropping_the_crossing_removes_the_conflict_it_caused():
    """The engine raises a RUNWAY alert when a landing clearance meets an open crossing on the same runway. Drop the
    crossing and the alert must go with it — the perturbation reached the output."""
    row = _row(CROSS_THEN_LAND)
    dropped = next(e for k, e in perturbations(row) if k == "dropped")
    from atcdb.evaluate import refold
    base, new = refold(row, {}), refold({**row, "events": dropped}, {})
    assert base and not new
    assert outcome(row, base, new)["label"] == "lost_alert"


def test_moving_a_clearance_to_the_reciprocal_runway_removes_the_conflict():
    row = _row(CROSS_THEN_LAND)
    moved = next(e for k, e in perturbations(row) if k == "wrong_runway")
    from atcdb.evaluate import refold
    assert refold(row, {}) and not refold({**row, "events": moved}, {})


def test_an_unchanged_stream_scores_no_change():
    row = _row(CROSS_THEN_LAND)
    from atcdb.evaluate import refold
    base = refold(row, {})
    assert outcome(row, base, base) == {"label": "no_change", "changed": False, "lost": 0, "gained": 0,
                                        "new_false_alarm": False}


def test_a_positive_row_is_scored_for_lost_detections_not_false_alarms():
    row = _row(CROSS_THEN_LAND, "positives", {"runway": "13", "anchor_tx": 0, "trigger_tx": 2, "edit_kind": "splice"})
    from atcdb.evaluate import refold
    base = refold(row, {})
    dropped = next(e for k, e in perturbations(row) if k == "dropped")
    o = outcome(row, base, refold({**row, "events": dropped}, {}))
    assert o["broke_detection"] is True
    assert "new_false_alarm" not in o


def test_an_unusable_row_is_skipped():
    assert all(not v for v in study([{**_row(CROSS_THEN_LAND), "incomplete": True}]).values())


def test_the_study_counts_every_perturbation_it_generated():
    row = _row(CROSS_THEN_LAND)
    agg = study([row])
    assert sum(c["n"] for c in agg.values()) == len(perturbations(row))
