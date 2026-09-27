import pytest

from atcdb.engine import (ClearTakeoff, ClearToCross, ClearToLand, GoAround, Handoff, HoldShort, LineUpAndWait, NoOp,
                          ReadbackObserved, RunwayVacated, Unresolved)
from atcdb.parsing import CONTEXT_MODES, Context, Transmission, event_to_row, row_to_event

TEXT = "csa one two three runway three one cleared to land"


@pytest.mark.parametrize("event,row", [
    (ClearToLand(callsign="csa one two three", runway="31"), ("LAND", "csa one two three", "31", None)),
    (ClearTakeoff(callsign="a", runway="13"), ("TAKEOFF", "a", "13", None)),
    (LineUpAndWait(callsign="a", runway="13"), ("LUAW", "a", "13", None)),
    (ClearToCross(callsign="a", runway="13"), ("CROSS", "a", "13", None)),
    (HoldShort(callsign="a", runway="24"), ("HOLD_SHORT", "a", "24", None)),
    (RunwayVacated(callsign="a"), ("VACATED", "a", None, None)),
    (GoAround(callsign="a"), ("GO_AROUND", "a", None, None)),
    (Handoff(callsign="a", to="ground"), ("HANDOFF", "a", None, '{"to": "ground"}')),
    (ReadbackObserved(callsign="a", text="roger"), ("READBACK", "a", None, None)),
    (NoOp(), ("NOOP", "", None, None)),
    (Unresolved(callsign="a", raw="CROSS three seven"), ("UNRESOLVED", "a", None, '{"raw": "CROSS three seven"}')),
])
def test_event_to_row(event, row):
    assert event_to_row(event) == row


def test_row_to_event_reattaches_time_and_text():
    e = row_to_event("LAND", "csa one two three", "31", None, t=12.5, text=TEXT)
    assert e == ClearToLand(callsign="csa one two three", runway="31", t=12.5, text=TEXT)
    h = row_to_event("HANDOFF", "a", None, '{"to": "ground"}', t=1.0, text="a contact ground")
    assert h == Handoff(callsign="a", to="ground", t=1.0, text="a contact ground")
    r = row_to_event("READBACK", "a", None, None, t=2.0, text="roger a")
    assert r == ReadbackObserved(callsign="a", text="roger a", t=2.0)
    assert row_to_event("NOOP", "", None, None, t=3.0, text="hi") == NoOp(t=3.0, text="hi")


def test_round_trip_every_kind():
    events = [ClearToLand(callsign="a", runway="31", t=1.0, text="x"), HoldShort(callsign="b", runway="13", t=1.0, text="x"),
              RunwayVacated(callsign="a", t=1.0, text="x"), GoAround(callsign="a", t=1.0, text="x"),
              Handoff(callsign="a", to="departure", t=1.0, text="x"), ReadbackObserved(callsign="a", text="x", t=1.0), NoOp(t=1.0, text="x"),
              Unresolved(callsign="a", raw="LAND", t=1.0, text="x")]
    for e in events:
        assert row_to_event(*event_to_row(e), t=1.0, text="x") == e


def test_unknown_kind_raises():
    with pytest.raises(KeyError):
        row_to_event("TELEPORT", "a", None, None)


def test_context_defaults_and_modes():
    assert CONTEXT_MODES == ("none", "role", "window")
    c = Context()
    assert (c.mode, c.role, c.history, c.active_callsigns, c.active_runways) == ("window", "unknown", (), (), ())
    tx = Transmission(id=1, transcript_id=2, text="hello", role="pilot", start_s=3.5)
    assert (tx.id, tx.transcript_id, tx.role, tx.start_s) == (1, 2, "pilot", 3.5)
