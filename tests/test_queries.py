from atcdb.loader import load_enriched_csv
from atcdb.queries import exchange
from atcdb.schema import init_db


def test_exchange_returns_recording_in_time_order_with_roles_and_text(tmp_path, fixture_csv):
    conn = init_db(tmp_path / "t.sqlite")
    load_enriched_csv(conn, fixture_csv, project_root=tmp_path)
    turns = exchange(conn, "uwb-atcc", "uwb-atcc_TWR-Cs5J1G")
    assert [(t["start_s"], t["speaker_role"], t["text"]) for t in turns] == [
        (6.4, "controller", "lufthansa five mike echo contact ground one two one nine bye"),
        (9.0, "pilot", "one two one nine bye bye lufthansa five mike echo"),
    ]


def test_exchange_for_unknown_recording_is_empty(tmp_path, fixture_csv):
    conn = init_db(tmp_path / "t.sqlite")
    load_enriched_csv(conn, fixture_csv, project_root=tmp_path)
    assert exchange(conn, "uwb-atcc", "does-not-exist") == []
