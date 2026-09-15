import pytest

from atcdb.engine import ClearToLand, NoOp, State, fold
from atcdb.parsing import Context
from atcdb.replay import (PARSER_MODELS, PARSERS, Step, Timeline, build_context, build_timeline, clear_events,
                          get_events, list_recordings, load_recording)
from atcdb.schema import init_db


def _fake_parser(events_by_text, calls):
    def parse(tx, ctx):
        calls.append(tx.text)
        out = events_by_text[tx.text]
        if isinstance(out, Exception):
            raise out
        return out
    return parse


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


def test_get_events_parses_once_then_serves_the_cache(tmp_path, monkeypatch):
    conn = init_db(tmp_path / "t.sqlite")
    txs = load_recording(conn, _seed(conn, SEQUENCE[:1]))
    calls = []
    monkeypatch.setitem(PARSERS, "rule", _fake_parser({SEQUENCE[0][1]: [ClearToLand(callsign="csa one two three", runway="31")]}, calls))
    monkeypatch.setitem(PARSER_MODELS, "rule", ("fake", "v0"))
    ctx = Context(mode="role", role="controller")
    first = get_events(conn, txs[0], "rule", ctx)
    second = get_events(conn, txs[0], "rule", ctx)
    assert calls == [SEQUENCE[0][1]]
    assert first == [ClearToLand(callsign="csa one two three", runway="31")]
    assert second == [ClearToLand(callsign="csa one two three", runway="31", t=0.0, text=SEQUENCE[0][1])]
    rows = conn.execute("SELECT parser, model, model_version, context, seq, kind, runway FROM events").fetchall()
    assert [tuple(r) for r in rows] == [("rule", "fake", "v0", "role", 0, "LAND", "31")]
    get_events(conn, txs[0], "rule", Context(mode="none"))   # a different context mode is a different cache entry
    assert len(calls) == 2 and conn.execute("SELECT count(*) FROM events").fetchone()[0] == 2


def test_get_events_stores_a_noop_row_for_an_empty_parse(tmp_path, monkeypatch):
    conn = init_db(tmp_path / "t.sqlite")
    txs = load_recording(conn, _seed(conn, SEQUENCE[:1]))
    calls = []
    monkeypatch.setitem(PARSERS, "rule", _fake_parser({SEQUENCE[0][1]: []}, calls))
    get_events(conn, txs[0], "rule", Context(mode="role", role="controller"))
    assert get_events(conn, txs[0], "rule", Context(mode="role", role="controller")) == [NoOp(t=0.0, text=SEQUENCE[0][1])]
    assert calls == [SEQUENCE[0][1]]
    assert conn.execute("SELECT kind FROM events").fetchone()[0] == "NOOP"


def test_get_events_does_not_cache_a_failed_parse(tmp_path, monkeypatch):
    conn = init_db(tmp_path / "t.sqlite")
    txs = load_recording(conn, _seed(conn, SEQUENCE[:1]))
    monkeypatch.setitem(PARSERS, "rule", _fake_parser({SEQUENCE[0][1]: RuntimeError("api down")}, []))
    with pytest.raises(RuntimeError):
        get_events(conn, txs[0], "rule", Context(mode="role", role="controller"))
    assert conn.execute("SELECT count(*) FROM events").fetchone()[0] == 0


def test_build_timeline_with_the_rules_parser_end_to_end(tmp_path):
    conn = init_db(tmp_path / "t.sqlite")
    rid = _seed(conn, SEQUENCE)
    tl = build_timeline(conn, rid)
    assert isinstance(tl, Timeline) and (tl.parser, tl.model, tl.context, tl.transcript_kind) == ("rule", "rules", "window", "gold")
    assert len(tl.steps) == 7 and all(isinstance(s, Step) and s.error is None for s in tl.steps)
    assert [(r.callsign, r.kind) for r in tl.steps[0].state.runways["31"]] == [("csa one two three", "LAND")]
    assert tl.steps[1].conflicts == () and tl.steps[1].state.aircraft["csa one two three"].pending is None
    c = tl.steps[2].conflicts
    assert len(c) == 1 and (c[0].type, c[0].severity, c[0].runway, c[0].callsigns) == ("RUNWAY", "alert", "31", ("lufthansa four five six", "csa one two three"))
    assert tl.steps[4].state.aircraft["csa one two three"].runway is None            # runway vacated
    assert "31" not in tl.steps[5].state.runways                                      # handoff to ground released the crossing
    r = tl.steps[6].conflicts
    assert len(r) == 1 and (r[0].type, r[0].severity, r[0].callsigns) == ("READBACK", "warning", ("lufthansa four five six",))
    assert sum(len(s.conflicts) for s in tl.steps) == 2
    assert conn.execute("SELECT count(DISTINCT transcript_id) FROM events").fetchone()[0] == 7
    again = build_timeline(conn, rid)   # second run is served from the cache and must be identical
    assert [s.events for s in again.steps] == [s.events for s in tl.steps]


def test_build_timeline_records_a_parser_error_and_keeps_going(tmp_path, monkeypatch):
    conn = init_db(tmp_path / "t.sqlite")
    rid = _seed(conn, SEQUENCE[:3])
    table = {SEQUENCE[0][1]: [ClearToLand(callsign="csa one two three", runway="31")],
             SEQUENCE[1][1]: RuntimeError("api down"),
             SEQUENCE[2][1]: [NoOp()]}
    monkeypatch.setitem(PARSERS, "rule", _fake_parser(table, []))
    tl = build_timeline(conn, rid, context="role")
    assert [s.error for s in tl.steps] == [None, "RuntimeError: api down", None]
    assert tl.steps[1].events == () and tl.steps[1].state == tl.steps[0].state
    assert tl.steps[2].state.seq == 2
    assert conn.execute("SELECT count(*) FROM events").fetchone()[0] == 2   # the failed one was not cached


def test_clear_events_deletes_only_the_matching_cache_entries(tmp_path, monkeypatch):
    conn = init_db(tmp_path / "t.sqlite")
    txs = load_recording(conn, _seed(conn, SEQUENCE[:1]))
    monkeypatch.setitem(PARSERS, "rule", _fake_parser({SEQUENCE[0][1]: [NoOp()]}, []))
    get_events(conn, txs[0], "rule", Context(mode="role", role="controller"))
    get_events(conn, txs[0], "rule", Context(mode="window", role="controller"))
    assert conn.execute("SELECT count(*) FROM events").fetchone()[0] == 2
    assert clear_events(conn, "rule", context="window") == 1
    assert [r[0] for r in conn.execute("SELECT context FROM events")] == ["role"]
    assert clear_events(conn, "rule") == 1 and conn.execute("SELECT count(*) FROM events").fetchone()[0] == 0
    assert clear_events(conn, "rule") == 0
