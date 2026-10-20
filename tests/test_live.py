import json
import threading
import time

import pytest
from live_fakes import Scripted, wav

from atcdb import parse_rules
from atcdb.engine import State
from atcdb.live import MIN_CLIP_S, Line, LiveSession, Track, Transcription, clip_seconds, step_payload

LAND_31 = "csa one two three runway three one cleared to land"
TAKEOFF_31 = "lufthansa four five six runway three one cleared for takeoff"
# a landing clearance without the word "runway": the rules parser drops it (spec addendum A.2), Claude reads it
BARE_LAND = "fedex one two three one eight left cleared to land"
TAKEOFF_18L = "southwest seven zero eight runway one eight left cleared for takeoff"


def line(seq, text, role="controller", t=None):
    return Line(seq, role, float(seq * 10 if t is None else t), text, "typed", "none")


def session(tmp_path, claude=None, whisper=None, timeout_s=8.0):
    tracks = {"rules": Track("rules", parse_rules.parse), "claude": Track("claude", claude or Scripted())}
    return LiveSession("s1", tracks, Transcription(lambda: whisper, timeout_s=timeout_s), tmp_path / "s1")


def extractions(events, extractor):
    return [e for e in events if e["type"] == "extraction" and e["extractor"] == extractor]


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


# --- LiveSession: typed lines ------------------------------------------------------------------------------------------

def test_typed_lines_are_normalized_then_read_by_both_extractors(tmp_path):
    s = session(tmp_path)
    assert s.submit_text("controller", 0.0, "CSA 123 runway 31 cleared to land") == 0
    events = s.wait_for(lambda ev: len([e for e in ev if e["type"] == "extraction"]) == 2)
    transcript = next(e for e in events if e["type"] == "transcript")
    assert transcript == {"id": 0, "type": "transcript", "seq": 0, "role": "controller", "t": 0.0, "text": LAND_31,
                          "source": "typed", "transcriber": "none", "preview_text": "", "error": None}
    assert {e["extractor"] for e in events if e["type"] == "extraction"} == {"rules", "claude"}


def test_each_extractor_keeps_its_own_engine_so_they_can_disagree(tmp_path):
    s = session(tmp_path)
    s.submit_text("controller", 0.0, BARE_LAND)
    s.submit_text("controller", 284.0, TAKEOFF_18L)
    events = s.wait_for(lambda ev: len(extractions(ev, "rules")) == 2 and len(extractions(ev, "claude")) == 2)
    rules, claude = extractions(events, "rules"), extractions(events, "claude")
    assert rules[0]["events"] == [] and rules[1]["conflicts"] == []   # rules never reserved 18L
    assert [(c["type"], c["severity"], c["runway"]) for c in claude[1]["conflicts"]] == [("RUNWAY", "alert", "18L")]


def test_rules_never_wait_for_a_slow_claude_and_claude_keeps_line_order(tmp_path):
    s = session(tmp_path, claude=Scripted(delay=0.3))
    for k, text in enumerate([LAND_31, TAKEOFF_31, LAND_31]):
        s.submit_text("controller", k * 10.0, text)
    events = s.wait_for(lambda ev: len(extractions(ev, "rules")) == 3, timeout=0.6)
    assert len(extractions(events, "claude")) < 3   # all three rules results arrived while Claude still worked
    events = s.wait_for(lambda ev: len(extractions(ev, "claude")) == 3)
    assert [e["seq"] for e in extractions(events, "claude")] == [0, 1, 2]


def test_a_claude_failure_leaves_rules_alone_and_retry_redoes_it_and_every_later_line(tmp_path):
    claude = Scripted(fail_texts=[LAND_31])
    s = session(tmp_path, claude=claude)
    s.submit_text("controller", 0.0, LAND_31)
    s.submit_text("controller", 10.0, TAKEOFF_31)
    events = s.wait_for(lambda ev: len(extractions(ev, "claude")) == 2 and len(extractions(ev, "rules")) == 2)
    failed, after = extractions(events, "claude")
    assert failed["error"].endswith("no internet connection") and failed["events"] == []
    assert after["conflicts"] == []   # parsed against the state without the failed line
    assert len(extractions(events, "rules")[1]["conflicts"]) == 1
    s.retry("claude", 0)
    events = s.wait_for(lambda ev: len(extractions(ev, "claude")) == 4)
    redo = extractions(events, "claude")[2:]
    assert [e["seq"] for e in redo] == [0, 1] and redo[0]["error"] is None
    assert [c["type"] for c in redo[1]["conflicts"]] == ["RUNWAY"]
    assert [s.seq for s in s.tracks["claude"].steps] == [0, 1]
    with pytest.raises(ValueError, match="unknown extractor"):
        s.retry("sonnet", 0)


