import json
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import anthropic
import pytest

from atcdb import parse_llm
from atcdb.engine import (HANDOFF_TARGETS, ClearTakeoff, ClearToCross, ClearToLand, GoAround, Handoff, HoldShort,
                          LineUpAndWait, ReadbackObserved, RunwayVacated, Unresolved)
from atcdb.parse_llm import (EVENT_KINDS, MODELS, SYSTEM, TOOL, ParseError, estimate_cost, events_from_response, make_parser,
                             render_prompt, request, to_events)
from atcdb.parsing import Context, Transmission

ROOT = Path(__file__).resolve().parents[1]
TX = Transmission(id=1, transcript_id=10, text="csa one two three runway three one cleared to land", role="controller",
                  start_s=42.0)
ROLE = Context(mode="role", role="controller")


class FakeMessages:
    """Stands in for `client.messages`: records each call's keyword arguments and returns (or raises) the next reply."""

    def __init__(self, replies):
        self.replies, self.calls = list(replies), []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply


class FakeClient:
    def __init__(self, *replies):
        self.messages = FakeMessages(replies)


def reply(events, stop_reason="tool_use"):
    """A response shaped like the SDK's Message: one report_events tool_use block."""
    return SimpleNamespace(stop_reason=stop_reason,
                           content=[SimpleNamespace(type="tool_use", name="report_events", input={"events": events})])


def item(kind, callsign="csa one two three", runway=None, to=None):
    return {"kind": kind, "callsign": callsign, "runway": runway, "to": to}


def test_the_tool_is_strict_and_mirrors_the_engine_events():
    assert TOOL["name"] == "report_events" and TOOL["strict"] is True
    schema = TOOL["input_schema"]
    assert (schema["required"], schema["additionalProperties"]) == (["events"], False)
    ev = schema["properties"]["events"]["items"]
    assert ev["required"] == ["kind", "callsign", "runway", "to"] and ev["additionalProperties"] is False
    assert tuple(ev["properties"]["kind"]["enum"]) == EVENT_KINDS
    assert EVENT_KINDS == ("LAND", "TAKEOFF", "LUAW", "CROSS", "HOLD_SHORT", "VACATED", "GO_AROUND", "HANDOFF", "READBACK", "NOOP")
    to_choices = ev["properties"]["to"]["anyOf"]
    assert tuple(to_choices[0]["enum"]) == HANDOFF_TARGETS and to_choices[1] == {"type": "null"}


def test_render_prompt_shows_only_what_the_context_mode_allows():
    assert render_prompt(TX, Context(mode="none")) == f"Transmission: {TX.text}"
    assert render_prompt(TX, ROLE) == f"Speaker: controller\nTransmission: {TX.text}"
    window = Context(mode="window", role="controller", history=(("pilot", "csa one two three with you"),),
                     active_callsigns=("lufthansa four five six",), active_runways=("31",))
    assert render_prompt(TX, window) == (
        "Previous transmissions, oldest first:\n"
        "  [pilot] csa one two three with you\n"
        "Aircraft being tracked: lufthansa four five six\n"
        "Runways with active clearances: 31\n"
        "Speaker: controller\n"
        f"Transmission: {TX.text}")
    empty = render_prompt(TX, Context(mode="window", role="pilot"))
    assert "Aircraft being tracked: none\nRunways with active clearances: none" in empty and "Previous" not in empty


def test_request_settings_per_model():
    haiku, sonnet = request("claude-haiku-4-5", TX, ROLE), request("claude-sonnet-5", TX, ROLE)
    for r in (haiku, sonnet):
        assert r["system"] == SYSTEM and r["tools"] == [TOOL]
        assert r["tool_choice"] == {"type": "tool", "name": "report_events"}
        assert r["messages"] == [{"role": "user", "content": render_prompt(TX, ROLE)}]
        assert "temperature" not in r   # anthropic 1.x has no temperature parameter
    assert haiku["model"] == "claude-haiku-4-5" and haiku["extra_body"] == {"temperature": 0}
    assert "thinking" not in haiku and "output_config" not in haiku
    assert sonnet["model"] == "claude-sonnet-5" and "extra_body" not in sonnet   # Sonnet 5 rejects temperature
    assert (sonnet["thinking"], sonnet["output_config"]) == ({"type": "disabled"}, {"effort": "low"})
    assert MODELS == ("claude-haiku-4-5", "claude-sonnet-5", "claude-haiku-5-5")


