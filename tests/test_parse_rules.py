from atcdb.engine import (ClearTakeoff, ClearToCross, ClearToLand, GoAround, Handoff, HoldShort, LineUpAndWait, NoOp,
                          RunwayInstruction)
from atcdb.parse_rules import VERSION, blank_values, parse, take_prefix
from atcdb.parsing import Context, Transmission

CTL = Context(mode="role", role="controller")
PLT = Context(mode="role", role="pilot")


def _tx(text, role="controller", t=0.0):
    return Transmission(id=1, transcript_id=1, text=text, role=role, start_s=t)


def _kinds(events):
    return [(type(e).__name__, e.callsign, getattr(e, "runway", getattr(e, "to", None))) for e in events]


def test_version_is_a_string():
    assert isinstance(VERSION, str) and VERSION


def test_takeoff_clearance_with_runway_before_the_phrase():
    text = "csa seven eight eight runway one three cleared for takeoff wind zero three zero degrees"
    assert parse(_tx(text, t=5.0), CTL) == [ClearTakeoff(callsign="csa seven eight eight", runway="13", t=5.0, text=text)]


def test_landing_clearance_variants():
    ev = parse(_tx("shamrock six four four runway three one clear to land wind zero six zero degrees and five knots"), CTL)
    assert _kinds(ev) == [("ClearToLand", "shamrock six four four", "31")]
    ev = parse(_tx("hotel lima hotel wind zero one zero degrees one zero knots runway one zero cleared to land"), CTL)
    assert _kinds(ev) == [("ClearToLand", "hotel lima hotel", "10")]


def test_line_up_then_takeoff_in_one_transmission_yields_two_events():
    ev = parse(_tx("sky travel one one nine two line up runway three one cleared for takeoff wind is calm"), CTL)
    assert _kinds(ev) == [("LineUpAndWait", "sky travel one one nine two", "31"), ("ClearTakeoff", "sky travel one one nine two", "31")]


def test_line_up_and_wait_variants():
    assert _kinds(parse(_tx("swiss one eight line up and wait runway one zero"), CTL)) == [("LineUpAndWait", "swiss one eight", "10")]
    assert _kinds(parse(_tx("csa four zero six line up runway one three and wait"), CTL)) == [("LineUpAndWait", "csa four zero six", "13")]


def test_cross_and_hold_short_take_the_runway_that_follows():
    text = "air france one nine eight romeo now expedite cross runway one three continue via delta to hold short of runway two four"
    assert _kinds(parse(_tx(text), CTL)) == [("ClearToCross", "air france one nine eight romeo", "13"),
                                             ("HoldShort", "air france one nine eight romeo", "24")]


def test_hold_short_ignores_a_taxi_via_runway_mention():
    ev = parse(_tx("csa four delta romeo taxi via runway two four and hold short of runway one three"), CTL)
    assert _kinds(ev) == [("HoldShort", "csa four delta romeo", "13")]


def test_handoffs():
    assert _kinds(parse(_tx("csa eight two nine vacate to the left contact ruzyne ground one two one point nine"), CTL)) == \
        [("Handoff", "csa eight two nine", "ground")]
    assert _kinds(parse(_tx("lufthansa five mike echo contact ground one two one nine bye"), CTL)) == \
        [("Handoff", "lufthansa five mike echo", "ground")]
    assert _kinds(parse(_tx("contact departure one two zero decimal five"), CTL)) == [("Handoff", "", "departure")]
    assert _kinds(parse(_tx("sunturk niner four seven taxiway juliett cross runway two eight contact apron one two one decimal seven five five bye"), CTL)) == \
        [("ClearToCross", "sunturk niner four seven", "28"), ("Handoff", "sunturk niner four seven", "ground")]


def test_go_around_instruction():
    assert _kinds(parse(_tx("csa one two three go around"), CTL)) == [("GoAround", "csa one two three", None)]


def test_no_instruction_yields_a_single_noop_carrying_the_text():
    text = "csa eight three eight whiskey reduce speed one sixty"
    assert parse(_tx(text, t=2.0), CTL) == [NoOp(t=2.0, text=text)]


def test_callsign_after_the_instruction_and_unknown_callsign():
    assert _kinds(parse(_tx("ok line up runway three one csa seven nine"), CTL)) == [("LineUpAndWait", "csa seven nine", "31")]
    ev = parse(_tx("right turn and runway three one cleared for takeoff wind one six zero degrees four knots"), CTL)
    assert _kinds(ev) == [("ClearTakeoff", "", "31")]


def test_missing_runway_uses_the_only_active_runway_in_window_mode_only():
    text = "hotel mike november line up in sequence"
    assert _kinds(parse(_tx(text), Context(mode="window", role="controller", active_runways=("31",)))) == \
        [("LineUpAndWait", "hotel mike november", "31")]
    assert _kinds(parse(_tx(text), Context(mode="window", role="controller", active_runways=("31", "13")))) == [("NoOp", "", None)]
    assert _kinds(parse(_tx(text), CTL)) == [("NoOp", "", None)]


def test_mixed_and_unknown_roles_are_parsed_like_controller():
    text = "csa seven three two zero line up runway three one cleared for takeoff wind calm line up three one csa"
    assert [type(e) for e in parse(_tx(text, role="mixed"), Context(mode="role", role="mixed"))] == [LineUpAndWait, ClearTakeoff]
    assert [type(e) for e in parse(_tx(text, role="unknown"), Context(mode="role", role="unknown"))] == [LineUpAndWait, ClearTakeoff]


def test_pilot_role_never_produces_instructions():
    ev = parse(_tx("cleared for takeoff runway three one csa two mike zulu", role="pilot"), PLT)
    assert not any(isinstance(e, RunwayInstruction) for e in ev)


def test_take_prefix_and_blank_values():
    assert take_prefix("csa four delta romeo taxi via".split()) == ["csa", "four", "delta", "romeo"]
    assert take_prefix("sky travel one one nine two".split()) == ["sky", "travel", "one", "one", "nine", "two"]
    assert take_prefix("hotel bravo sierra delta foxtrot tower hello".split()) == ["hotel", "bravo", "sierra", "delta", "foxtrot"]
    assert take_prefix("right turn and".split()) == []
    text = "csa seven eight eight runway one three cleared for takeoff wind zero three zero degrees"
    blanked = blank_values(text)
    assert len(blanked) == len(text)
    assert blanked.split() == ["csa", "seven", "eight", "eight", "cleared", "for", "takeoff"]
