"""The mechanism classifier behind the report's §4.3 replication counts.

`classify` is what turns "6 against 2" into a named mechanism across four arm pairs, and the report cites its
counts, so the cases below are the ones the hand reading of Appendix A established — plus the two the hand reading
missed, which is why the classifier distinguishes the holder from the trigger.
"""
import pytest

from scripts.cross_arm_replication import anonymous, caught, classify, holders, trigger_event, trigger_step


def _row(events, runway="13", trigger_ix=None, detection="strict"):
    """One stored evaluation row. `events` is a list per transmission of [kind, callsign, runway, extra] lists.

    `detection` is faked through `conflicts`: `caught` reads `evaluate.detection`, which needs an alert on the
    injected runway at or after the trigger, so a strict catch gets one at the trigger step and a miss gets none.
    """
    trigger_ix = len(events) - 1 if trigger_ix is None else trigger_ix
    conflicts = []
    if detection == "strict":
        conflicts = [{"type": "RUNWAY", "severity": "alert", "runway": runway,
                      "callsigns": ["a", "b"], "tx_id": trigger_ix, "step": trigger_ix}]
    elif detection == "warning":
        conflicts = [{"type": "RUNWAY", "severity": "warning", "runway": runway,
                      "callsigns": ["a", ""], "tx_id": trigger_ix, "step": trigger_ix}]
    return {"recording_id": 1, "set": "positives",
            "truth": {"runway": runway, "anchor_tx": 0, "trigger_tx": trigger_ix, "edit_kind": "splice"},
            "span_s": 100.0, "incomplete": False, "missing_transcripts": 0, "dropped": 0,
            "tx_ids": list(range(len(events))), "t": [10.0 * i for i in range(len(events))],
            "events": events, "conflicts": conflicts}


def _n(kind, callsign, runway="13"):
    return [kind, callsign, runway, None]


# The engine caps a conflict at `warning` when either party is unidentified, so the arm that resolves the callsign
# catches what the other only warns about. Recording 3250 is this shape: an anonymous line-up, then the takeoff.
HOLDER_BLANK = [[_n("LUAW", "")], [_n("TAKEOFF", "channex eight eight papa romeo")]]
HOLDER_NAMED = [[_n("LUAW", "csa two nine six")], [_n("TAKEOFF", "channex eight eight papa romeo")]]


def test_an_anonymous_prior_holder_is_identity_on_the_holder():
    missed = _row(HOLDER_BLANK, detection="warning")
    got = _row(HOLDER_NAMED, detection="strict")
    assert classify(missed, got, "13") == "identity_holder"


def test_the_classification_does_not_depend_on_argument_order():
    missed = _row(HOLDER_BLANK, detection="warning")
    got = _row(HOLDER_NAMED, detection="strict")
    assert classify(got, missed, "13") == classify(missed, got, "13")


# Recording 3291: the *trigger* is the anonymous party, and there the rules parser is the arm that resolves it.
# The engine consequence is the same, but it needs no memory of an earlier transmission, so it is counted apart.
TRIGGER_BLANK = [[_n("TAKEOFF", "csa nine zero four")], [_n("LAND", "")]]
TRIGGER_NAMED = [[_n("TAKEOFF", "csa nine zero four")], [_n("LAND", "two six two three")]]


def test_an_anonymous_trigger_is_identity_on_the_trigger_not_the_holder():
    missed = _row(TRIGGER_BLANK, detection="warning")
    got = _row(TRIGGER_NAMED, detection="strict")
    assert classify(missed, got, "13") == "identity_trigger"


def test_identity_on_the_trigger_runs_either_way_round():
    """3291 is the regex resolving a callsign Haiku drops, so the mechanism is not a property of being an LLM."""
    rules = _row(TRIGGER_NAMED, detection="strict")
    haiku = _row(TRIGGER_BLANK, detection="warning")
    assert classify(rules, haiku, "13") == "identity_trigger"
    assert caught(rules) and not caught(haiku)


# Recording 3271: an invented LAND for the aircraft already holding TAKEOFF replaces its own reservation, so
# LAND-vs-TAKEOFF (alert) is rewritten as LAND-vs-LAND (ok) and the conflict disappears with no alarm raised.
SUPERSEDED = [[_n("TAKEOFF", "juliett november five one one")],
              [_n("LAND", "juliett november five one one")],
              [_n("LAND", "cimber three five two three")]]
NOT_SUPERSEDED = [[_n("TAKEOFF", "juliett november five one one")],
                  [_n("NOOP", "")],
                  [_n("LAND", "cimber three five two three")]]