def test_haiku_5_5_runs_like_the_sonnet_arm_without_sampling_parameters():
    # Haiku 5.5 rejects any non-default temperature, and accepts disabled thinking at low effort and a forced tool call.
    r = request("claude-haiku-5-5", TX, ROLE)
    assert r["model"] == "claude-haiku-5-5" and "extra_body" not in r and "temperature" not in r
    assert (r["thinking"], r["output_config"]) == ({"type": "disabled"}, {"effort": "low"})
    assert r["tool_choice"] == {"type": "tool", "name": "report_events"}


def test_every_kind_maps_to_its_engine_event():
    items = [item("LAND", runway="31"), item("TAKEOFF", runway="31"), item("LUAW", runway="31"),
             item("CROSS", callsign="Lufthansa  Four five six", runway="three one"),
             item("HOLD_SHORT", runway="04L"), item("HANDOFF", to="ground"), item("READBACK"), item("VACATED"),
             item("GO_AROUND"), item("NOOP", callsign="")]
    common = {"callsign": "csa one two three", "t": 42.0, "text": TX.text}
    assert to_events(items, TX) == [
        ClearToLand(runway="31", **common), ClearTakeoff(runway="31", **common), LineUpAndWait(runway="31", **common),
        ClearToCross(runway="31", callsign="lufthansa four five six", t=42.0, text=TX.text),   # callsign normalised
        HoldShort(runway="04L", **common), Handoff(to="ground", **common),
        ReadbackObserved(callsign="csa one two three", text=TX.text, t=42.0),
        RunwayVacated(**common), GoAround(**common)]                                         # NOOP adds nothing


def test_events_that_cannot_be_placed_become_unresolved():
    bad = [item("LAND", runway="three seven"), item("TAKEOFF"), item("HANDOFF")]
    out = to_events(bad, TX)
    assert [type(e) for e in out] == [Unresolved] * 3
    assert [json.loads(e.raw) for e in out] == bad
    assert (out[0].callsign, out[0].t, out[0].text) == ("csa one two three", 42.0, TX.text)


def test_the_parser_sends_one_request_and_maps_the_reply():
    client = FakeClient(reply([item("LAND", runway="31")]))
    parse = make_parser("claude-sonnet-5", client)
    assert parse(TX, ROLE) == [ClearToLand(callsign="csa one two three", runway="31", t=42.0, text=TX.text)]
    assert client.messages.calls == [request("claude-sonnet-5", TX, ROLE)]
    assert make_parser("claude-haiku-4-5", FakeClient(reply([])))(TX, ROLE) == []   # get_events stores the NOOP row


@pytest.mark.parametrize("response,message", [
    (SimpleNamespace(stop_reason="refusal", content=[]), "refused"),
    (reply([item("LAND", runway="31")], stop_reason="max_tokens"), "max_tokens"),
    (SimpleNamespace(stop_reason="end_turn", content=[SimpleNamespace(type="text", text="no events")]), "no report_events"),
])
def test_unusable_replies_raise_parse_error(response, message):
    with pytest.raises(ParseError, match=message):
        make_parser("claude-haiku-4-5", FakeClient(response))(TX, ROLE)


def test_an_api_error_propagates_unchanged():
    boom = RuntimeError("529 overloaded")
    with pytest.raises(RuntimeError) as raised:
        make_parser("claude-haiku-4-5", FakeClient(boom))(TX, ROLE)
    assert raised.value is boom


def test_make_parser_rejects_an_unknown_model():
    with pytest.raises(ValueError, match="unknown Claude model"):
        make_parser("claude-opus-5")


def test_default_client_sets_a_timeout_so_a_hung_call_cannot_stall_a_replay(monkeypatch):
    calls = []
    monkeypatch.setattr(anthropic, "Anthropic", lambda **kw: calls.append(kw))
    parse_llm._default_client.cache_clear()
    try:
        parse_llm._default_client()
    finally:
        parse_llm._default_client.cache_clear()   # do not leak the fake client into later tests
    assert calls == [{"timeout": 60.0}]


