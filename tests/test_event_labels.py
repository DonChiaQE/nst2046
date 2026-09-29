import pytest

from atcdb.engine import ClearToLand, GoAround, Handoff, HoldShort, ReadbackObserved, RunwayVacated
from atcdb.event_labels import COLUMNS, parse_event_cell, sample_event_sheet
from atcdb.schema import init_db


def _seed(conn, turns, external_id="r1"):
    """One tower recording; `turns` = [(role, text, split), ...] at 10 s spacing, gold transcripts by 'human'."""
    conn.execute("INSERT OR IGNORE INTO sources (id, name, kind) VALUES (1, 'test', 'corpus')")
    rid = conn.execute("INSERT INTO recordings (source_id, external_id, facility) VALUES (1, ?, 'Tower')",
                       (external_id,)).lastrowid
    for i, (role, text, split) in enumerate(turns):
        xid = conn.execute(
            """INSERT INTO transmissions (recording_id, external_id, start_s, end_s, speaker_role, split, clip_path)
               VALUES (?, ?, ?, ?, ?, ?, ?)""", (rid, f"x{i}", 10.0 * i, 10.0 * i + 3, role, split, f"clips/{external_id}-{i}.wav")).lastrowid
        conn.execute("INSERT INTO transcripts (transmission_id, kind, model, raw_text, normalized_text) VALUES (?, 'gold', 'human', ?, ?)",
                     (xid, text, text))
    conn.commit()
    return rid


TURNS = [
    ("controller", "csa one two three runway three one cleared to land", "train"),
    ("pilot", "cleared to land three one csa one two three", "test"),
    ("controller", "lufthansa four five six hold short runway three one", "test"),
    ("pilot", "holding short lufthansa four five six", "train"),
    ("controller", "csa one two three contact ground one two one nine", "test"),
]


def test_the_sheet_samples_only_test_split_transmissions_with_their_context(tmp_path):
    conn = init_db(tmp_path / "t.sqlite")
    _seed(conn, TURNS)
    rows = sample_event_sheet(conn, n=10, seed=0)
    assert sorted(r["text"] for r in rows) == sorted(t for _, t, split in TURNS if split == "test")
    assert [r["row_id"] for r in rows] == [1, 2, 3]
    third = next(r for r in rows if r["text"] == TURNS[2][1])
    assert third["context"] == f"[controller] {TURNS[0][1]}\n[pilot] {TURNS[1][1]}"
    assert third["role"] == "controller" and third["clip_path"] == "clips/r1-2.wav"
    assert (third["events"], third["notes"]) == ("", "")
    assert list(third) == COLUMNS


def test_the_sheet_is_seeded_and_capped_at_n(tmp_path):
    conn = init_db(tmp_path / "t.sqlite")
    _seed(conn, TURNS)
    _seed(conn, TURNS, external_id="r2")
    first = sample_event_sheet(conn, n=4, seed=1)
    assert len(first) == 4
    assert first == sample_event_sheet(conn, n=4, seed=1)
    assert [r["transmission_id"] for r in first] != [r["transmission_id"] for r in sample_event_sheet(conn, n=4, seed=2)]


def test_the_sheet_carries_no_parser_output(tmp_path):
    conn = init_db(tmp_path / "t.sqlite")
    _seed(conn, TURNS)
    assert not {"kind", "parser", "rule", "predicted", "llm"} & set(COLUMNS)


def test_parse_event_cell_reads_every_kind():
    cell = ("land 31 csa one two three\nhold_short 4L lufthansa four five six\nhandoff ground csa one two three\n"
            "vacated csa one two three\ngo_around\nreadback lufthansa four five six")
    assert parse_event_cell(cell) == [
        ClearToLand(runway="31", callsign="csa one two three"),
        HoldShort(runway="04L", callsign="lufthansa four five six"),
        Handoff(to="ground", callsign="csa one two three"),
        RunwayVacated(callsign="csa one two three"),
        GoAround(callsign=""),
        ReadbackObserved(callsign="lufthansa four five six", text=""),
    ]
    assert parse_event_cell(" NOOP \n") == []


@pytest.mark.parametrize("cell, message", [
    ("", "empty cell"),
    ("land csa one two three", "needs a runway"),
    ("cross 99 csa", "needs a runway"),
    ("handoff tower_two csa", "needs a target"),
    ("taxi 31 csa", "unknown kind"),
    ("land 31 csa\nnoop", "only line"),
])
def test_parse_event_cell_rejects_bad_cells(cell, message):
    with pytest.raises(ValueError, match=message):
        parse_event_cell(cell)
