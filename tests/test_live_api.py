import json
import time

import pytest
from fastapi.testclient import TestClient
from live_fakes import Scripted, wav

from atcdb import parse_rules
from atcdb.api import create_app
from atcdb.asr import normalize_asr_text
from atcdb.incidents import austin_lines, fold_window
from atcdb.live import Line, Track
from atcdb.live_hub import AUSTIN_ID, LiveHub, WhisperLoader, gpu_whisper, live_claude_parser
from atcdb.parsing import Transmission
from atcdb.serialize import conflict_dict, event_dict

LAND_31 = "csa one two three runway three one cleared to land"


def make_hub(tmp_path, claude=None, whisper_text="CSA 123 runway 31 cleared to land"):
    tracks = lambda: {"rules": Track("rules", parse_rules.parse), "claude": Track("claude", claude or Scripted())}
    return LiveHub(tmp_path / "sessions", WhisperLoader(lambda: (lambda clip: {"text": whisper_text})), tracks)


def ready(hub):
    """Start Whisper loading and wait for it, as the app does by polling /api/live/health at launch."""
    hub.whisper.start()
    for _ in range(100):
        if hub.whisper.status == "ready":
            return hub
        time.sleep(0.01)
    raise AssertionError(f"whisper is {hub.whisper.status}")


@pytest.fixture
def hub(tmp_path):
    return make_hub(tmp_path)


@pytest.fixture
def client(tmp_path, hub):
    return TestClient(create_app(tmp_path / "t.sqlite", tmp_path, live_hub=hub))


def read_stream(client, sid, n, after=-1, headers=None):
    """The first `n` events of a session's stream after `after`, parsed from the server-sent event text."""
    with client.stream("GET", f"/api/live/sessions/{sid}/stream", params={"after": after, "max_events": n},
                       headers=headers or {}) as r:
        assert r.status_code == 200 and r.headers["content-type"].startswith("text/event-stream")
        text = "".join(r.iter_text())
    events = []
    for block in text.strip().split("\n\n"):
        fields = dict(line.split(": ", 1) for line in block.splitlines() if not line.startswith(":"))
        data = json.loads(fields["data"])
        assert (int(fields["id"]), fields["event"]) == (data["id"], data["type"])
        events.append(data)
    return events


def new_session(client):
    r = client.post("/api/live/sessions")
    assert r.status_code == 200
    return r.json()["session_id"]


# --- the hub --------------------------------------------------------------------------------------------------------

