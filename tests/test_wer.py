from atcdb.loader import load_enriched_csv
from atcdb.schema import init_db
from atcdb.wer import score_model


def _put_asr(conn, external_id, text, model="m", version="v1"):
    tid = conn.execute("SELECT id FROM transmissions WHERE external_id = ?", (external_id,)).fetchone()[0]
    conn.execute("INSERT INTO transcripts (transmission_id, kind, model, model_version, raw_text, normalized_text) VALUES (?, 'asr', ?, ?, ?, ?)",
                 (tid, model, version, text, text))
    conn.commit()


def test_overall_wer_is_computed_over_transmissions_that_have_both_gold_and_asr(tmp_path, fixture_csv):
    conn = init_db(tmp_path / "t.sqlite")
    load_enriched_csv(conn, fixture_csv, project_root=tmp_path)
    # gold: "we are not ready now foxtrot lima delta" (8 words) -> 1 substitution
    _put_asr(conn, "atco2_test-set-1h_LSGS_SION_Tower_118_3MHz_20210502_065945-D__000000-000300", "we are not ready now foxtrot lima deltas")
    # gold: "lufthansa five mike echo contact ground one two one nine bye" (11 words) -> exact
    _put_asr(conn, "uwb-atcc_TWR-Cs5J1G_000640_000900_AT", "lufthansa five mike echo contact ground one two one nine bye")
    res = score_model(conn, model="m", model_version="v1")
    assert res["n"] == 2
    assert abs(res["wer"] - 1 / 19) < 1e-9


def test_wer_slices_by_role_and_corpus(tmp_path, fixture_csv):
    conn = init_db(tmp_path / "t.sqlite")
    load_enriched_csv(conn, fixture_csv, project_root=tmp_path)
    _put_asr(conn, "atco2_test-set-1h_LSGS_SION_Tower_118_3MHz_20210502_065945-D__000000-000300", "we are not ready now foxtrot lima deltas")
    _put_asr(conn, "uwb-atcc_TWR-Cs5J1G_000640_000900_AT", "lufthansa five mike echo contact ground one two one nine bye")
    res = score_model(conn, model="m", model_version="v1")
    assert res["by"]["speaker_role"]["controller"]["wer"] == 0.0
    assert abs(res["by"]["speaker_role"]["unknown"]["wer"] - 1 / 8) < 1e-9
    assert res["by"]["source_corpus"]["atco2-1h"]["n"] == 1


def test_marker_survival_compares_informal_word_rates_between_gold_and_asr(tmp_path, fixture_csv):
    conn = init_db(tmp_path / "t.sqlite")
    load_enriched_csv(conn, fixture_csv, project_root=tmp_path)
    _put_asr(conn, "uwb-atcc_TWR-Cs5J1G_000640_000900_AT", "lufthansa five mike echo contact ground one two one nine")  # dropped "bye"
    _put_asr(conn, "uwb-atcc_TWR-Cs5J1G_000900_001150_PI", "one two one nine bye bye lufthansa five mike echo")        # kept both
    res = score_model(conn, model="m", model_version="v1", markers=["bye"])
    assert res["markers"]["bye"] == {"gold": 3, "asr": 2, "survival": 2 / 3}
