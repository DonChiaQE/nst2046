import numpy as np
import pytest
import soundfile as sf
from fastapi.testclient import TestClient

from atcdb.api import create_app
from atcdb.parse_rules import VERSION
from atcdb.schema import init_db

TURNS = [
    ("controller", "csa one two three runway three one cleared to land wind calm"),
    ("pilot", "cleared to land runway three one csa one two three"),
    ("controller", "lufthansa four five six cross runway three one"),   # CROSS while csa holds a LAND -> alert
    ("pilot", "crossing runway three one lufthansa four five six"),
]


def _transcript(conn, transmission_id, kind, model, text):
    conn.execute("INSERT INTO transcripts (transmission_id, kind, model, raw_text, normalized_text) VALUES (?, ?, ?, ?, ?)",
                 (transmission_id, kind, model, text, text))


@pytest.fixture
def client(tmp_path):
    """Recording 10 (four tower transmissions, one real clip) and recording 11 (no transmissions)."""
    root = tmp_path / "proj"
    (root / "clips").mkdir(parents=True)
    sf.write(root / "clips" / "x0.wav", np.zeros(800, dtype="float32"), 8000, subtype="PCM_16")
    conn = init_db(tmp_path / "t.sqlite")
    conn.execute("INSERT INTO sources (id, name, kind) VALUES (1, 'test', 'corpus')")
    conn.execute("INSERT INTO recordings (id, source_id, external_id, airport_icao, facility) VALUES (10, 1, 'rec-a', 'LKPR', 'Tower')")
    conn.execute("INSERT INTO recordings (id, source_id, external_id, facility) VALUES (11, 1, 'rec-empty', 'Tower')")
    for i, (role, text) in enumerate(TURNS):
        conn.execute("INSERT INTO transmissions (id, recording_id, external_id, start_s, speaker_role, clip_path) VALUES (?, 10, ?, ?, ?, ?)",
                     (100 + i, f"x{i}", 10.0 * i, role, f"clips/x{i}.wav"))   # only clips/x0.wav exists on disk
        if i == 2:   # a second gold transcript with a LOWER id: an unpinned replay would pick it
            _transcript(conn, 102, "gold", "atco2-xml", "lufthansa four five six hold short of runway three one")
        _transcript(conn, 100 + i, "gold", "human", text)
    _transcript(conn, 100, "asr", "whisper-test", "csa one two three runway one three cleared to land")
    conn.commit()
    conn.close()
    return TestClient(create_app(tmp_path / "t.sqlite", root))


def test_capabilities(client):
    assert client.get("/api/capabilities").json() == {
        "parsers": [{"name": "rule", "model": "rules", "model_version": VERSION}],
        "contexts": ["none", "role", "window"],
        "transcripts": {"gold": ["atco2-xml", "human"], "asr": ["whisper-test"]},
        "live": False,
    }


def test_recordings_lists_replayable_recordings_and_validates_the_kind(client):
    r = client.get("/api/recordings")
    assert r.status_code == 200
    assert r.json() == [{"id": 10, "source": "test", "external_id": "rec-a", "airport_icao": "LKPR", "facility": "Tower",
                         "n_transmissions": 4, "n_runway_mentions": 4}]
    assert client.get("/api/recordings", params={"min_transmissions": 5}).json() == []
    assert client.get("/api/recordings", params={"transcript": "llm"}).status_code == 422
    assert client.get("/api/recordings", params={"min_transmissions": 0}).status_code == 422


