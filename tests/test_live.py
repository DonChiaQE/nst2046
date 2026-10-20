from live_fakes import Scripted

from atcdb import parse_rules
from atcdb.engine import State
from atcdb.live import Line, Track, step_payload

LAND_31 = "csa one two three runway three one cleared to land"
TAKEOFF_31 = "lufthansa four five six runway three one cleared for takeoff"
# a landing clearance without the word "runway": the rules parser drops it (spec addendum A.2), Claude reads it
BARE_LAND = "fedex one two three one eight left cleared to land"
TAKEOFF_18L = "southwest seven zero eight runway one eight left cleared for takeoff"


def line(seq, text, role="controller", t=None):
    return Line(seq, role, float(seq * 10 if t is None else t), text, "typed", "none")


# --- Track ----------------------------------------------------------------------------------------------------------

def test_a_track_folds_lines_through_its_own_engine():
    track = Track("rules", parse_rules.parse)
    first = track.apply(line(0, LAND_31), [])
    assert [type(e).__name__ for e in first.events] == ["ClearToLand"] and first.conflicts == ()
    second = track.apply(line(1, TAKEOFF_31), [line(0, LAND_31)])
    assert [(c.type, c.severity, c.runway) for c in second.conflicts] == [("RUNWAY", "alert", "31")]
    assert {r.kind for r in track.state.runways["31"]} == {"LAND", "TAKEOFF"}


def test_a_track_gives_the_parser_window_context():
    parser = Scripted()
    track = Track("claude", parser)
    track.apply(line(0, LAND_31), [])
    track.apply(line(1, "lufthansa four five six hold position", role="pilot"), [line(0, LAND_31)])
    ctx = parser.contexts[1]
    assert ctx.mode == "window" and ctx.role == "pilot"
    assert ctx.history == (("controller", LAND_31),) and ctx.active_runways == ("31",)


def test_a_parser_failure_is_an_error_step_that_keeps_the_state():
    track = Track("claude", Scripted(fail_texts=[TAKEOFF_31]))
    track.apply(line(0, LAND_31), [])
    before = track.state
    step = track.apply(line(1, TAKEOFF_31), [line(0, LAND_31)])
    assert step.events == () and step.conflicts == () and step.state is before
    assert step.error == "RuntimeError: Claude unavailable: no internet connection"


def test_undo_drops_only_the_last_step_and_truncate_drops_from_a_line_on():
    track = Track("rules", parse_rules.parse)
    for k, text in enumerate([LAND_31, TAKEOFF_31, LAND_31]):
        track.apply(line(k, text), [])
    assert not track.undo(1) and track.undo(2) and [s.seq for s in track.steps] == [0, 1]
    track.truncate(1)
    assert [s.seq for s in track.steps] == [0]
    assert Track("x", parse_rules.parse).state == State()


def test_step_payload_uses_the_api_shapes_and_leaves_out_noop():
    nothing = Track("rules", parse_rules.parse).apply(line(0, "csa one two three good morning"), [])
    assert [type(e).__name__ for e in nothing.events] == ["NoOp"] and step_payload("rules", nothing)["events"] == []
    step = Track("rules", parse_rules.parse).apply(line(0, LAND_31), [])
    assert step_payload("rules", step) == {
        "seq": 0, "extractor": "rules",
        "events": [{"kind": "LAND", "callsign": "csa one two three", "runway": "31", "to": None}],
        "conflicts": [], "runways": {"31": [{"callsign": "csa one two three", "kind": "LAND"}]}, "error": None}
