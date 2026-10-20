import sqlite3
import sys
from dataclasses import replace

import pytest

from atcdb import engine, parse_llm
from atcdb.engine import ClearTakeoff, ClearToLand, Handoff, NoOp, ReadbackObserved, State, Unresolved, fold
from atcdb.parse_rules import VERSION
from atcdb.parsing import Context
from atcdb.replay import (PARSER_AVAILABILITY, PARSER_MODELS, PARSER_VERSIONS, PARSERS, Step, Timeline, build_context,
                          build_timeline, cache_version, clear_events, default_transcript_model, get_events, get_recording,
                          list_recordings, load_recording, real_recordings, transcript_models, uncached_parses)
from atcdb.schema import init_db


def _fake_parser(events_by_text, calls):
    def parse(tx, ctx):
        calls.append(tx.text)
        out = events_by_text[tx.text]
        if isinstance(out, Exception):
            raise out
        return out
    return lambda model: parse   # PARSERS maps a parser name to a factory taking the model id


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
    monkeypatch.setitem(PARSER_MODELS, "rule", ["fake"])
    monkeypatch.setitem(PARSER_VERSIONS, "rule", "v0")
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
    calls = []
    monkeypatch.setitem(PARSERS, "rule", _fake_parser(table, calls))
    tl = build_timeline(conn, rid, context="role")
    assert [s.error for s in tl.steps] == [None, "RuntimeError: api down", None]
    assert tl.steps[1].events == () and tl.steps[1].state == tl.steps[0].state
    assert tl.steps[2].state.seq == 2
    assert conn.execute("SELECT count(*) FROM events").fetchone()[0] == 2   # the failed one was not cached
    # a `role` replay never sees engine state, so an earlier error does not stop later transmissions from parsing
    assert calls == [SEQUENCE[0][1], SEQUENCE[1][1], SEQUENCE[2][1]]


def test_build_timeline_skips_later_window_transmissions_after_a_parse_fails(tmp_path, monkeypatch):
    conn = init_db(tmp_path / "t.sqlite")
    rid = _seed(conn, [("controller", "csa one two three runway three one cleared to land"),
                       ("controller", "csa one two three cleared for takeoff")])
    txs = load_recording(conn, rid)
    landing = ClearToLand(callsign="csa one two three", runway="31")
    takeoff = ClearTakeoff(callsign="csa one two three", runway="31")
    tx0_attempts = []

    def flaky_tx0_then_context_sensitive_tx1(tx, ctx):
        if tx.id == txs[0].id:
            tx0_attempts.append(1)
            if len(tx0_attempts) == 1:
                raise RuntimeError("api down")
            return [landing]
        return [takeoff] if ctx.active_runways == ("31",) else []   # only right if tx0's LAND made it into state

    monkeypatch.setitem(PARSERS, "rule", lambda model: flaky_tx0_then_context_sensitive_tx1)

    run1 = build_timeline(conn, rid)   # window is the default context
    assert run1.steps[0].error == "RuntimeError: api down" and run1.steps[0].events == ()
    assert run1.steps[1].error == "skipped: an earlier transmission failed to parse, so the window context is incomplete"
    assert run1.steps[1].events == ()
    assert conn.execute("SELECT count(*) FROM events").fetchone()[0] == 0   # tx1 was never parsed or cached

    run2 = build_timeline(conn, rid)   # tx0 now parses; tx1 sees the right context and is parsed for real
    assert run2.steps[0].error is None and run2.steps[0].events == (landing,)     # a fresh parse: raw parser output
    assert run2.steps[1].error is None and run2.steps[1].events == (takeoff,)
    assert conn.execute("SELECT count(*) FROM events").fetchone()[0] == 2


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


def test_list_recordings_returns_plain_dicts(tmp_path):
    conn = init_db(tmp_path / "t.sqlite")
    rid = _seed(conn, SEQUENCE)
    rows = list_recordings(conn)
    assert rows == [{"id": rid, "source": "test", "external_id": "r1", "airport_icao": None, "facility": "Tower",
                     "n_transmissions": 7, "n_runway_mentions": 5}]
    assert type(rows[0]) is dict


def test_get_recording_distinguishes_unknown_from_empty(tmp_path):
    conn = init_db(tmp_path / "t.sqlite")
    rid = _seed(conn, [], external_id="empty")
    assert get_recording(conn, rid) == {"id": rid, "source": "test", "external_id": "empty", "airport_icao": None, "facility": "Tower"}
    assert get_recording(conn, rid + 1) is None


