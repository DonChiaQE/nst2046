import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from atcdb import judge, parse_llm
from atcdb.evaluate import JUDGE_ARMS, Arm, detection, recording_row, uncached, usable
from atcdb.judge import (MODELS, SYSTEM, TOOL, JudgeError, conflicts_from_response, estimate_cost, is_cached, render_sequence,
                         request)
from atcdb.parse_llm import MODEL_SETTINGS
from atcdb.parsing import Transmission
from atcdb.schema import init_db

ROOT = Path(__file__).resolve().parents[1]
TURNS = [("controller", "csa one two three runway three one cleared to land wind calm"),
         ("pilot", "cleared to land runway three one csa one two three"),
         ("controller", "lufthansa four five six cross runway three one")]
TXS = [Transmission(id=i + 1, transcript_id=i + 1, text=t, role=r, start_s=10.0 * i) for i, (r, t) in enumerate(TURNS)]


class FakeMessages:
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


def reply(conflicts, stop_reason="tool_use"):
    return SimpleNamespace(stop_reason=stop_reason,
                           content=[SimpleNamespace(type="tool_use", name="report_conflicts", input={"conflicts": conflicts})])


def item(runway="31", index=3, type_="RUNWAY", callsigns=("lufthansa four five six",)):
    return {"type": type_, "runway": runway, "callsigns": list(callsigns), "trigger_index": index}


def _seed(conn, turns=TURNS, external_id="r1"):
    conn.execute("INSERT OR IGNORE INTO sources (id, name, kind) VALUES (1, 'test', 'corpus')")
    rid = conn.execute("INSERT INTO recordings (source_id, external_id, facility) VALUES (1, ?, 'Tower')", (external_id,)).lastrowid
    for i, (role, text) in enumerate(turns):
        xid = conn.execute("INSERT INTO transmissions (recording_id, external_id, start_s, end_s, speaker_role) VALUES (?, ?, ?, ?, ?)",
                           (rid, f"x{i}", 10.0 * i, 10.0 * i + 3, role)).lastrowid
        conn.execute("INSERT INTO transcripts (transmission_id, kind, model, raw_text, normalized_text) VALUES (?, 'gold', 'human', ?, ?)",
                     (xid, text, text))
    conn.commit()
    return rid


def test_the_tool_is_strict_and_each_request_matches_the_parser_arm_of_its_model():
    assert TOOL["name"] == "report_conflicts" and TOOL["strict"] is True
    item_schema = TOOL["input_schema"]["properties"]["conflicts"]["items"]
    assert item_schema["required"] == ["type", "runway", "callsigns", "trigger_index"]
    assert item_schema["additionalProperties"] is False and item_schema["properties"]["type"]["enum"] == ["RUNWAY", "READBACK"]
    assert MODELS == ("claude-sonnet-5", "claude-haiku-5-5")
    for model in MODELS:
        r = request(model, TXS)
        assert r["system"] == SYSTEM and r["tools"] == [TOOL] and r["tool_choice"] == {"type": "tool", "name": "report_conflicts"}
        assert (r["thinking"], r["output_config"]) == (MODEL_SETTINGS[model]["thinking"], {"effort": "low"})


def test_render_sequence_numbers_every_transmission_from_one():
    assert render_sequence(TXS) == (
        "Transmissions, in order:\n"
        f"[1] (controller) {TURNS[0][1]}\n[2] (pilot) {TURNS[1][1]}\n[3] (controller) {TURNS[2][1]}")


def test_conflicts_map_to_zero_based_steps_and_bad_ones_are_dropped():
    found, dropped = conflicts_from_response(reply([
        item(), item(runway="4 Left", index=1, type_="READBACK", callsigns=["CSA  One"]),
        item(runway="99"), item(index=0), item(index=4)]), n=3)
    assert found == [{"type": "RUNWAY", "runway": "31", "step": 2, "callsigns": ["lufthansa four five six"]},
                     {"type": "READBACK", "runway": "04L", "step": 0, "callsigns": ["csa one"]}]
    assert dropped == 3


@pytest.mark.parametrize("response, message", [
    (reply([], stop_reason="refusal"), "refused"),
    (reply([], stop_reason="max_tokens"), "truncated"),
    (SimpleNamespace(stop_reason="end_turn", content=[SimpleNamespace(type="text", text="none")]), "no report_conflicts"),
])
def test_unusable_replies_raise(response, message):
    with pytest.raises(JudgeError, match=message):
        conflicts_from_response(response, 3)


def test_judgments_are_cached_and_failures_are_not(tmp_path):
    conn = init_db(tmp_path / "t.sqlite")
    rid = _seed(conn)
    client = FakeClient(RuntimeError("overloaded"), reply([item()]))
    with pytest.raises(RuntimeError):
        judge.judge(conn, rid, TXS, "gold", "human", client=client)
    assert not is_cached(conn, rid, "gold", "human")
    first = judge.judge(conn, rid, TXS, "gold", "human", client=client)
    assert first == ([{"type": "RUNWAY", "runway": "31", "step": 2, "callsigns": ["lufthansa four five six"]}], 0)
    assert judge.judge(conn, rid, TXS, "gold", "human", client=FakeClient()) == first   # no second call
    assert len(client.messages.calls) == 2 and is_cached(conn, rid, "gold", "human")
    assert judge.judge(conn, rid, [], "gold", "human", client=FakeClient()) == ([], 0)
    with pytest.raises(ValueError):
        judge.judge(conn, rid, TXS, "gold", "human", model="claude-haiku-4-5")