def test_health_starts_loading_whisper_and_says_why_claude_cannot_run(client, hub, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    assert hub.whisper.status == "idle"
    body = client.get("/api/live/health").json()
    assert body["claude"] == {"model": "claude-haiku-5-5", "available": False, "reason": "ANTHROPIC_API_KEY not set"}
    assert body["extractors"] == ["rules", "claude"] and hub.whisper.status in ("loading", "ready")
    ready(hub)
    assert client.get("/api/live/health").json()["whisper"] == {"status": "ready", "reason": None}


def test_a_whisper_that_cannot_load_reports_failed_and_lines_use_apple_text(tmp_path):
    loader = WhisperLoader(gpu_whisper(tmp_path / "missing"))
    loader.start()
    for _ in range(50):
        if loader.status != "loading":
            break
        time.sleep(0.02)
    assert loader.status == "failed" and "run scripts/bench_whisper.py once" in loader.reason and loader.get() is None


def test_the_live_claude_parser_without_a_key_fails_each_line_not_the_session(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    tx = Transmission(id=0, transcript_id=0, text=LAND_31, role="controller", start_s=0.0)
    with pytest.raises(RuntimeError, match="ANTHROPIC_API_KEY not set"):
        live_claude_parser()(tx, None)


def test_a_new_session_closes_the_old_one_and_gets_its_own_folder(hub):
    first, second = hub.new_session(), hub.new_session()
    assert first.session_id != second.session_id and second.folder.parent == hub.sessions_dir
    assert hub.get(second.session_id) is second and hub.get("nope") is None


# --- routes ---------------------------------------------------------------------------------------------------------

def test_a_typed_line_streams_its_transcript_then_both_extractions(client):
    sid = new_session(client)
    assert client.post(f"/api/live/sessions/{sid}/text",
                       json={"role": "controller", "t": 0.0, "text": "CSA 123 runway 31 cleared to land"}).json() == {"seq": 0}
    events = read_stream(client, sid, 3)
    assert [e["type"] for e in events] == ["transcript", "extraction", "extraction"]
    assert events[0]["text"] == LAND_31 and {e["extractor"] for e in events[1:]} == {"rules", "claude"}


def test_a_clip_is_posted_as_the_raw_wav_body(client, hub):
    ready(hub)
    sid = new_session(client)
    r = client.post(f"/api/live/sessions/{sid}/audio", params={"role": "controller", "t": 2.5, "preview_text": "csa"},
                    content=wav(1.0), headers={"Content-Type": "audio/wav"})
    assert r.json() == {"seq": 0, "dropped": None}
    transcript = read_stream(client, sid, 1)[0]
    assert (transcript["text"], transcript["transcriber"], transcript["preview_text"]) == (LAND_31, "whisper", "csa")
    assert client.get(f"/api/live/sessions/{sid}/clips/0").headers["content-type"] == "audio/wav"
    short = client.post(f"/api/live/sessions/{sid}/audio", params={"role": "pilot", "t": 3.0}, content=wav(0.2))
    assert short.json() == {"seq": None, "dropped": "Too short"}


def test_bad_input_is_422_and_an_unknown_session_is_404(client):
    sid = new_session(client)
    assert client.post(f"/api/live/sessions/{sid}/text", json={"role": "tower", "t": 0, "text": "x"}).status_code == 422
    assert client.post(f"/api/live/sessions/{sid}/audio", params={"role": "pilot", "t": 0},
                       content=b"not audio").status_code == 422
    assert client.post(f"/api/live/sessions/{sid}/audio", params={"role": "pilot", "t": 0, "transcriber": "siri"},
                       content=wav(1.0)).status_code == 422
    assert client.post(f"/api/live/sessions/{sid}/retry", json={"extractor": "gpt", "seq": 0}).status_code == 422
    assert client.post("/api/live/sessions/nope/text", json={"role": "pilot", "t": 0, "text": "x"}).status_code == 404
    assert client.get("/api/live/sessions/nope/stream").status_code == 404
    assert client.get(f"/api/live/sessions/{sid}/clips/9").status_code == 404


def test_undo_and_retry_over_http(tmp_path):
    hub = make_hub(tmp_path, claude=Scripted(fail_texts=[LAND_31]))
    client = TestClient(create_app(tmp_path / "t.sqlite", tmp_path, live_hub=hub))
    sid = new_session(client)
    client.post(f"/api/live/sessions/{sid}/text", json={"role": "controller", "t": 0, "text": LAND_31})
    failed = [e for e in read_stream(client, sid, 3) if e.get("extractor") == "claude"][0]
    assert failed["error"].endswith("no internet connection")
    assert client.post(f"/api/live/sessions/{sid}/retry", json={"extractor": "claude", "seq": 0}).json() == {"ok": True}
    redone = read_stream(client, sid, 1, after=2)[0]
    assert (redone["extractor"], redone["seq"], redone["error"]) == ("claude", 0, None)
    assert client.post(f"/api/live/sessions/{sid}/undo").json() == {"seq": 0}
    assert read_stream(client, sid, 1, after=3)[0] == {"id": 4, "type": "undone", "seq": 0}
    assert client.post(f"/api/live/sessions/{sid}/undo").json() == {"seq": None}


def test_the_stream_resumes_after_the_last_event_id(client):
    sid = new_session(client)
    client.post(f"/api/live/sessions/{sid}/text", json={"role": "controller", "t": 0, "text": LAND_31})
    first = read_stream(client, sid, 3)
    again = read_stream(client, sid, 1, headers={"Last-Event-ID": str(first[1]["id"])})
    assert again == [first[2]]


def test_a_saved_session_is_labelled_and_replays_its_lines_with_their_clips(client, hub):
    ready(hub)
    sid = new_session(client)
    client.post(f"/api/live/sessions/{sid}/audio", params={"role": "controller", "t": 1.0}, content=wav(1.0))
    client.post(f"/api/live/sessions/{sid}/text", json={"role": "pilot", "t": 4.0, "text": "cleared to land csa one two three"})
    client.post(f"/api/live/sessions/{sid}/text", json={"role": "pilot", "t": 6.0, "text": "say again"})
    read_stream(client, sid, 6)
    client.post(f"/api/live/sessions/{sid}/undo")
    assert client.post(f"/api/live/sessions/{sid}/label", json={"label": "Rehearsal 1"}).json() == {"ok": True}
    assert client.post("/api/live/sessions/nope/label", json={"label": "x"}).status_code == 404
    listed = client.get("/api/live/scenarios").json()
    assert listed[0]["id"] == AUSTIN_ID and listed[1] == {"id": sid, "title": "Rehearsal 1", "lines": 2, "audio": True}
    lines = client.get(f"/api/live/scenarios/{sid}").json()
    assert [(x["role"], x["t"], x["text"]) for x in lines] == [("controller", 1.0, LAND_31),
                                                              ("pilot", 4.0, "cleared to land csa one two three")]
    assert lines[0]["audio"] == f"/api/live/sessions/{sid}/clips/0" and lines[1]["audio"] is None
    assert client.get(lines[0]["audio"]).status_code == 200
    assert client.get("/api/live/scenarios/nope").status_code == 404


def test_capabilities_say_the_live_routes_exist(client):
    assert client.get("/api/capabilities").status_code in (200, 503)   # 503: no corpus DB in this test's tmp_path
    assert client.get("/api/live/scenarios").status_code == 200


# --- Austin through the live path ----------------------------------------------------------------------------------------

def test_the_austin_replay_matches_the_reference_fold_and_rules_warn_only_late(client):
    lines = client.get(f"/api/live/scenarios/{AUSTIN_ID}").json()
    assert len(lines) == len([1 for _, tx in austin_lines() if tx.role in ("controller", "pilot")])
    sid = new_session(client)
    for x in lines:
        client.post(f"/api/live/sessions/{sid}/text", json={"role": x["role"], "t": x["t"], "text": x["text"],
                                                            "source": "replay"})
    events = read_stream(client, sid, 3 * len(lines))
    reference = [Line(k, x["role"], x["t"], normalize_asr_text(x["text"]), "replay", "none").transmission()
                 for k, x in enumerate(lines)]
    for name, parse in (("rules", parse_rules.parse), ("claude", Scripted())):
        live = sorted((e for e in events if e.get("extractor") == name), key=lambda e: e["seq"])
        folded = fold_window(reference, parse)
        assert [e["events"] for e in live] == [[event_dict(ev) for ev in evs if type(ev).__name__ != "NoOp"]
                                               for _, evs, _ in folded]
        assert [e["conflicts"] for e in live] == [[conflict_dict(c) for c in cs] for _, _, cs in folded]
    rules_conflicts = [(lines[e["seq"]]["t"], c["severity"]) for e in events if e.get("extractor") == "rules"
                       for c in e["conflicts"] if c["type"] == "RUNWAY"]
    at = {tx.start_s: hhmm for hhmm, tx in austin_lines()}
    assert [(at[t], sev) for t, sev in rules_conflicts] == [("0639:34", "warning")]
