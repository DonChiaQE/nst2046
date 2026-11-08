import pytest

from atcdb.engine import (ClearTakeoff, ClearToCross, ClearToLand, GoAround, Handoff, HoldShort, LineUpAndWait, NoOp,
                          ReadbackObserved, RunwayInstruction, RunwayVacated)
from atcdb.parse_rules import (VERSION, blank_values, count_unresolved, make_parser, parse, pilot_callsign,
                               snap_callsign, take_prefix, take_suffix)
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


def test_pilot_transmission_is_a_readback_with_trailing_callsign():
    text = "cleared to land csa nine seven five"
    assert parse(_tx(text, role="pilot", t=4.0), PLT) == [ReadbackObserved(callsign="csa nine seven five", text=text, t=4.0)]


def test_pilot_callsign_survives_trailing_filler_and_bye():
    assert pilot_callsign("cleared to land one three csa three eight whiskey and will expedite to") == "csa three eight whiskey"
    assert pilot_callsign("one two one nine bye bye lufthansa five mike echo") == "lufthansa five mike echo"
    assert pilot_callsign("cleared for takeoff runway three one air france one zero eight three good bye") == "air france one zero eight three"
    assert pilot_callsign("reducing one sixty csa eight eight whiskey") == "csa eight eight whiskey"
    assert pilot_callsign("descending flight level one hundred swiss one two four") == "swiss one two four"
    assert pilot_callsign("hotel bravo sierra delta foxtrot") == "hotel bravo sierra delta foxtrot"


def test_pilot_values_are_not_mistaken_for_callsigns():
    assert pilot_callsign("we are cleared for takeoff runway one three") == ""
    assert pilot_callsign("climbing flight level one zero zero") == ""
    assert pilot_callsign("roger") == ""


def test_pilot_reports_vacated_and_going_around():
    ev = parse(_tx("runway vacated csa one two three", role="pilot"), PLT)
    assert _kinds(ev) == [("ReadbackObserved", "csa one two three", None), ("RunwayVacated", "csa one two three", None)]
    ev = parse(_tx("going around csa one two three", role="pilot"), PLT)
    assert _kinds(ev) == [("ReadbackObserved", "csa one two three", None), ("GoAround", "csa one two three", None)]
    ev = parse(_tx("vacating via bravo csa one two three", role="pilot"), PLT)
    assert [type(e) for e in ev] == [ReadbackObserved, RunwayVacated]


def test_take_suffix():
    assert take_suffix("cleared to land csa nine seven five".split()) == ["csa", "nine", "seven", "five"]
    assert take_suffix("we are cleared for takeoff runway one three".split()) == []
    assert take_suffix("line up runway three one csa two mike".split()) == ["csa", "two", "mike"]


def test_snap_callsign_matches_abbreviations_in_order_only():
    active = ("csa eight three eight whiskey", "csa seven three zero", "air france one nine eight romeo")
    assert snap_callsign("csa eight eight whiskey", active) == "csa eight three eight whiskey"
    assert snap_callsign("air france one nine", active) == "air france one nine eight romeo"
    assert snap_callsign("csa seven three charlie", active) == "csa seven three charlie"   # charlie is not in any candidate
    assert snap_callsign("lufthansa seven three", active) == "lufthansa seven three"       # name disagrees
    assert snap_callsign("", active) == ""
    assert snap_callsign("csa eight", ("csa eight one", "csa eight two")) == "csa eight"     # ambiguous: leave it


def test_window_mode_snaps_pilot_callsign_but_role_mode_does_not():
    text = "reducing one sixty csa eight eight whiskey"
    win = Context(mode="window", role="pilot", active_callsigns=("csa eight three eight whiskey",))
    assert parse(_tx(text, role="pilot"), win)[0].callsign == "csa eight three eight whiskey"
    assert parse(_tx(text, role="pilot"), PLT)[0].callsign == "csa eight eight whiskey"


def test_none_mode_turns_a_pilot_readback_into_a_reservation():
    text = "cleared for takeoff runway three one csa two mike zulu"
    assert _kinds(parse(_tx(text, role="pilot"), Context(mode="none"))) == [("ClearTakeoff", "csa two mike zulu", "31")]


def test_count_unresolved_counts_instructions_with_no_runway():
    # Austin 2023, 0634:14: the landing clearance carries no "runway" token, so v1 cannot place it.
    austin = _tx("fedex fourteen thirty-two heavy austin tower one eight left cleared to land")
    assert parse(austin, CTL) == [NoOp(t=0.0, text=austin.text)]
    assert count_unresolved(austin, CTL) == 1
    assert count_unresolved(_tx("csa one two three runway three one cleared to land"), CTL) == 0
    assert count_unresolved(_tx("csa one two three cleared to land"), PLT) == 0              # pilots issue no instructions
    assert count_unresolved(_tx("csa one two three line up and wait cleared for takeoff"), CTL) == 2


def test_count_unresolved_follows_window_snapping():
    # With exactly one active runway, window mode places the clearance, so nothing is dropped.
    tx = _tx("fedex fourteen thirty-two heavy one eight left cleared to land")
    window = Context(mode="window", role="controller", active_runways=("18L",))
    assert _kinds(parse(tx, window)) == [("ClearToLand", "", "18L")]   # placed; the US callsign is a known v1 gap
    assert count_unresolved(tx, window) == 0


# --- phraseology convention: Context.single_digit_runways (atcdb/parse_rules.py, `_patterns`) -----------------------

parse_single = make_parser(single_digit_runways=True)   # a US tower: "runway four left" is a real designator


@pytest.mark.parametrize("text,runway", [
    ("delta one two three runway four left cleared to land", "04L"),
    ("delta one two three runway four cleared to land", "04"),
    ("delta one two three runway oh four left cleared to land", "04L"),
    ("delta one two three runway zero four left cleared to land", "04L"),
])
def test_a_us_tower_reads_a_single_digit_word_as_a_designator(text, runway):
    assert _kinds(parse_single(_tx(text), CTL)) == [("ClearToLand", "delta one two three", runway)]


@pytest.mark.parametrize("text", [
    "csa one two three line up runway three o",     # 27 of these in the corpus: a truncated "three one"
    "csa one two three line up runway two",
    "csa one two three hold short of runway one",
])
def test_the_default_refuses_a_lone_digit_word_so_a_truncation_is_not_read_as_a_runway(text):
    """Two digit-words are always spoken at the airports in this corpus, so a lone one is an ASR truncation.

    Reading it as a designator invents a runway the transmission never named; refusing it lets `_runway_for` fall
    back to the active runway in window context. 110 transcripts (73 gold, 37 ASR) have this shape and not one is a
    real single-digit designator.
    """
    assert all(r is None for _, _, r in _kinds(parse(_tx(text), CTL)))


def test_oh_is_read_as_zero_inside_a_designator_but_is_not_a_general_digit_word():
    """The narrow scope is the point: "oh" is a common interjection ("oh, roger"), so widening the shared
    `D`/`DIGITS` vocabulary would risk reading it as part of a callsign or another field."""
    from atcdb.parse_rules import DIGITS, _desig
    assert "oh" not in DIGITS
    assert _desig("oh four left") == "04L"
    assert _desig("zero four left") == "04L"
    assert _kinds(parse(_tx("csa one two three runway oh nine cleared to land"), CTL)) == \
        [("ClearToLand", "csa one two three", "09")]
