import pytest

from atcdb import engine
from atcdb.engine import (ENGINE_VERSION, ClearTakeoff, ClearToCross, ClearToLand, Event, GoAround, Handoff, HANDOFF_TARGETS,
                          HoldShort, LineUpAndWait, MATRIX, NoOp, ReadbackObserved, RESERVATION_KINDS, RunwayVacated,
                          STALE_S, State, Unresolved, apply, fold, normalize_runway)


@pytest.mark.parametrize("text,expected", [
    ("three one", "31"),
    ("one three", "13"),
    ("one six right", "16R"),
    ("two four left", "24L"),
    ("zero six centre", "06C"),
    ("zero six center", "06C"),
    ("31", "31"),
    ("16r", "16R"),
    ("", None),
    ("three", "03"),       # US phraseology drops the leading zero: "runway three"
    ("four left", "04L"),
    ("nine", "09"),
    ("4l", "04L"),
    ("zero", None),        # no runway 00
    ("four zero", None),   # no such runway: heading 01-36 only
    ("left", None),
])
def test_normalize_runway(text, expected):
    assert normalize_runway(text) == expected


def test_events_are_frozen_keyword_only_and_typed():
    e = ClearToLand(callsign="csa one two three", runway="31", t=12.5, text="csa one two three runway three one cleared to land")
    assert (e.callsign, e.runway, e.t, e.kind) == ("csa one two three", "31", 12.5, "LAND")
    with pytest.raises(Exception):
        e.runway = "13"  # frozen
    with pytest.raises(TypeError):
        ClearToLand("csa one two three", "31")  # positional not allowed
    assert ClearToLand(callsign="a", runway="31") != ClearTakeoff(callsign="a", runway="31")  # class matters
    assert ClearToLand(callsign="a", runway="31") == ClearToLand(callsign="a", runway="31")


def test_event_kinds():
    assert ClearTakeoff.kind == "TAKEOFF"
    assert LineUpAndWait.kind == "LUAW"
    assert ClearToCross.kind == "CROSS"
    assert HoldShort.kind == "HOLD_SHORT"
    assert Handoff(callsign="a", to="ground").to == "ground"
    assert ReadbackObserved(callsign="a", text="roger").text == "roger"
    assert isinstance(RunwayVacated(callsign="a"), Event)
    assert isinstance(GoAround(callsign="a"), Event)
    assert NoOp().callsign == ""


def _kinds(state, runway):
    return [(r.callsign, r.kind) for r in state.runways.get(runway, ())]


def test_land_after_land_is_anticipated_separation_not_a_conflict():
    state, conflicts = fold([ClearToLand(callsign="a", runway="31"), ClearToLand(callsign="b", runway="31")])
    assert conflicts == []
    assert _kinds(state, "31") == [("a", "LAND"), ("b", "LAND")]


def test_luaw_then_land_same_runway_is_an_alert():  # Austin 2023 FedEx / Southwest pattern
    _, conflicts = fold([LineUpAndWait(callsign="southwest", runway="18L", t=0.0),
                         ClearToLand(callsign="fedex", runway="18L", t=30.0)])
    assert len(conflicts) == 1
    c = conflicts[0]
    assert (c.type, c.severity, c.runway, c.callsigns, c.seq) == ("RUNWAY", "alert", "18L", ("fedex", "southwest"), 2)
    assert "fedex" in c.explanation and "southwest" in c.explanation and "18L" in c.explanation


def test_cross_against_active_landing_is_an_alert():
    _, conflicts = fold([ClearToLand(callsign="a", runway="13"), ClearToCross(callsign="b", runway="13")])
    assert [(c.severity, c.callsigns) for c in conflicts] == [("alert", ("b", "a"))]


def test_takeoff_after_luaw_same_callsign_is_an_upgrade_not_a_conflict():
    state, conflicts = fold([LineUpAndWait(callsign="a", runway="13"), ClearTakeoff(callsign="a", runway="13")])
    assert conflicts == []
    assert _kinds(state, "13") == [("a", "TAKEOFF")]
    assert (state.aircraft["a"].runway, state.aircraft["a"].kind) == ("13", "TAKEOFF")


