import json

from atcdb.engine import (ClearToLand, Handoff, HoldShort, LineUpAndWait, NoOp, ReadbackObserved, State, apply, fold)
from atcdb.parsing import Transmission
from atcdb.replay import Step, Timeline
from atcdb.serialize import event_dict, step_dict, timeline_dict

TX = Transmission(id=7, transcript_id=70, text="charlie runway three one cleared to land", role="controller", start_s=12.5)


def test_event_dict_has_the_same_keys_for_every_kind():
    assert event_dict(ClearToLand(callsign="csa one two three", runway="31")) == \
        {"kind": "LAND", "callsign": "csa one two three", "runway": "31", "to": None}
    assert event_dict(Handoff(callsign="a", to="ground")) == {"kind": "HANDOFF", "callsign": "a", "runway": None, "to": "ground"}
    assert event_dict(ReadbackObserved(callsign="a", text="roger")) == {"kind": "READBACK", "callsign": "a", "runway": None, "to": None}
    assert event_dict(NoOp()) == {"kind": "NOOP", "callsign": "", "runway": None, "to": None}


def test_step_dict_carries_transmission_events_conflicts_board_and_aircraft():
    state, _ = fold([LineUpAndWait(callsign="a", runway="31", text="a line up runway three one"), HoldShort(callsign="b", runway="31")])
    land = ClearToLand(callsign="c", runway="31")
    state, conflicts = apply(state, land)
    d = step_dict(3, Step(tx=TX, events=(land,), conflicts=tuple(conflicts), state=state))
    assert d["index"] == 3 and d["error"] is None and d["dropped"] == 0
    assert d["transmission"] == {"id": 7, "transcript_id": 70, "start_s": 12.5, "role": "controller", "text": TX.text}
    assert d["events"] == [{"kind": "LAND", "callsign": "c", "runway": "31", "to": None}]
    assert d["board"] == {"31": [{"callsign": "a", "kind": "LUAW"}, {"callsign": "c", "kind": "LAND"}]}
    assert d["aircraft"] == [
        {"callsign": "a", "runway": "31", "kind": "LUAW", "holding_short": None, "pending": "a line up runway three one"},
        {"callsign": "b", "runway": None, "kind": None, "holding_short": "31", "pending": None},
        {"callsign": "c", "runway": "31", "kind": "LAND", "holding_short": None, "pending": None},
    ]
    assert [(c["type"], c["severity"], c["runway"], c["callsigns"], c["seq"]) for c in d["conflicts"]] == \
        [("RUNWAY", "alert", "31", ["c", "a"], 3)]
    assert "runway 31" in d["conflicts"][0]["explanation"]
    assert d["conflicts"][0]["basis"] is None   # LAND against a held LUAW has no verified ICAO citation


def test_timeline_dict_names_every_runway_and_is_json_ready():
    land, hold = ClearToLand(callsign="a", runway="31"), HoldShort(callsign="b", runway="24")
    s1, _ = apply(State(), land)
    s2, _ = apply(s1, hold)
    tl = Timeline(recording_id=5, parser="rule", model="rules", model_version="v1", context="window", transcript_kind="gold",
                  steps=(Step(tx=TX, events=(land,), conflicts=(), state=s1),
                         Step(tx=TX, events=(), conflicts=(), state=s1, error="RuntimeError: boom"),
                         Step(tx=TX, events=(hold,), conflicts=(), state=s2)))
    rec = {"id": 5, "source": "test", "external_id": "r1", "airport_icao": None, "facility": "Tower"}
    d = timeline_dict(tl, rec, "human")
    assert {k: v for k, v in d.items() if k != "steps"} == {
        "recording": rec, "parser": "rule", "model": "rules", "model_version": "v1", "context": "window",
        "transcript_kind": "gold", "transcript_model": "human", "runways": ["24", "31"], "dropped": 0}
    assert [(s["index"], s["error"]) for s in d["steps"]] == [(0, None), (1, "RuntimeError: boom"), (2, None)]
    assert json.loads(json.dumps(d)) == d


def test_timeline_dict_for_a_recording_with_no_steps():
    tl = Timeline(recording_id=5, parser="rule", model="rules", model_version="v1", context="window", transcript_kind="asr", steps=())
    d = timeline_dict(tl, {"id": 5}, None)
    assert (d["runways"], d["steps"], d["transcript_model"]) == ([], [], None)


def test_dropped_counts_are_serialised_per_step_and_in_total():
    tl = Timeline(recording_id=5, parser="rule", model="rules", model_version="v1", context="window", transcript_kind="gold",
                  steps=(Step(tx=TX, events=(), conflicts=(), state=State(), dropped=1),
                         Step(tx=TX, events=(), conflicts=(), state=State(), dropped=2)))
    d = timeline_dict(tl, {"id": 5}, "human")
    assert [s["dropped"] for s in d["steps"]] == [1, 2] and d["dropped"] == 3
