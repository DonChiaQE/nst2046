import pytest

from atcdb.engine import ClearToLand, NoOp, State, fold
from atcdb.parsing import Context
from atcdb.replay import (PARSER_MODELS, PARSERS, Step, Timeline, build_context, build_timeline, get_events,
                          list_recordings, load_recording)
from atcdb.schema import init_db


def _seed(conn, turns, external_id="r1", facility="Tower"):
    """One recording with `turns` = [(role, text), ...] at 10 s spacing, gold transcripts by 'human'. Returns its id."""
    conn.execute("INSERT OR IGNORE INTO sources (id, name, kind) VALUES (1, 'test', 'corpus')")
    rid = conn.execute("INSERT INTO recordings (source_id, external_id, facility) VALUES (1, ?, ?)", (external_id, facility)).lastrowid
    for i, (role, text) in enumerate(turns):
        xid = conn.execute("INSERT INTO transmissions (recording_id, external_id, start_s, end_s, speaker_role) VALUES (?, ?, ?, ?, ?)",
                           (rid, f"x{i}", 10.0 * i, 10.0 * i + 3, role)).lastrowid
        conn.execute("INSERT INTO transcripts (transmission_id, kind, model, raw_text, normalized_text) VALUES (?, 'gold', 'human', ?, ?)",
                     (xid, text, text))
    conn.commit()
    return rid


SEQUENCE = [
    ("controller", "csa one two three runway three one cleared to land wind calm"),
    ("pilot", "cleared to land runway three one csa one two three"),
    ("controller", "lufthansa four five six cross runway three one"),          # CROSS while csa still has LAND -> alert
    ("pilot", "crossing runway three one lufthansa four five six"),
    ("pilot", "runway vacated csa one two three"),
    ("controller", "lufthansa four five six contact ground one two one nine"),
    ("pilot", "one two one five lufthansa four five six"),                     # wrong frequency -> readback warning
]


def test_load_recording_is_in_time_order_and_picks_the_transcript_kind(tmp_path):
    conn = init_db(tmp_path / "t.sqlite")
    rid = _seed(conn, SEQUENCE)
    txs = load_recording(conn, rid)
    assert [(tx.role, tx.start_s) for tx in txs][:3] == [("controller", 0.0), ("pilot", 10.0), ("controller", 20.0)]
    assert txs[0].text == SEQUENCE[0][1] and txs[0].transcript_id > 0
    conn.execute("INSERT INTO transcripts (transmission_id, kind, model, raw_text, normalized_text) VALUES (?, 'asr', 'w', 'x', 'asr text')", (txs[2].id,))
    asr = load_recording(conn, rid, transcript_kind="asr")
    assert [(tx.id, tx.text) for tx in asr] == [(txs[2].id, "asr text")]
    assert load_recording(conn, 999) == []


def test_build_context_modes(tmp_path):
    conn = init_db(tmp_path / "t.sqlite")
    txs = load_recording(conn, _seed(conn, SEQUENCE))
    state, _ = fold([ClearToLand(callsign="csa one two three", runway="31", text="x")])
    assert build_context("none", txs[5], txs[:5], state) == Context(mode="none")
    assert build_context("role", txs[5], txs[:5], state) == Context(mode="role", role="controller")
    win = build_context("window", txs[5], txs[:5], state)
    assert win.mode == "window" and win.role == "controller"
    assert win.history == tuple((r, t) for r, t in SEQUENCE[1:5])     # last 4, oldest first
    assert win.active_callsigns == ("csa one two three",) and win.active_runways == ("31",)
    assert build_context("window", txs[0], [], State()).history == ()
    with pytest.raises(ValueError):
        build_context("everything", txs[0], [], State())


def test_list_recordings_keeps_tower_recordings_with_enough_transmissions_and_a_runway(tmp_path):
    conn = init_db(tmp_path / "t.sqlite")
    big = _seed(conn, SEQUENCE, external_id="big")
    _seed(conn, SEQUENCE[:2], external_id="short")
    _seed(conn, SEQUENCE, external_id="approach", facility="Approach")
    _seed(conn, [("controller", "csa one two three descend flight level one hundred")] * 5, external_id="no-runway")
    rows = list_recordings(conn)
    assert [(r["id"], r["external_id"], r["n_transmissions"], r["n_runway_mentions"]) for r in rows] == [(big, "big", 7, 5)]
    assert list_recordings(conn, min_transmissions=2)[1]["external_id"] == "short"
