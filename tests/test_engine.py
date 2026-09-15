import pytest

from atcdb.engine import (ClearTakeoff, ClearToCross, ClearToLand, Event, GoAround, Handoff, HoldShort,
                          LineUpAndWait, MATRIX, NoOp, ReadbackObserved, RESERVATION_KINDS, RunwayVacated,
                          State, apply, fold, normalize_runway)


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
    ("three", None),
    ("four zero", None),   # no such runway: heading 01-36 only
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