def test_takeoff_after_luaw_different_callsign_is_an_alert():
    _, conflicts = fold([LineUpAndWait(callsign="a", runway="13"), ClearTakeoff(callsign="b", runway="13")])
    assert [c.severity for c in conflicts] == ["alert"]


def test_takeoff_after_takeoff_and_luaw_after_luaw_are_warnings():
    _, c1 = fold([ClearTakeoff(callsign="a", runway="13"), ClearTakeoff(callsign="b", runway="13")])
    _, c2 = fold([LineUpAndWait(callsign="a", runway="13"), LineUpAndWait(callsign="b", runway="13")])
    assert [c.severity for c in c1] == ["warning"] and [c.severity for c in c2] == ["warning"]


def test_cross_after_cross_is_ok():
    _, conflicts = fold([ClearToCross(callsign="a", runway="13"), ClearToCross(callsign="b", runway="13")])
    assert conflicts == []


def test_different_runways_never_conflict():
    _, conflicts = fold([ClearToLand(callsign="a", runway="31"), ClearToCross(callsign="b", runway="13")])
    assert conflicts == []


def test_one_new_reservation_can_conflict_with_several_active_ones():
    _, conflicts = fold([ClearToLand(callsign="a", runway="31"), LineUpAndWait(callsign="b", runway="31"),
                         ClearToCross(callsign="c", runway="31")])
    # b vs a (LUAW after LAND = alert), then c vs a (alert) and c vs b (CROSS after LUAW = warning)
    assert [(c.callsigns, c.severity) for c in conflicts] == [(("b", "a"), "alert"), (("c", "a"), "alert"), (("c", "b"), "warning")]


def test_matrix_is_complete_and_matches_the_spec():
    assert set(MATRIX) == {(n, a) for n in RESERVATION_KINDS for a in RESERVATION_KINDS}
    assert set(MATRIX.values()) <= {"ok", "warning", "alert"}
    assert MATRIX[("LAND", "LAND")] == "ok" and MATRIX[("LAND", "LUAW")] == "alert"
    assert MATRIX[("CROSS", "CROSS")] == "ok" and MATRIX[("TAKEOFF", "TAKEOFF")] == "warning"


def test_a_new_instruction_moves_the_aircraft_off_its_old_runway():
    state, _ = fold([ClearToLand(callsign="a", runway="31"), ClearToCross(callsign="a", runway="13")])
    assert "31" not in state.runways and _kinds(state, "13") == [("a", "CROSS")]


def test_apply_does_not_mutate_its_input_and_seq_counts_every_event():
    s0 = State()
    s1, _ = apply(s0, ClearToLand(callsign="a", runway="31"))
    assert s0.seq == 0 and s0.runways == {} and s0.aircraft == {}
    assert s1.seq == 1 and s1.aircraft["a"].last_seq == 1
    s2, _ = fold([NoOp(), NoOp()], s1)
    assert s2.seq == 3


def test_runway_vacated_releases_so_a_crossing_is_fine():
    state, conflicts = fold([ClearToLand(callsign="a", runway="31"), RunwayVacated(callsign="a"),
                             ClearToCross(callsign="b", runway="31")])
    assert conflicts == []
    assert _kinds(state, "31") == [("b", "CROSS")]
    assert (state.aircraft["a"].runway, state.aircraft["a"].kind) == (None, None)


def test_handoff_to_ground_releases_landing_and_crossing_but_tower_does_not():
    _, c = fold([ClearToLand(callsign="a", runway="31"), Handoff(callsign="a", to="ground"), ClearToCross(callsign="b", runway="31")])
    assert c == []
    _, c = fold([ClearToCross(callsign="a", runway="31"), Handoff(callsign="a", to="ground"), ClearToLand(callsign="b", runway="31")])
    assert c == []
    _, c = fold([ClearToLand(callsign="a", runway="31"), Handoff(callsign="a", to="tower"), ClearToCross(callsign="b", runway="31")])
    assert [x.severity for x in c] == ["alert"]


