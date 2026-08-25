from atcdb.loader import load_enriched_csv
from atcdb.schema import init_db


def counts(conn):
    return {t: conn.execute(f"SELECT count(*) FROM {t}").fetchone()[0]
            for t in ["sources", "recordings", "transmissions", "transcripts", "annotations"]}


def test_loader_populates_every_table(tmp_path, fixture_csv):
    conn = init_db(tmp_path / "t.sqlite")
    load_enriched_csv(conn, fixture_csv, project_root=tmp_path)
    # 6 human gold transcripts + 2 atco2-xml transcripts (the two rows that carry ner_text);
    # annotations: row 0 -> callsign/command/value, row 1 -> hesitation + callsign
    assert counts(conn) == {"sources": 2, "recordings": 4, "transmissions": 6, "transcripts": 8, "annotations": 5}


def test_loader_is_idempotent(tmp_path, fixture_csv):
    conn = init_db(tmp_path / "t.sqlite")
    load_enriched_csv(conn, fixture_csv, project_root=tmp_path)
    before = counts(conn)
    load_enriched_csv(conn, fixture_csv, project_root=tmp_path)
    assert counts(conn) == before


def test_recording_metadata_and_transmission_fields(tmp_path, fixture_csv):
    conn = init_db(tmp_path / "t.sqlite")
    load_enriched_csv(conn, fixture_csv, project_root=tmp_path)
    rec = conn.execute("SELECT * FROM recordings WHERE external_id = 'LSZH_ZURICH_Tower_118_1MHz_20210414_085908'").fetchone()
    assert (rec["airport_icao"], rec["facility"], rec["frequency_mhz"], rec["started_at_utc"]) == ("LSZH", "Tower", 118.1, "2021-04-14T08:59:08")
    tx = conn.execute("SELECT * FROM transmissions WHERE external_id LIKE '%-B__000200-000400'").fetchone()
    assert (tx["speaker_role"], tx["pilot_callsign"], tx["start_s"], tx["end_s"], tx["split"]) == ("pilot", "SWR124", 2.0, 4.0, "train")
    assert tx["clip_path"] == "jacktol-atc/clips/train/train_00001.wav"
    assert len(tx["pcm_sha1"]) == 40
    assert tx["sample_rate"] == 8000


def test_human_gold_transcript_is_loaded(tmp_path, fixture_csv):
    conn = init_db(tmp_path / "t.sqlite")
    load_enriched_csv(conn, fixture_csv, project_root=tmp_path)
    tr = conn.execute("""SELECT t.* FROM transcripts t JOIN transmissions x ON x.id = t.transmission_id
                         WHERE x.external_id LIKE '%-A__000000-000200' AND t.model = 'human'""").fetchone()
    assert (tr["kind"], tr["normalized_text"]) == ("gold", "swiss one two four descend flight level one hundred")


def test_ner_annotations_attach_to_a_separate_xml_transcript_with_exact_indices(tmp_path, fixture_csv):
    conn = init_db(tmp_path / "t.sqlite")
    load_enriched_csv(conn, fixture_csv, project_root=tmp_path)
    # fixture row 1's XML text differs from jacktol's gold text in word count -> spans must index the XML text
    xml = conn.execute("""SELECT t.* FROM transcripts t JOIN transmissions x ON x.id = t.transmission_id
                          WHERE x.external_id LIKE '%-B__000200-000400' AND t.model = 'atco2-xml'""").fetchone()
    assert xml["kind"] == "gold"
    assert xml["raw_text"] == "[hes] descending flight level one hundred swiss one two four"
    spans = conn.execute("SELECT start_word, end_word, category, provenance, annotator FROM annotations WHERE transcript_id = ? ORDER BY start_word",
                         (xml["id"],)).fetchall()
    assert [tuple(s) for s in spans] == [(0, 0, "hesitation", "human", "atco2"), (6, 9, "callsign", "human", "atco2")]
    human_id = conn.execute("SELECT id FROM transcripts WHERE transmission_id = ? AND model = 'human'", (xml["transmission_id"],)).fetchone()[0]
    assert conn.execute("SELECT count(*) FROM annotations WHERE transcript_id = ?", (human_id,)).fetchone()[0] == 0


def test_mixed_role_and_uwb_recording_without_airport(tmp_path, fixture_csv):
    conn = init_db(tmp_path / "t.sqlite")
    load_enriched_csv(conn, fixture_csv, project_root=tmp_path)
    tx = conn.execute("SELECT x.speaker_role, r.airport_icao, r.facility FROM transmissions x JOIN recordings r ON r.id = x.recording_id "
                      "WHERE x.external_id = 'uwb-atcc_ACCU-99d9Oj_001614_001992_PIAT'").fetchone()
    assert (tx["speaker_role"], tx["airport_icao"], tx["facility"]) == ("mixed", None, "Area Control (ACC)")