def test_transcript_models_and_the_pinned_default(tmp_path):
    conn = init_db(tmp_path / "t.sqlite")
    assert transcript_models(conn) == {} and default_transcript_model(conn, "gold") is None
    txs = load_recording(conn, _seed(conn, SEQUENCE[:1]))
    for kind, model in (("gold", "atco2-xml"), ("asr", "whisper-b"), ("asr", "whisper-a")):
        conn.execute("INSERT INTO transcripts (transmission_id, kind, model, raw_text, normalized_text) VALUES (?, ?, ?, 'x', 'x')",
                     (txs[0].id, kind, model))
    assert transcript_models(conn) == {"asr": ["whisper-a", "whisper-b"], "gold": ["atco2-xml", "human"]}
    assert default_transcript_model(conn, "gold") == "human"
    assert default_transcript_model(conn, "asr") == "whisper-a"
    assert default_transcript_model(conn, "llm") is None


def test_get_events_returns_the_rows_another_request_stored_first(tmp_path, monkeypatch):
    conn = init_db(tmp_path / "t.sqlite")
    txs = load_recording(conn, _seed(conn, SEQUENCE[:1]))

    def racing_parser(tx, ctx):   # a concurrent request caches the same parse while this one is still parsing
        conn.execute("INSERT INTO events (transcript_id, parser, model, model_version, context, seq, kind, callsign, runway) "
                     "VALUES (?, 'rule', 'rules', ?, 'role', 0, 'LAND', 'csa one two three', '31')", (tx.transcript_id, VERSION))
        conn.commit()
        return [ClearToLand(callsign="csa one two three", runway="31")]

    monkeypatch.setitem(PARSERS, "rule", lambda model: racing_parser)
    assert get_events(conn, txs[0], "rule", Context(mode="role", role="controller")) == \
        [ClearToLand(callsign="csa one two three", runway="31", t=0.0, text=SEQUENCE[0][1])]
    assert conn.execute("SELECT count(*) FROM events").fetchone()[0] == 1


def test_get_events_never_mixes_two_different_racing_parses(tmp_path, monkeypatch):
    conn = init_db(tmp_path / "t.sqlite")
    txs = load_recording(conn, _seed(conn, SEQUENCE[:1]))

    def racing_parser(tx, ctx):   # the other request cached a one-row NOOP parse; this request parses two different rows
        conn.execute("INSERT INTO events (transcript_id, parser, model, model_version, context, seq, kind) "
                     "VALUES (?, 'rule', 'rules', ?, 'role', 0, 'NOOP')", (tx.transcript_id, VERSION))
        conn.commit()
        return [ClearToLand(callsign="csa one two three", runway="31"), ReadbackObserved(callsign="csa one two three", text="x")]

    monkeypatch.setitem(PARSERS, "rule", lambda model: racing_parser)
    assert get_events(conn, txs[0], "rule", Context(mode="role", role="controller")) == [NoOp(t=0.0, text=SEQUENCE[0][1])]
    assert [tuple(r) for r in conn.execute("SELECT seq, kind FROM events ORDER BY seq")] == [(0, "NOOP")]


def test_build_timeline_counts_dropped_instructions(tmp_path):
    conn = init_db(tmp_path / "t.sqlite")
    rid = _seed(conn, [("controller", "csa one two three cleared to land"),                  # no runway anywhere: dropped
                       ("controller", "lufthansa four five six runway three one cleared for takeoff")])
    tl = build_timeline(conn, rid, context="role")
    assert [s.dropped for s in tl.steps] == [1, 0] and tl.dropped == 1


def test_build_timeline_counts_events_the_engine_ignored(tmp_path, monkeypatch):
    conn = init_db(tmp_path / "t.sqlite")
    rid = _seed(conn, [("controller", "a contact grund one two one nine")])
    monkeypatch.setitem(PARSERS, "rule", _fake_parser({"a contact grund one two one nine": [Handoff(callsign="a", to="grund")]}, []))
    tl = build_timeline(conn, rid, context="role")
    assert tl.steps[0].dropped == 1