def test_handoff_to_departure_releases_takeoff_only():
    _, c = fold([ClearTakeoff(callsign="a", runway="31"), Handoff(callsign="a", to="departure"), ClearToLand(callsign="b", runway="31")])
    assert c == []
    _, c = fold([ClearToLand(callsign="a", runway="31"), Handoff(callsign="a", to="departure"), ClearToCross(callsign="b", runway="31")])
    assert [x.severity for x in c] == ["alert"]


def test_go_around_cancels_landing_only():
    state, c = fold([ClearToLand(callsign="a", runway="31"), GoAround(callsign="a"), ClearToCross(callsign="b", runway="31")])
    assert c == [] and _kinds(state, "31") == [("b", "CROSS")]
    state, _ = fold([ClearTakeoff(callsign="a", runway="31"), GoAround(callsign="a")])
    assert _kinds(state, "31") == [("a", "TAKEOFF")]


def test_stale_reservation_is_dropped_silently():
    _, c = fold([ClearToLand(callsign="a", runway="31", t=0.0), ClearToCross(callsign="b", runway="31", t=STALE_S["LAND"] + 1)])
    assert c == []
    state, c = fold([ClearToLand(callsign="a", runway="31", t=0.0), ClearToCross(callsign="b", runway="31", t=100.0)])
    assert [x.severity for x in c] == ["alert"]
    state, _ = fold([NoOp(t=100 + max(STALE_S.values()) + 1)], state)   # both the t=0 LAND and the t=100 CROSS are now stale
    assert state.runways == {} and state.aircraft["a"].runway is None


def test_hold_short_never_conflicts_and_is_recorded_until_the_next_instruction():
    state, c = fold([ClearToLand(callsign="a", runway="13"), HoldShort(callsign="b", runway="13")])
    assert c == []
    assert state.aircraft["b"].holding_short == "13" and _kinds(state, "13") == [("a", "LAND")]
    state, c = fold([ClearToCross(callsign="b", runway="13")], state)
    assert state.aircraft["b"].holding_short is None and state.aircraft["b"].kind == "CROSS"


def test_release_events_for_unknown_callsigns_do_not_crash():
    state, c = fold([RunwayVacated(callsign="zzz"), GoAround(callsign=""), Handoff(callsign="", to="ground")])
    assert c == [] and state.seq == 3


def test_handoff_and_hold_short_with_text_set_pending():
    state, _ = fold([Handoff(callsign="a", to="ground", text="a contact ground one two one nine")])
    assert state.aircraft["a"].pending == "a contact ground one two one nine"
    state, _ = fold([HoldShort(callsign="b", runway="13", text="b hold short of runway one three")], state)
    assert state.aircraft["b"].pending == "b hold short of runway one three"
    state, _ = fold([Handoff(callsign="c", to="ground")], state)
    assert state.aircraft["c"].pending is None


CSA = "csa one two three"
LAND_31 = ClearToLand(callsign=CSA, runway="31", text="csa one two three runway three one cleared to land")


def test_correct_readback_clears_pending_without_conflict():
    state, c = fold([LAND_31, ReadbackObserved(callsign=CSA, text="cleared to land runway three one csa one two three")])
    assert c == [] and state.aircraft[CSA].pending is None


def test_wrong_runway_in_readback_is_an_alert():
    state, c = fold([LAND_31, ReadbackObserved(callsign=CSA, text="cleared to land runway one three csa one two three")])
    assert len(c) == 1
    assert (c[0].type, c[0].severity, c[0].runway, c[0].callsigns, c[0].seq) == ("READBACK", "alert", "31", (CSA,), 2)
    assert "three one" in c[0].explanation and "one three" in c[0].explanation
    assert state.aircraft[CSA].pending is None


def test_missing_frequency_after_handoff_is_a_warning():
    lh = "lufthansa five mike echo"
    events = [Handoff(callsign=lh, to="ground", text="lufthansa five mike echo contact ground one two one nine bye"),
              ReadbackObserved(callsign=lh, text="one two one five bye bye lufthansa five mike echo")]
    _, c = fold(events)
    assert [(x.type, x.severity, x.runway) for x in c] == [("READBACK", "warning", None)]


