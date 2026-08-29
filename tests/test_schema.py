import sqlite3

from atcdb.schema import init_db, TABLES


def table_names(conn):
    return {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}


def test_init_db_creates_all_tables(tmp_path):
    conn = init_db(tmp_path / "t.sqlite")
    assert set(TABLES) <= table_names(conn)
    assert {"sources", "recordings", "transmissions", "transcripts", "annotations", "phraseology_rules", "readback_pairs"} == set(TABLES)


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