def test_window_parses_are_keyed_by_the_engine_version(tmp_path, monkeypatch):
    conn = init_db(tmp_path / "t.sqlite")
    txs = load_recording(conn, _seed(conn, SEQUENCE[:1]))
    calls = []
    monkeypatch.setitem(PARSERS, "rule", _fake_parser({SEQUENCE[0][1]: [NoOp()]}, calls))
    window, role = Context(mode="window", role="controller"), Context(mode="role", role="controller")
    get_events(conn, txs[0], "rule", window)
    get_events(conn, txs[0], "rule", role)
    stored = sorted(r[0] for r in conn.execute("SELECT model_version FROM events"))
    assert stored == [VERSION, f"{VERSION}+engine{engine.ENGINE_VERSION}"]
    monkeypatch.setattr(engine, "ENGINE_VERSION", "test")
    assert (cache_version("v1", "window"), cache_version("v1", "role"), cache_version("v1", "none")) == ("v1+enginetest", "v1", "v1")
    get_events(conn, txs[0], "rule", window)   # a new engine: the window parse is a miss and is parsed again
    get_events(conn, txs[0], "rule", role)     # role parses never see engine state: still served from the cache
    assert len(calls) == 3


def test_get_events_re_raises_an_integrity_error_that_left_no_rows(tmp_path, monkeypatch):
    conn = init_db(tmp_path / "t.sqlite")
    txs = load_recording(conn, _seed(conn, SEQUENCE[:1]))
    monkeypatch.setitem(PARSERS, "rule", _fake_parser({SEQUENCE[0][1]: [NoOp()]}, []))
    orphan = replace(txs[0], transcript_id=999_999)   # no such transcript: the foreign key fails and nobody cached anything
    with pytest.raises(sqlite3.IntegrityError):
        get_events(conn, orphan, "rule", Context(mode="role", role="controller"))


def test_the_pinned_transcript_model_is_chosen_per_recording(tmp_path):
    conn = init_db(tmp_path / "t.sqlite")
    human = _seed(conn, SEQUENCE[:1], external_id="human")
    synthetic = _seed(conn, SEQUENCE[:1], external_id="synthetic")
    conn.execute("UPDATE transcripts SET model = 'synthetic' WHERE transmission_id IN "
                 "(SELECT id FROM transmissions WHERE recording_id = ?)", (synthetic,))
    assert default_transcript_model(conn, "gold") == "human"                 # database-wide, as before
    assert default_transcript_model(conn, "gold", human) == "human"
    assert default_transcript_model(conn, "gold", synthetic) == "synthetic"  # conflict injection's recordings replay
    assert default_transcript_model(conn, "asr", synthetic) is None


def test_an_unknown_model_for_the_parser_is_rejected(tmp_path):
    conn = init_db(tmp_path / "t.sqlite")
    rid = _seed(conn, SEQUENCE[:1])
    txs = load_recording(conn, rid)
    msg = "unknown model 'claude-sonnet-5' for parser 'rule'"
    with pytest.raises(ValueError, match=msg):
        get_events(conn, txs[0], "rule", Context(mode="role", role="controller"), model="claude-sonnet-5")
    with pytest.raises(ValueError, match=msg):
        build_timeline(conn, rid, parser="rule", model="claude-sonnet-5")
    with pytest.raises(ValueError, match=msg):
        uncached_parses(conn, rid, parser="rule", model="claude-sonnet-5")
    assert conn.execute("SELECT count(*) FROM events").fetchone()[0] == 0   # nothing was cached under the wrong model


def test_the_registry_knows_both_parsers_and_their_models():
    assert PARSER_MODELS == {"rule": ["rules"], "llm": ["claude-haiku-4-5", "claude-sonnet-5", "claude-haiku-5-5"]}
    assert PARSER_VERSIONS == {"rule": VERSION, "llm": "p1"}
    assert set(PARSERS) == set(PARSER_AVAILABILITY) == set(PARSER_MODELS)
    assert PARSER_AVAILABILITY["rule"]() == (True, None)


