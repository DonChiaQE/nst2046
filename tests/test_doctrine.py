from atcdb import doctrine
from atcdb.engine import MATRIX, MATRIX_BASIS
from atcdb.schema import init_db


def test_every_rule_has_the_schema_columns_and_a_unique_id():
    assert len({r["id"] for r in doctrine.RULES}) == len(doctrine.RULES)
    for r in doctrine.RULES:
        assert set(r) == {"id", "document", "section", "category", "pattern", "description"}
        assert (r["section"] is None) == (r["document"] == doctrine.HEURISTIC)   # a heuristic cites no paragraph


def test_every_matrix_citation_names_a_rule_and_a_real_cell():
    ids = {r["id"] for r in doctrine.RULES}
    assert set(MATRIX_BASIS) <= set(MATRIX)
    assert set(MATRIX_BASIS.values()) <= ids


def test_init_db_seeds_phraseology_rules_idempotently(tmp_path):
    conn = init_db(tmp_path / "t.sqlite")
    conn = init_db(tmp_path / "t.sqlite")   # a second open must not duplicate or fail
    rows = conn.execute("SELECT id, document, section FROM phraseology_rules ORDER BY id").fetchall()
    assert len(rows) == len(doctrine.RULES)
    assert ("icao-4444-7.9.2", doctrine.DOC_4444, "7.9.2") in [tuple(r) for r in rows]


def test_seed_writes_nothing_once_the_table_already_matches_rules_but_corrects_a_stale_row(tmp_path):
    conn = init_db(tmp_path / "t.sqlite")
    before = conn.total_changes
    doctrine.seed(conn)   # table already matches RULES: no write, no commit
    assert conn.total_changes == before

    rule_id = doctrine.RULES[0]["id"]
    conn.execute("UPDATE phraseology_rules SET description = 'stale' WHERE id = ?", (rule_id,))
    conn.commit()
    doctrine.seed(conn)   # table now differs from RULES: the stale row is corrected
    row = conn.execute("SELECT description FROM phraseology_rules WHERE id = ?", (rule_id,)).fetchone()
    assert row[0] == doctrine.RULES[0]["description"]


def test_seed_ignores_a_foreign_row_it_does_not_own(tmp_path):
    # phraseology_rules is shared: annotations.rule_id references rows seed() does not own (e.g. a human annotator's
    # own rule). seed() must compare only the ids in RULES, not the whole table, or a foreign row makes every
    # comparison miss and every init_db call rewrites and commits (spec finding: init_db runs once per API request).
    conn = init_db(tmp_path / "t.sqlite")
    conn.execute(
        "INSERT INTO phraseology_rules (id, document, section, category, pattern, description) VALUES (?, ?, ?, ?, ?, ?)",
        ("human-note-1", "human", None, "note", None, "a human annotator's own rule row, not in doctrine.RULES"))
    conn.commit()
    before = conn.total_changes
    doctrine.seed(conn)   # table matches RULES on every id RULES cares about: no write, no commit
    assert conn.total_changes == before
    row = conn.execute("SELECT id FROM phraseology_rules WHERE id = ?", ("human-note-1",)).fetchone()
    assert row is not None
