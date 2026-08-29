from atcdb.asr import normalize_asr_text, run_asr
from atcdb.loader import load_enriched_csv
from atcdb.schema import init_db


def test_normalize_lowercases_strips_punctuation_and_spells_digits():
    assert normalize_asr_text("Swiss 124, descend Flight Level 100.") == "swiss one two four descend flight level one zero zero"


def test_normalize_decimal_frequency_and_whitespace():
    assert normalize_asr_text("  contact ground 121.9 \n bye ") == "contact ground one two one decimal nine bye"


def test_normalize_keeps_apostrophe_free_words_and_hyphen_splits():
    assert normalize_asr_text("x-ray, we're ready") == "x ray we're ready"


def fake_transcriber(clip_path):
    # deterministic stand-in for the model: echoes the split directory so tests can check routing
    return {"text": f"Hello from {clip_path.parent.name}", "avg_logprob": -0.25, "no_speech_prob": 0.01,
            "words": [{"word": "hello", "start": 0.0, "end": 0.4, "probability": 0.9}]}


def test_run_asr_stores_one_asr_transcript_per_transmission_in_split(tmp_path, fixture_csv):
    conn = init_db(tmp_path / "t.sqlite")
    load_enriched_csv(conn, fixture_csv, project_root=tmp_path)
    n = run_asr(conn, model_name="fake", model_version="v1", transcriber=fake_transcriber, project_root=tmp_path, split="test")
    assert n == 2
    rows = conn.execute("SELECT x.external_id, t.raw_text, t.normalized_text, t.confidence, t.words_json FROM transcripts t "
                        "JOIN transmissions x ON x.id = t.transmission_id WHERE t.kind = 'asr' AND t.model = 'fake' ORDER BY x.external_id").fetchall()
    assert len(rows) == 2
    assert rows[0]["raw_text"] == "Hello from test"
    assert rows[0]["normalized_text"] == "hello from test"
    assert rows[0]["confidence"] == -0.25
    assert '"probability": 0.9' in rows[0]["words_json"]


def test_run_asr_skips_transmissions_already_transcribed_by_that_model(tmp_path, fixture_csv):
    conn = init_db(tmp_path / "t.sqlite")
    load_enriched_csv(conn, fixture_csv, project_root=tmp_path)
    assert run_asr(conn, "fake", "v1", fake_transcriber, project_root=tmp_path, split="test") == 2
    assert run_asr(conn, "fake", "v1", fake_transcriber, project_root=tmp_path, split="test") == 0
    assert run_asr(conn, "fake", "v2", fake_transcriber, project_root=tmp_path, split="test") == 2  # new version -> new rows
    assert conn.execute("SELECT count(*) FROM transcripts WHERE kind = 'asr'").fetchone()[0] == 4


def test_run_asr_limit(tmp_path, fixture_csv):
    conn = init_db(tmp_path / "t.sqlite")
    load_enriched_csv(conn, fixture_csv, project_root=tmp_path)
    assert run_asr(conn, "fake", "v1", fake_transcriber, project_root=tmp_path, split="train", limit=3) == 3