def test_readback_with_nothing_pending_is_ignored():
    state, c = fold([ReadbackObserved(callsign=CSA, text="roger")])
    assert c == [] and state.aircraft == {}
    state, c = fold([LAND_31, ReadbackObserved(callsign=CSA, text="cleared to land runway three one csa one two three"),
                     ReadbackObserved(callsign=CSA, text="runway vacated csa one two three")])
    assert c == []


def test_instruction_without_text_expects_no_readback():
    _, c = fold([ClearToLand(callsign=CSA, runway="31"), ReadbackObserved(callsign=CSA, text="roger")])
    assert c == []


def test_instruction_with_no_readback_items_expects_nothing():
    _, c = fold([GoAround(callsign=CSA, text="csa one two three go around"), ReadbackObserved(callsign=CSA, text="going around")])
    assert c == []


def test_unknown_callsign_instruction_reserves_but_only_warns():
    # An instruction whose callsign the parser could not extract still occupies the runway ...
    state, c = fold([LineUpAndWait(callsign="a", runway="31", t=0.0), ClearTakeoff(callsign="", runway="31", t=5.0)])
    assert _kinds(state, "31") == [("a", "LUAW"), ("", "TAKEOFF")]
    # ... but the engine cannot tell whether it is a different aircraft, so it warns instead of alerting.
    assert [(x.severity, x.callsigns) for x in c] == [("warning", ("", "a"))]
    assert "an unidentified aircraft" in c[0].explanation
    # Two unknowns on one runway: also a warning, never an alert.
    _, c = fold([ClearToLand(callsign="", runway="31", t=0.0), ClearToCross(callsign="", runway="31", t=5.0)])
    assert [x.severity for x in c] == ["warning"]
    # Nothing can release an unknown reservation except staleness.
    state, _ = fold([ClearToLand(callsign="", runway="31", t=0.0), RunwayVacated(callsign="", t=5.0)])
    assert _kinds(state, "31") == [("", "LAND")]
    state, _ = fold([NoOp(t=STALE_S["LAND"] + 1)], state)
    assert state.runways == {}


# --- phase 2.5 (spec addendum A.3) -------------------------------------------------------------

def test_staleness_is_per_kind(monkeypatch):
    assert set(STALE_S) == set(RESERVATION_KINDS) | {"HOLD_SHORT"}
    monkeypatch.setitem(engine.STALE_S, "CROSS", 30.0)
    _, c = fold([ClearToCross(callsign="a", runway="31", t=0.0), ClearToLand(callsign="b", runway="31", t=31.0)])
    assert c == []                                     # the crossing timed out after 30 s
    _, c = fold([ClearToLand(callsign="a", runway="31", t=0.0), ClearToCross(callsign="b", runway="31", t=31.0)])
    assert [x.severity for x in c] == ["alert"]        # the landing clearance did not


def test_landing_clearance_outlives_the_austin_gap():
    # Austin 2023: FedEx cleared to land 18L at 0634:14, Southwest cleared for takeoff on 18L at 0638:58, 284 s later.
    assert STALE_S["LAND"] >= 284
    _, c = fold([ClearToLand(callsign="fedex", runway="18L", t=0.0), ClearTakeoff(callsign="southwest", runway="18L", t=284.0)])
    assert [(x.type, x.severity, x.runway) for x in c] == [("RUNWAY", "alert", "18L")]


def test_hold_short_expires():
    state, _ = fold([HoldShort(callsign="b", runway="13", t=0.0)])
    assert state.aircraft["b"].holding_short == "13"
    state, _ = fold([NoOp(t=STALE_S["HOLD_SHORT"] - 1)], state)
    assert state.aircraft["b"].holding_short == "13"
    state, _ = fold([NoOp(t=STALE_S["HOLD_SHORT"] + 1)], state)
    assert (state.aircraft["b"].holding_short, state.aircraft["b"].holding_short_t) == (None, None)


def test_vacating_or_leaving_the_frequency_ends_a_hold_short():
    for release in (RunwayVacated(callsign="b"), Handoff(callsign="b", to="ground"), Handoff(callsign="b", to="departure")):
        state, _ = fold([HoldShort(callsign="b", runway="13"), release])
        assert state.aircraft["b"].holding_short is None, release
    state, _ = fold([HoldShort(callsign="b", runway="13"), Handoff(callsign="b", to="tower")])
    assert state.aircraft["b"].holding_short == "13"


