import pytest

from atcdb.engine import (ClearTakeoff, ClearToCross, ClearToLand, Event, GoAround, Handoff, HoldShort,
                          LineUpAndWait, NoOp, ReadbackObserved, RunwayVacated, normalize_runway)


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