def test_undo_removes_the_last_line_from_both_engines(tmp_path):
    s = session(tmp_path)
    s.submit_text("controller", 0.0, LAND_31)
    s.submit_text("controller", 10.0, TAKEOFF_31)
    s.wait_for(lambda ev: len([e for e in ev if e["type"] == "extraction"]) == 4)
    assert s.undo() == 1
    assert [st.seq for st in s.tracks["rules"].steps] == [0] and [st.seq for st in s.tracks["claude"].steps] == [0]
    s.submit_text("controller", 20.0, LAND_31)   # line 2 sees line 0 only
    events = s.wait_for(lambda ev: len(extractions(ev, "rules")) == 3)
    assert extractions(events, "rules")[2]["conflicts"] == []   # LAND after LAND is lawful; the takeoff is gone
    assert any(e["type"] == "undone" and e["seq"] == 1 for e in events)
    assert s.undo() == 2 and s.undo() == 0 and s.undo() is None


def test_undo_while_claude_is_still_parsing_discards_its_late_result(tmp_path):
    s = session(tmp_path, claude=Scripted(delay=0.3))
    s.submit_text("controller", 0.0, LAND_31)
    s.wait_for(lambda ev: len(extractions(ev, "rules")) == 1)
    assert s.undo() == 0
    time.sleep(0.5)
    assert extractions(s.events_after(), "claude") == [] and s.tracks["claude"].steps == []


def test_bad_roles_and_sources_are_refused(tmp_path):
    s = session(tmp_path)
    with pytest.raises(ValueError, match="unknown role"):
        s.submit_text("tower", 0.0, LAND_31)
    with pytest.raises(ValueError, match="unknown source"):
        s.submit_text("pilot", 0.0, LAND_31, source="radio")


# --- LiveSession: audio ------------------------------------------------------------------------------------------------

def test_a_clip_is_transcribed_by_whisper_and_saved(tmp_path):
    s = session(tmp_path, whisper=lambda clip: {"text": "CSA 123, runway 31, cleared to land."})
    seq = s.submit_audio("controller", 3.0, wav(1.0), preview_text="csa one two three runway three one")
    events = s.wait_for(lambda ev: len(extractions(ev, "rules")) == 1)
    transcript = next(e for e in events if e["type"] == "transcript")
    assert (transcript["text"], transcript["transcriber"], transcript["source"]) == (LAND_31, "whisper", "speech")
    assert clip_seconds((tmp_path / "s1" / f"clip_{seq}.wav").read_bytes()) == pytest.approx(1.0)


def test_a_clip_shorter_than_half_a_second_is_dropped(tmp_path):
    s = session(tmp_path, whisper=lambda clip: {"text": "thank you"})
    assert s.submit_audio("pilot", 1.0, wav(MIN_CLIP_S - 0.2)) is None
    events = s.wait_for(lambda ev: any(e["type"] == "dropped" for e in ev))
    assert events[0]["reason"] == "Too short" and not list((tmp_path / "s1").glob("clip_*.wav"))
    with pytest.raises(ValueError, match="not a readable WAV"):
        s.submit_audio("pilot", 1.0, b"not audio")


def test_a_slow_whisper_falls_back_to_apple_text_and_later_lines_do_not_queue_behind_it(tmp_path):
    release = threading.Event()

    def stuck(clip):
        release.wait(5)
        return {"text": "too late"}

    s = session(tmp_path, whisper=stuck, timeout_s=0.2)
    s.submit_audio("controller", 0.0, wav(1.0), preview_text="CSA 123 runway 31 cleared to land")
    s.submit_audio("controller", 5.0, wav(1.0), preview_text="Lufthansa 456 runway 31 cleared for takeoff")
    events = s.wait_for(lambda ev: len([e for e in ev if e["type"] == "transcript"]) == 2, timeout=1.0)
    release.set()
    transcripts = [e for e in events if e["type"] == "transcript"]
    assert [(e["text"], e["transcriber"]) for e in transcripts] == [(LAND_31, "apple"), (TAKEOFF_31, "apple")]


