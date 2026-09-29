import sqlite3

import pytest

from atcdb.schema import init_db, TABLES


def table_names(conn):
    return {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}


def test_init_db_creates_all_tables(tmp_path):
    conn = init_db(tmp_path / "t.sqlite")
    assert set(TABLES) <= table_names(conn)
    assert {"sources", "recordings", "transmissions", "transcripts", "annotations", "phraseology_rules",
            "readback_pairs", "events", "judgments"} == set(TABLES)


def _seed_transcript(conn) -> int:
    conn.execute("INSERT INTO sources (id, name, kind) VALUES (1, 's', 'corpus')")
    conn.execute("INSERT INTO recordings (id, source_id, external_id) VALUES (1, 1, 'r1')")
    conn.execute("INSERT INTO transmissions (id, recording_id, external_id) VALUES (1, 1, 'x1')")
    conn.execute("INSERT INTO transcripts (id, transmission_id, kind, model, raw_text, normalized_text) "
                 "VALUES (1, 1, 'gold', 'human', 'a', 'a')")
    conn.commit()
    return 1


def test_events_rows_are_unique_per_transcript_parser_model_context_seq(tmp_path):
    conn = init_db(tmp_path / "t.sqlite")
    tid = _seed_transcript(conn)
    row = (tid, "rule", "rules", "v1", "window", 0, "LAND", "csa one two three", "31", None)
    conn.execute("INSERT INTO events (transcript_id, parser, model, model_version, context, seq, kind, callsign, runway, extra_json) "
                 "VALUES (?,?,?,?,?,?,?,?,?,?)", row)
    conn.commit()
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("INSERT INTO events (transcript_id, parser, model, model_version, context, seq, kind, callsign, runway, extra_json) "
                     "VALUES (?,?,?,?,?,?,?,?,?,?)", row)


def test_events_reject_unknown_parser_or_context(tmp_path):
    conn = init_db(tmp_path / "t.sqlite")
    tid = _seed_transcript(conn)
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("INSERT INTO events (transcript_id, parser, model, model_version, context, seq, kind) "
                     "VALUES (?, 'magic', 'm', '', 'window', 0, 'NOOP')", (tid,))
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("INSERT INTO events (transcript_id, parser, model, model_version, context, seq, kind) "
                     "VALUES (?, 'rule', 'm', '', 'everything', 0, 'NOOP')", (tid,))


def test_init_db_is_idempotent_and_keeps_data(tmp_path):
    db = tmp_path / "t.sqlite"
    conn = init_db(db)
    conn.execute("INSERT INTO sources (name, kind) VALUES ('x', 'corpus')")
    conn.commit()
    conn.close()
    conn2 = init_db(db)  # second call must not fail or wipe data
    assert conn2.execute("SELECT count(*) FROM sources").fetchone()[0] == 1


def test_foreign_keys_are_enforced(tmp_path):
    conn = init_db(tmp_path / "t.sqlite")
    try:
        conn.execute("INSERT INTO recordings (source_id, external_id) VALUES (999, 'r1')")
        conn.commit()
        enforced = False
    except sqlite3.IntegrityError:
        enforced = True
    assert enforced


def test_judgments_are_unique_per_recording_transcript_and_judge(tmp_path):
    conn = init_db(tmp_path / "t.sqlite")
    _seed_transcript(conn)
    row = (1, "gold", "human", "claude-sonnet-5", "j1", "[]", "sha")
    sql = ("INSERT INTO judgments (recording_id, transcript_kind, transcript_model, judge_model, judge_version, "
           "conflicts_json, sequence_sha1) VALUES (?,?,?,?,?,?,?)")
    conn.execute(sql, row)
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(sql, row)
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(sql, (1, "llm", "human", "claude-sonnet-5", "j1", "[]", "sha"))
