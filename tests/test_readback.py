from atcdb.loader import load_enriched_csv
from atcdb.readback import (build_readback_pairs, check_readback, extract_items, perturb_digit,
                            shares_callsign, split_by_recording)
from atcdb.schema import init_db


def test_extract_frequency_with_decimal():
    items = extract_items("lufthansa two five three eight contact rhein one three three decimal two eight five good bye")
    assert items == [("frequency", "one three three decimal two eight five")]


def test_extract_frequency_after_contact_without_decimal():
    items = extract_items("lufthansa five mike echo contact ground one two one nine bye")
    assert items == [("frequency", "one two one nine")]


def test_extract_level_altitude_heading_squawk_runway():
    text = ("descend flight level one hundred then climb five thousand feet heading two seven zero "
            "squawk one four zero two runway three one left")
    assert extract_items(text) == [("level", "one hundred"), ("altitude", "five thousand"), ("heading", "two seven zero"),
                                   ("squawk", "one four zero two"), ("runway", "three one left")]


def test_check_readback_exact_and_decimal_dropped_are_ok():
    items = [("frequency", "one three four decimal four four zero")]
    assert check_readback(items, "one three four four four zero wizz air five three five") == [("frequency", "one three four decimal four four zero", "ok")]
    assert check_readback(items, "one three four decimal four four zero bye") == [("frequency", "one three four decimal four four zero", "ok")]


def test_check_readback_missing_or_wrong_digit_is_flagged():
    items = [("level", "three four zero")]
    assert check_readback(items, "climbing three three zero lufthansa") == [("level", "three four zero", "missing")]
    assert check_readback(items, "roger lufthansa") == [("level", "three four zero", "missing")]


def test_shares_callsign_requires_a_common_digit_run():
    assert shares_callsign("swiss one two four descend", "descending swiss one two four")
    assert not shares_callsign("swiss one two four descend", "austrian seven seven papa roger")


def test_perturb_digit_changes_exactly_one_digit_inside_the_item():
    out = perturb_digit("one three four four four zero bye", "one three four decimal four four zero", seed=1)
    assert out != "one three four four four zero bye"
    diff = [(a, b) for a, b in zip(out.split(), "one three four four four zero bye".split()) if a != b]
    assert len(diff) == 1 and diff[0][1] in "one three four four four zero".split()


def test_build_pairs_from_fixture(tmp_path, fixture_csv):
    conn = init_db(tmp_path / "t.sqlite")
    load_enriched_csv(conn, fixture_csv, project_root=tmp_path)
    n = build_readback_pairs(conn)
    rows = conn.execute("SELECT * FROM readback_pairs ORDER BY id").fetchall()
    assert n == len(rows) == 2  # swiss (atco2 recording) and lufthansa (uwb recording)
    swiss = next(r for r in rows if "swiss" in r["instruction_text"])
    assert (swiss["same_aircraft"], swiss["rule_verdict"], swiss["n_items"], swiss["n_missing"]) == (1, "consistent", 1, 0)
    lh = next(r for r in rows if "lufthansa" in r["instruction_text"])
    assert (lh["same_aircraft"], lh["rule_verdict"], lh["clarification_cue"]) == (1, "consistent", None)


def test_build_pairs_is_idempotent(tmp_path, fixture_csv):
    conn = init_db(tmp_path / "t.sqlite")
    load_enriched_csv(conn, fixture_csv, project_root=tmp_path)
    build_readback_pairs(conn)
    build_readback_pairs(conn)
    assert conn.execute("SELECT count(*) FROM readback_pairs").fetchone()[0] == 2


def test_split_by_recording_keeps_a_recording_in_one_split():
    pairs = [{"recording_id": r, "id": i} for i, r in enumerate([1, 1, 2, 3, 3, 4, 5, 6, 7, 8])]
    splits = split_by_recording(pairs, test_fraction=0.3, seed=0)
    by_rec = {}
    for p, s in zip(pairs, splits):
        by_rec.setdefault(p["recording_id"], set()).add(s)
    assert all(len(v) == 1 for v in by_rec.values())
    assert set(splits) == {"train", "test"}