def test_apple_text_is_used_when_asked_for_or_when_whisper_is_not_ready(tmp_path):
    preview = "CSA 123 runway 31 cleared to land"
    asked = session(tmp_path / "a", whisper=lambda clip: {"text": "unused"})
    asked.submit_audio("controller", 0.0, wav(1.0), preview_text=preview, prefer="apple")
    not_ready = session(tmp_path / "b", whisper=None)
    not_ready.submit_audio("controller", 0.0, wav(1.0), preview_text=preview)
    for s in (asked, not_ready):
        t = next(e for e in s.wait_for(lambda ev: any(e["type"] == "transcript" for e in ev)) if e["type"] == "transcript")
        assert (t["text"], t["transcriber"]) == (LAND_31, "apple")
    with pytest.raises(ValueError, match="unknown transcriber"):
        asked.submit_audio("controller", 0.0, wav(1.0), prefer="siri")


def test_a_clip_with_no_words_gets_an_error_and_no_extraction(tmp_path):
    s = session(tmp_path, whisper=lambda clip: {"text": "  "})
    s.submit_audio("pilot", 0.0, wav(1.0))
    s.submit_text("controller", 5.0, LAND_31)
    events = s.wait_for(lambda ev: len(extractions(ev, "rules")) == 1)
    first = next(e for e in events if e["type"] == "transcript")
    assert first["error"] == "No speech recognized" and extractions(events, "rules")[0]["seq"] == 1


def test_every_event_is_logged_to_the_session_folder(tmp_path):
    s = session(tmp_path)
    s.submit_text("controller", 0.0, LAND_31)
    s.undo()
    events = s.wait_for(lambda ev: any(e["type"] == "undone" for e in ev))
    time.sleep(0.1)
    logged = [json.loads(x) for x in (tmp_path / "s1" / "session.jsonl").read_text().splitlines()]
    assert logged == s.events_after() and {e["type"] for e in events} >= {"undone"}


def test_events_after_returns_only_newer_events_and_waits_for_them(tmp_path):
    s = session(tmp_path)
    assert s.events_after(-1, timeout=0.05) == []
    s.submit_text("controller", 0.0, LAND_31)
    first = s.events_after(-1, timeout=2)
    assert first and first[0]["id"] == 0
    assert all(e["id"] > first[-1]["id"] for e in s.events_after(first[-1]["id"], timeout=0.05))


# --- review focus (plan A) -------------------------------------------------------------------------------------------

def test_overlapping_talk_keys_still_number_and_handle_every_line_once(tmp_path):
    s = session(tmp_path)
    seqs, threads = [], [threading.Thread(target=lambda k=k: seqs.append(s.submit_text("pilot", k, LAND_31)))
                         for k in range(20)]
    for th in threads:
        th.start()
    for th in threads:
        th.join()
    assert sorted(seqs) == list(range(20))
    events = s.wait_for(lambda ev: len(extractions(ev, "claude")) == 20)
    assert [e["seq"] for e in extractions(events, "claude")] == list(range(20))


def test_a_whisper_that_raises_falls_back_to_apple_text(tmp_path):
    def broken(clip):
        raise RuntimeError("MPS backend out of memory")

    s = session(tmp_path, whisper=broken)
    s.submit_audio("controller", 0.0, wav(1.0), preview_text="CSA 123 runway 31 cleared to land")
    t = next(e for e in s.wait_for(lambda ev: any(e["type"] == "transcript" for e in ev)) if e["type"] == "transcript")
    assert (t["text"], t["transcriber"]) == (LAND_31, "apple")


def test_retry_for_a_line_the_track_has_not_reached_redoes_nothing(tmp_path):
    s = session(tmp_path)
    s.submit_text("controller", 0.0, LAND_31)
    s.wait_for(lambda ev: len(extractions(ev, "claude")) == 1)
    s.retry("claude", 5)
    s.submit_text("controller", 10.0, TAKEOFF_31)
    events = s.wait_for(lambda ev: len(extractions(ev, "claude")) == 2)
    assert [e["seq"] for e in extractions(events, "claude")] == [0, 1]


def test_undo_after_a_dropped_short_clip_undoes_the_line_before_it(tmp_path):
    s = session(tmp_path, whisper=lambda clip: {"text": "unused"})
    s.submit_text("controller", 0.0, LAND_31)
    assert s.submit_audio("pilot", 1.0, wav(0.1)) is None
    assert s.undo() == 0