def test_an_invented_event_on_the_holders_own_aircraft_is_supersession():
    missed = _row(SUPERSEDED, trigger_ix=2, detection="warning")
    got = _row(NOT_SUPERSEDED, trigger_ix=2, detection="strict")
    assert classify(missed, got, "13") == "supersession"


def test_supersession_needs_the_second_hold_to_be_a_different_kind():
    """Two reservations of the same kind for one aircraft rewrite nothing, so they are not supersession."""
    repeated = [[_n("TAKEOFF", "juliett november five one one")],
                [_n("TAKEOFF", "juliett november five one one")],
                [_n("LAND", "cimber three five two three")]]
    missed = _row(repeated, trigger_ix=2, detection="warning")
    got = _row(NOT_SUPERSEDED, trigger_ix=2, detection="strict")
    assert classify(missed, got, "13") != "supersession"


def test_supersession_is_preferred_over_identity_when_both_could_apply():
    """A rewritten hold explains an anonymous holder, so reporting both would double-count one divergence."""
    both = [[_n("LUAW", "csa one zulu alfa")], [_n("TAKEOFF", "csa one zulu alfa")],
            [_n("LAND", "cimber three five two three")]]
    missed = _row(both, trigger_ix=2, detection="warning")
    got = _row([[_n("LUAW", "csa one zulu alfa")], [_n("NOOP", "")],
                [_n("LAND", "cimber three five two three")]], trigger_ix=2, detection="strict")
    assert classify(missed, got, "13") == "supersession"


def test_an_unexplained_divergence_is_reported_as_unclassified_not_forced():
    """Both arms name both parties identically and still diverge: the rules above must not invent a reason."""
    same = [[_n("LUAW", "csa one")], [_n("LAND", "csa two")]]
    missed = _row(same, detection="warning")
    got = _row(same, detection="strict")
    assert classify(missed, got, "13") == "unclassified"


def test_events_on_another_runway_are_not_holders_of_this_one():
    """A reservation on 31 cannot hold runway 13."""
    other = [[_n("LUAW", "csa one", "31")], [_n("LUAW", "")], [_n("TAKEOFF", "csa two")]]
    assert holders(_row(other, trigger_ix=2), "13", 2) == [("LUAW", "")]
    assert holders(_row(other, trigger_ix=2), "31", 2) == [("LUAW", "csa one")]


def test_holders_come_from_the_engine_so_a_released_reservation_is_not_one():
    """A hold-short for the same runway cancels that aircraft's clearance (engine.apply), so it stops being a holder.
    Reading the event list instead would still count it and mislabel the divergence."""
    released = [[_n("LUAW", "csa one")], [_n("HOLD_SHORT", "csa one")], [_n("TAKEOFF", "csa two")]]
    assert holders(_row(released, trigger_ix=2), "13", 2) == []


def test_a_hold_short_of_a_different_runway_releases_nothing():
    """"cross runway 13 ... hold short of runway 24" must not release the crossing it was issued with."""
    kept = [[_n("CROSS", "csa one")], [_n("HOLD_SHORT", "csa one", "24")], [_n("TAKEOFF", "csa two")]]
    assert holders(_row(kept, trigger_ix=2), "13", 2) == [("CROSS", "csa one")]


def test_more_than_one_aircraft_can_hold_a_runway_at_once():
    """Recording 3260's rules arm holds a LUAW and a TAKEOFF, both anonymous, so holders is a list not a value."""
    two = [[_n("LUAW", "")], [_n("TAKEOFF", "")], [_n("LAND", "csa two")]]
    assert holders(_row(two, trigger_ix=2), "13", 2) == [("LUAW", ""), ("TAKEOFF", "")]


def test_anonymous_is_true_when_any_holder_is_unidentified():
    """The engine caps at warning if *either* party is unknown, so one blank among several is enough."""
    assert anonymous([("LUAW", ""), ("TAKEOFF", "csa one")]) is True
    assert anonymous([("LUAW", "csa one"), ("TAKEOFF", "csa two")]) is False
    assert anonymous([]) is False


def test_the_trigger_step_comes_from_the_recordings_own_transmission_ids():
    row = _row(HOLDER_NAMED, trigger_ix=1)
    assert trigger_step(row) == 1
    assert trigger_event(row, "13", 1) == ("TAKEOFF", "channex eight eight papa romeo")


@pytest.mark.parametrize("missing_key", ["tx_ids", "truth"])
def test_a_row_without_a_locatable_trigger_is_unclassified(missing_key):
    missed, got = _row(HOLDER_BLANK, detection="warning"), _row(HOLDER_NAMED)
    del missed[missing_key]
    assert classify(missed, got, "13") == "unclassified"