def test_make_examples_builds_balanced_labelled_pairs(tmp_path, fixture_csv):
    from atcdb.readback import make_examples
    conn = init_db(tmp_path / "t.sqlite")
    load_enriched_csv(conn, fixture_csv, project_root=tmp_path)
    build_readback_pairs(conn)
    ex = make_examples(conn, seed=0)
    # 2 consistent natural pairs -> 2 positives + 2 synthetic negatives (one perturbed digit each)
    assert sorted(e["label"] for e in ex) == [0, 0, 1, 1]
    assert {e["source"] for e in ex} == {"natural", "synthetic"}
    neg = next(e for e in ex if e["source"] == "synthetic")
    pos = next(e for e in ex if e["pair_id"] == neg["pair_id"] and e["source"] == "natural")
    assert neg["instruction"] == pos["instruction"] and neg["readback"] != pos["readback"]
    assert {"pair_id", "recording_id", "instruction", "readback", "item_kind", "item_value", "label", "source", "split"} <= set(ex[0])
    assert all(e["split"] in ("train", "test") for e in ex)


def test_sample_label_sheet_is_stratified_deterministic_and_hides_rule_verdict(tmp_path, fixture_csv):
    from atcdb.readback import sample_label_sheet
    conn = init_db(tmp_path / "t.sqlite")
    load_enriched_csv(conn, fixture_csv, project_root=tmp_path)
    build_readback_pairs(conn)
    rows = sample_label_sheet(conn, n_consistent=1, n_inconsistent=5, n_unmatched=5, seed=0)
    assert len(rows) == 1                      # fixture only has consistent same-aircraft pairs; asks beyond supply are capped
    r = rows[0]
    assert {"pair_id", "instruction", "readback", "instruction_clip", "readback_clip", "items", "human_label", "notes"} <= set(r)
    assert "rule_verdict" not in r and "n_missing" not in r
    assert r["human_label"] == "" and r["instruction_clip"].endswith(".wav")
    assert sample_label_sheet(conn, 1, 5, 5, seed=0) == rows   # deterministic


def test_extract_frequency_unit_name_cannot_swallow_digit_words():
    items = extract_items("lufthansa six lima l contact praha one three three three nine zero good bye")
    assert items == [("frequency", "one three three three nine zero")]


def test_build_pairs_rebuild_updates_items_in_place_keeping_ids(tmp_path, fixture_csv):
    conn = init_db(tmp_path / "t.sqlite")
    load_enriched_csv(conn, fixture_csv, project_root=tmp_path)
    build_readback_pairs(conn)
    ids_before = [r[0] for r in conn.execute("SELECT id FROM readback_pairs ORDER BY id")]
    conn.execute("UPDATE readback_pairs SET items_json = '[]', n_items = 0, rule_verdict = 'no_items'")
    conn.commit()
    build_readback_pairs(conn)
    ids_after = [r[0] for r in conn.execute("SELECT id FROM readback_pairs ORDER BY id")]
    assert ids_after == ids_before
    assert conn.execute("SELECT count(*) FROM readback_pairs WHERE n_items > 0").fetchone()[0] == 2


def test_the_runway_item_stays_icao_only_even_where_the_parser_reads_a_single_digit():
    """A deliberate asymmetry, pinned so it is not "fixed" by accident.

    `parse_rules.make_parser(single_digit_runways=True)` reads "runway four left" as 04L for a US tower, but this
    extractor keeps requiring two digit-words, so a runway read-back miss on a single-digit designator is not
    detected. Widening it would make the readback check see a runway item in the 110 ASR-truncated mentions
    ("runway three o") that carry no designator, changing every published readback number for a convention no
    transcript in this corpus uses. Report §7 states the limitation.
    """
    assert extract_items("cleared to land runway four left") == []
    assert extract_items("cleared to land runway zero four left") == [("runway", "zero four left")]