def test_a_judgment_of_another_sequence_is_judged_again(tmp_path):
    conn = init_db(tmp_path / "t.sqlite")
    rid = _seed(conn)
    judge.judge(conn, rid, TXS[:2], "gold", "human", client=FakeClient(reply([])))   # e.g. before the ASR run finished
    assert is_cached(conn, rid, "gold", "human", txs=TXS[:2]) and not is_cached(conn, rid, "gold", "human", txs=TXS)
    client = FakeClient(reply([item()]))
    found, dropped = judge.judge(conn, rid, TXS, "gold", "human", client=client)
    assert len(client.messages.calls) == 1 and [c["step"] for c in found] == [2] and dropped == 0
    assert conn.execute("SELECT COUNT(*) FROM judgments").fetchone()[0] == 1
    assert judge.judge(conn, rid, TXS, "gold", "human", client=FakeClient()) == (found, 0)


def test_a_partial_asr_recording_is_not_replayed_judged_or_counted(tmp_path, monkeypatch):
    conn = init_db(tmp_path / "t.sqlite")
    rid = _seed(conn)
    conn.execute("""INSERT INTO transcripts (transmission_id, kind, model, raw_text, normalized_text)
                    VALUES (1, 'asr', 'whisper', ?, ?)""", (TURNS[0][1], TURNS[0][1]))   # an ASR run that has not finished
    conn.commit()
    client = FakeClient()   # no replies: any call fails the test
    monkeypatch.setattr(judge, "_default_client", lambda: client)
    monkeypatch.setattr(parse_llm, "_default_client", lambda: client)
    for arm in (JUDGE_ARMS[1], Arm("llm", "claude-sonnet-5", "window", "asr")):
        assert arm.transcript == "asr"
        row = recording_row(conn, arm, rid, "negatives", None)
        assert row["missing_transcripts"] == 2 and row["incomplete"] is False and not usable(row)
        assert row["conflicts"] == [] and all(e == [] for e in row["events"])
        assert uncached(conn, arm, [rid]) == (0, 0.0)
    assert client.messages.calls == []
    assert conn.execute("SELECT (SELECT COUNT(*) FROM judgments) + (SELECT COUNT(*) FROM events)").fetchone()[0] == 0


def test_the_judge_arm_row_places_conflicts_at_their_trigger(tmp_path, monkeypatch):
    conn = init_db(tmp_path / "t.sqlite")
    rid = _seed(conn)
    arm = JUDGE_ARMS[0]
    assert (arm.parser, arm.model, arm.context, arm.transcript) == ("judge", "claude-sonnet-5", "sequence", "gold")
    assert uncached(conn, arm, [rid])[0] == 1
    monkeypatch.setattr(judge, "_default_client", lambda: FakeClient(reply([item()])))
    row = recording_row(conn, arm, rid, "positives", {"runway": "31", "anchor_tx": 1, "trigger_tx": 3, "edit_kind": "splice"})
    assert row["incomplete"] is False and row["tx_ids"] == [1, 2, 3] and row["events"] == [[], [], []]
    assert row["conflicts"] == [{"type": "RUNWAY", "severity": "alert", "runway": "31",
                                 "callsigns": ["lufthansa four five six"], "tx_id": 3, "step": 2}]
    assert detection(row) == "strict" and uncached(conn, arm, [rid]) == (0, 0.0)
    monkeypatch.setattr(judge, "_default_client", lambda: FakeClient(RuntimeError("down")))
    failed = recording_row(conn, arm, _seed(conn, external_id="r2"), "negatives", None)
    assert failed["incomplete"] is True and failed["conflicts"] == []


def test_estimate_cost_scales_with_the_sequences():
    one = estimate_cost("claude-sonnet-5", ["x" * 2000])
    assert 0 < one < 0.02 and estimate_cost("claude-sonnet-5", ["x" * 2000] * 3) == pytest.approx(3 * one)
    # a twentieth of Sonnet's prices, but its newer tokenizer counts the same text as about 30% more tokens
    assert estimate_cost("claude-haiku-5-5", ["x" * 2000]) == pytest.approx(0.065 * one)


# --- recorded replies (scripts/record_judge_fixtures.py) -----------------------------------------

FIXTURE = ROOT / "tests" / "fixtures" / "judge_responses.json"
RECORDED = {
    ("crossing_against_a_landing", "claude-sonnet-5"): [("RUNWAY", "31", 2)],
    ("released_before_the_takeoff", "claude-sonnet-5"): [],
    ("crossing_against_a_landing", "claude-haiku-5-5"): [("RUNWAY", "31", 2)],
    ("released_before_the_takeoff", "claude-haiku-5-5"): [],
}


def test_recorded_replies_map_to_the_pinned_conflicts():
    seen = set()
    for r in json.loads(FIXTURE.read_text()):
        response = SimpleNamespace(stop_reason=r["stop_reason"], content=[SimpleNamespace(**b) for b in r["content"]])
        found, dropped = conflicts_from_response(response, len(r["turns"]))
        assert [(c["type"], c["runway"], c["step"]) for c in found] == RECORDED[(r["case"], r["model"])] and dropped == 0
        seen.add((r["case"], r["model"]))
    assert seen == set(RECORDED)
    assert {r["version"] for r in json.loads(FIXTURE.read_text())} == {judge.VERSION}


@pytest.mark.skipif(not os.environ.get("ANTHROPIC_API_KEY"), reason="ANTHROPIC_API_KEY not set: live smoke test skipped")
def test_live_smoke_the_judge_finds_a_crossing_against_a_landing(tmp_path):
    conn = init_db(tmp_path / "t.sqlite")
    found, _ = judge.judge(conn, _seed(conn), TXS, "gold", "human")
    assert [(c["type"], c["runway"], c["step"]) for c in found] == [("RUNWAY", "31", 2)]