def test_availability_reports_why_a_cold_parse_cannot_run(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    assert parse_llm.availability() == (True, None)
    monkeypatch.delenv("ANTHROPIC_API_KEY")
    assert parse_llm.availability() == (False, "ANTHROPIC_API_KEY not set")
    monkeypatch.setitem(sys.modules, "anthropic", None)   # makes `import anthropic` raise ImportError
    assert parse_llm.availability() == (False, "anthropic not installed")


def test_importing_the_parser_does_not_import_the_sdk():
    code = "import sys, atcdb.parse_llm; print('anthropic' in sys.modules)"
    out = subprocess.run([sys.executable, "-c", code], cwd=ROOT, capture_output=True, text=True, check=True)
    assert out.stdout.strip() == "False"


def test_estimate_cost_scales_with_the_calls_and_the_price():
    assert estimate_cost("claude-haiku-4-5", []) == 0
    one = estimate_cost("claude-haiku-4-5", ["x" * 400])
    assert 0 < one < 0.01
    assert estimate_cost("claude-haiku-4-5", ["x" * 400] * 10) == pytest.approx(10 * one)
    assert estimate_cost("claude-sonnet-5", ["x" * 400]) == pytest.approx(2 * one)   # both prices are double Haiku's
    # a tenth of Haiku 4.5's prices, but its newer tokenizer counts the same text as about 30% more tokens
    assert estimate_cost("claude-haiku-5-5", ["x" * 400]) == pytest.approx(0.13 * one)


# --- recorded replies (scripts/record_llm_fixtures.py) -----------------------------------------

FIXTURE = ROOT / "tests" / "fixtures" / "llm_responses.json"

# (case, model) -> what the recorded reply maps to: (event type, callsign, runway or handoff target).
# Models whose replies are recorded (claude-haiku-5-5: operational step O2 of the live demo helper plan, 2026-10-20).
RECORDED_MODELS = ("claude-haiku-4-5", "claude-sonnet-5", "claude-haiku-5-5")
RECORDED = {
    **{("austin_landing_clearance", m): [("ClearToLand", "fedex fourteen thirty-two heavy", "18L")] for m in RECORDED_MODELS},
    **{("austin_takeoff_clearance", m): [("ClearTakeoff", "southwest seven zero eight", "18L")] for m in RECORDED_MODELS},
    # Findings, not expectations to fix here: Haiku reads the pilot's readback as a new clearance for the heading,
    # Sonnet sees a readback but misses the callsign said at the end, and Haiku 5.5 sees a readback but takes the heading
    # for the callsign.
    ("austin_takeoff_readback", "claude-haiku-4-5"): [("ClearTakeoff", "one seven zero", "18L")],
    ("austin_takeoff_readback", "claude-sonnet-5"): [("ReadbackObserved", "", None)],
    ("austin_takeoff_readback", "claude-haiku-5-5"): [("ReadbackObserved", "one seven zero", None)],
    **{("austin_handoff", m): [("Handoff", "american nineteen thirteen", "departure")] for m in RECORDED_MODELS},
    **{("cross_then_hold_short", m): [("ClearToCross", "lufthansa four five six", "24"),
                                      ("HoldShort", "lufthansa four five six", "31")] for m in RECORDED_MODELS},
    **{("window_snaps_to_the_active_runway", m): [("ClearToLand", "csa one two three", "31")] for m in RECORDED_MODELS},
}


def _recorded():
    """Each recorded reply as (case, model, transmission, context, response), the response shaped like the SDK's Message."""
    for r in json.loads(FIXTURE.read_text()):
        c = r["context"]
        ctx = Context(mode=c["mode"], role=c["role"], history=tuple(tuple(h) for h in c["history"]),
                      active_callsigns=tuple(c["active_callsigns"]), active_runways=tuple(c["active_runways"]))
        tx = Transmission(id=0, transcript_id=0, text=r["text"], role=r["role"], start_s=0.0)
        response = SimpleNamespace(stop_reason=r["stop_reason"], content=[SimpleNamespace(**b) for b in r["content"]])
        yield r["case"], r["model"], tx, ctx, response


def test_recorded_replies_map_to_the_pinned_events():
    seen = set()
    for case, model, tx, ctx, response in _recorded():
        got = [(type(e).__name__, e.callsign, getattr(e, "runway", None) or getattr(e, "to", None))
               for e in events_from_response(response, tx)]
        assert got == RECORDED[(case, model)], (case, model)
        seen.add((case, model))
    assert seen == set(RECORDED)


def test_the_recorded_replies_are_for_this_parser_version():
    # A change to the prompt, the tool or the request bumps VERSION; then re-run scripts/record_llm_fixtures.py.
    assert {r["version"] for r in json.loads(FIXTURE.read_text())} == {parse_llm.VERSION}


@pytest.mark.skipif(not os.environ.get("ANTHROPIC_API_KEY"), reason="ANTHROPIC_API_KEY not set: live smoke test skipped")
def test_live_smoke_haiku_parses_a_landing_clearance():
    events = make_parser("claude-haiku-4-5")(TX, ROLE)
    assert [(type(e).__name__, e.callsign, e.runway) for e in events] == [("ClearToLand", "csa one two three", "31")]