def test_llm_replays_resolve_the_model_only_on_a_miss_and_cache_unresolved_events(tmp_path, monkeypatch):
    conn = init_db(tmp_path / "t.sqlite")
    rid = _seed(conn, SEQUENCE[:2])
    made, calls = [], []
    table = {SEQUENCE[0][1]: [ClearToLand(callsign="csa one two three", runway="31"), Unresolved(callsign="csa one two three", raw="x")],
             SEQUENCE[1][1]: [ReadbackObserved(callsign="csa one two three", text=SEQUENCE[1][1])]}

    def factory(model):
        made.append(model)
        return _fake_parser(table, calls)(model)

    monkeypatch.setitem(PARSERS, "llm", factory)
    tl = build_timeline(conn, rid, parser="llm", model="claude-sonnet-5")
    assert (tl.parser, tl.model, tl.model_version) == ("llm", "claude-sonnet-5", "p1")
    assert made == ["claude-sonnet-5"] * 2 and len(calls) == 2
    assert [s.dropped for s in tl.steps] == [1, 0]
    again = build_timeline(conn, rid, parser="llm", model="claude-sonnet-5")   # all cached: no parser is even created
    assert len(made) == 2 and [s.dropped for s in again.steps] == [1, 0]
    assert [tuple(r) for r in conn.execute("SELECT DISTINCT parser, model, model_version FROM events")] == \
        [("llm", "claude-sonnet-5", f"p1+engine{engine.ENGINE_VERSION}")]
    assert build_timeline(conn, rid, parser="llm").model == "claude-haiku-4-5"   # the first model is the default


def test_a_cached_llm_replay_works_with_anthropic_absent(tmp_path, monkeypatch):
    conn = init_db(tmp_path / "t.sqlite")
    rid = _seed(conn, SEQUENCE[:2])
    txs = load_recording(conn, rid)
    calls = []
    monkeypatch.setitem(PARSERS, "llm",
                        _fake_parser({SEQUENCE[0][1]: [ClearToLand(callsign="csa one two three", runway="31")],
                                      SEQUENCE[1][1]: [NoOp()]}, calls))
    first = build_timeline(conn, rid, parser="llm")   # fills the cache under the real registry entry's model/version
    assert len(calls) == 2 and all(s.error is None for s in first.steps)
    monkeypatch.setitem(PARSERS, "llm", parse_llm.make_parser)   # restore the real registry entry

    monkeypatch.setitem(sys.modules, "anthropic", None)   # makes `import anthropic` raise ImportError
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    again = build_timeline(conn, rid, parser="llm")   # served entirely from the cache: no SDK, no key needed
    assert again.steps[0].events == (ClearToLand(callsign="csa one two three", runway="31", t=txs[0].start_s, text=txs[0].text),)
    assert again.steps[1].events == (NoOp(t=txs[1].start_s, text=txs[1].text),)
    assert all(s.error is None for s in again.steps)
    assert len(calls) == 2   # the second replay never touched the (now-blocked) parser


def test_uncached_parses_lists_what_a_replay_would_still_have_to_parse(tmp_path):
    conn = init_db(tmp_path / "t.sqlite")
    rid = _seed(conn, SEQUENCE[:3])
    txs = load_recording(conn, rid)
    assert [tx for tx, _ in uncached_parses(conn, rid)] == txs
    build_timeline(conn, rid)                                  # the rules parser caches all three in window mode
    assert uncached_parses(conn, rid) == []
    assert len(uncached_parses(conn, rid, context="role")) == 3   # another context mode is another cache entry
    conn.execute("DELETE FROM events WHERE transcript_id = ?", (txs[2].transcript_id,))
    conn.commit()
    [(tx, ctx)] = uncached_parses(conn, rid)
    assert tx == txs[2] and ctx.active_runways == ("31",)       # the cached LAND on 31 is folded into the context
    assert ctx.history == tuple((r, t) for r, t in SEQUENCE[:2])
    assert conn.execute("SELECT count(*) FROM events").fetchone()[0] == 2   # counting parsed and stored nothing


def test_real_recordings_leaves_out_the_synthetic_conflicts(tmp_path):
    conn = init_db(tmp_path / "t.sqlite")
    real = _seed(conn, SEQUENCE, external_id="real")
    fake = _seed(conn, SEQUENCE, external_id="fake")
    conn.execute("INSERT INTO sources (id, name, kind) VALUES (2, 'synthetic-conflicts', 'corpus')")
    conn.execute("UPDATE recordings SET source_id = 2 WHERE id = ?", (fake,))
    assert {r["id"] for r in list_recordings(conn)} == {real, fake}   # both replay in the app
    assert [r["id"] for r in real_recordings(conn)] == [real]
    assert real_recordings(conn, min_transmissions=99) == []