def test_hold_short_cancels_the_aircrafts_clearance_for_that_runway():
    state, _ = fold([ClearToCross(callsign="b", runway="13"), HoldShort(callsign="b", runway="13")])
    assert _kinds(state, "13") == []
    assert (state.aircraft["b"].runway, state.aircraft["b"].kind, state.aircraft["b"].holding_short) == (None, None, "13")
    _, c = fold([ClearToCross(callsign="b", runway="13"), HoldShort(callsign="b", runway="13"), ClearToLand(callsign="a", runway="13")])
    assert c == []


def test_hold_short_of_another_runway_keeps_the_crossing():
    # Recording 528: "air france one nine eight romeo ... cross runway one three continue via delta to hold short of runway
    # two four" parses to a CROSS on 13 followed by a HOLD_SHORT of 24. The crossing must survive the second event.
    state, c = fold([ClearToCross(callsign="af", runway="13"), HoldShort(callsign="af", runway="24"),
                     ClearToLand(callsign="csa", runway="13")])
    assert _kinds(state, "13") == [("af", "CROSS"), ("csa", "LAND")]
    assert [(x.type, x.severity, x.runway) for x in c] == [("RUNWAY", "alert", "13")]


def test_readback_conflict_names_the_runway_that_was_missed():
    hold = HoldShort(callsign="b", runway="13", text="b hold short of runway one three")
    _, c = fold([hold, ReadbackObserved(callsign="b", text="holding short runway three one b")])
    assert [(x.type, x.severity, x.runway) for x in c] == [("READBACK", "alert", "13")]   # was None before phase 2.5


def test_readback_conflict_falls_back_to_the_hold_short_runway():
    # The missed item is a "contact tower" frequency, not a ground handoff: a handoff to ground (or departure) would
    # release the hold-short (see heuristic-handoff-release in atcdb/doctrine.py), which the real rules parser would
    # also emit from that text, making this scenario impossible. A handoff to tower releases nothing.
    hold = HoldShort(callsign="b", runway="13", text="b hold short of runway one three contact tower one one nine decimal seven")
    _, c = fold([hold, ReadbackObserved(callsign="b", text="holding short runway one three b")])
    assert [(x.type, x.severity, x.runway) for x in c] == [("READBACK", "warning", "13")]


def test_unknown_handoff_target_releases_nothing_and_is_counted():
    assert HANDOFF_TARGETS == ("ground", "departure", "tower", "approach")
    state, c = fold([ClearToLand(callsign="a", runway="31"), Handoff(callsign="a", to="grund"), ClearToCross(callsign="b", runway="31")])
    assert [x.severity for x in c] == ["alert"] and state.ignored == 1
    state, _ = fold([ClearToLand(callsign="a", runway="31"), Handoff(callsign="a", to="ground")])
    assert state.ignored == 0


def test_runway_conflicts_carry_their_doctrine_basis():
    _, c = fold([ClearToLand(callsign="fedex", runway="18L"), ClearTakeoff(callsign="southwest", runway="18L")])
    assert [x.basis for x in c] == ["icao-4444-7.9.2"]
    _, c = fold([ClearTakeoff(callsign="southwest", runway="18L"), ClearToLand(callsign="fedex", runway="18L")])
    assert [x.basis for x in c] == ["icao-4444-7.10.1"]
    _, c = fold([ClearToLand(callsign="a", runway="31"), ClearToCross(callsign="b", runway="31")])
    assert [x.basis for x in c] == [None]   # no verified citation for this cell yet


# --- phase 3a (spec addendum A.4, A.7.2) -------------------------------------------------------

def test_unresolved_is_counted_and_changes_nothing_else():
    state, _ = fold([ClearToLand(callsign="a", runway="31")])
    after, c = fold([Unresolved(callsign="b", raw='{"kind": "CROSS", "runway": "three seven"}')], state)
    assert c == [] and after.ignored == 1
    assert (after.runways, after.aircraft) == (state.runways, state.aircraft)
    assert isinstance(ENGINE_VERSION, str) and ENGINE_VERSION