def test_replay_folds_the_recording_and_pins_the_human_gold_transcripts(client):
    r = client.get("/api/recordings/10/replay")
    assert r.status_code == 200
    d = r.json()
    assert (d["parser"], d["model"], d["context"], d["transcript_kind"], d["transcript_model"]) == \
        ("rule", "rules", "window", "gold", "human")
    assert d["recording"] == {"id": 10, "source": "test", "external_id": "rec-a", "airport_icao": "LKPR", "facility": "Tower"}
    assert d["runways"] == ["31"] and len(d["steps"]) == 4
    assert d["steps"][0]["board"] == {"31": [{"callsign": "csa one two three", "kind": "LAND"}]}
    assert [e["kind"] for e in d["steps"][2]["events"]] == ["CROSS"]
    assert [(c["type"], c["severity"], c["callsigns"]) for c in d["steps"][2]["conflicts"]] == \
        [("RUNWAY", "alert", ["lufthansa four five six", "csa one two three"])]
    assert sum(len(s["conflicts"]) for s in d["steps"]) == 1
    assert client.get("/api/recordings/10/replay").json() == d   # second request is served from the events cache


def test_replay_with_an_explicit_transcript_model_or_asr(client):
    d = client.get("/api/recordings/10/replay", params={"transcript_model": "atco2-xml"}).json()
    assert d["transcript_model"] == "atco2-xml"
    assert [[e["kind"] for e in s["events"]] for s in d["steps"]] == [["HOLD_SHORT"]]
    d = client.get("/api/recordings/10/replay", params={"transcript": "asr", "context": "role"}).json()
    assert (d["transcript_model"], d["context"]) == ("whisper-test", "role")
    assert [(e["kind"], e["runway"]) for s in d["steps"] for e in s["events"]] == [("LAND", "13")]


def test_replay_errors(client):
    assert client.get("/api/recordings/999/replay").status_code == 404
    empty = client.get("/api/recordings/11/replay")
    assert empty.status_code == 200 and (empty.json()["steps"], empty.json()["runways"]) == ([], [])
    for params in ({"parser": "magic"}, {"context": "everything"}, {"transcript": "llm"}):
        r = client.get("/api/recordings/10/replay", params=params)
        assert r.status_code == 422 and "unknown" in r.json()["detail"]
    assert client.get("/api/recordings/abc/replay").status_code == 422


def test_clip_streams_the_wav_or_404s(client):
    r = client.get("/api/clips/100")
    assert r.status_code == 200 and r.headers["content-type"] == "audio/wav" and r.content[:4] == b"RIFF"
    assert client.get("/api/clips/101").status_code == 404   # clip_path set, file missing
    assert client.get("/api/clips/999").status_code == 404   # unknown transmission


def test_clip_path_outside_the_project_root_is_refused(client, tmp_path):
    outside = tmp_path / "outside.wav"
    sf.write(outside, np.zeros(80, dtype="float32"), 8000, subtype="PCM_16")
    conn = init_db(tmp_path / "t.sqlite")
    conn.execute("UPDATE transmissions SET clip_path = ? WHERE id = 101", ("../outside.wav",))
    conn.commit()
    conn.close()
    assert client.get("/api/clips/101").status_code == 404


def test_front_end_page_is_served_at_the_root(client):
    r = client.get("/")
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/html")
    assert 'id="board"' in r.text and 'id="feed"' in r.text and 'src="app.js"' in r.text


def test_clip_under_a_symlinked_data_directory_is_served(tmp_path):
    real = tmp_path / "elsewhere" / "clips"
    real.mkdir(parents=True)
    sf.write(real / "a.wav", np.zeros(80, dtype="float32"), 8000, subtype="PCM_16")
    root = tmp_path / "proj"
    (root / "data").mkdir(parents=True)
    (root / "data" / "clips").symlink_to(real)
    conn = init_db(tmp_path / "s.sqlite")
    conn.execute("INSERT INTO sources (id, name, kind) VALUES (1, 'test', 'corpus')")
    conn.execute("INSERT INTO recordings (id, source_id, external_id) VALUES (1, 1, 'r')")
    conn.execute("INSERT INTO transmissions (id, recording_id, external_id, clip_path) VALUES (1, 1, 'x', 'data/clips/a.wav')")
    conn.commit()
    conn.close()
    assert TestClient(create_app(tmp_path / "s.sqlite", root)).get("/api/clips/1").status_code == 200
