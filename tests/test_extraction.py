import csv

import pytest

from atcdb.engine import ClearToCross, ClearToLand, Handoff, HoldShort, NoOp, ReadbackObserved, RunwayVacated
from atcdb.extraction import (ALL_KINDS, FIELDS, GOLD_COLUMNS, Extraction, effect, evaluate, events_to_extractions,
                              extractions_to_row, read_sheet, row_to_extractions, score_transmission, summarize,
                              write_sheet)


def test_effect_partition():
    assert effect("LAND") == "block"
    assert effect("HOLD_SHORT") == "hold"
    assert effect("VACATED") == effect("CANCEL") == "clear"
    with pytest.raises(ValueError):
        effect("BOGUS")
    assert len(set(ALL_KINDS)) == len(ALL_KINDS)


def test_events_to_extractions_drops_readback_and_noop():
    events = [
        ClearToCross(callsign="air france one nine eight romeo", runway="13"),
        HoldShort(callsign="air france one nine eight romeo", runway="24"),
        ReadbackObserved(callsign="csa three eight whiskey", text="..."),
        NoOp(),
        Handoff(callsign="csa eight two nine", to="ground"),
        RunwayVacated(callsign="csa three eight whiskey"),
    ]
    exs = events_to_extractions(events)
    assert [e.kind for e in exs] == ["CROSS", "HOLD_SHORT", "HANDOFF", "VACATED"]
    assert exs[0].surface_type == "runway" and exs[0].surface == "13"
    assert exs[2].surface == "" and exs[2].surface_type == ""


def test_row_roundtrip_multi_event():
    exs = [Extraction("air france one nine eight romeo", "runway", "13", "CROSS"),
           Extraction("air france one nine eight romeo", "runway", "24", "HOLD_SHORT")]
    row = extractions_to_row(7, exs)
    assert row["change"] == "True" and row["kind"] == "CROSS;HOLD_SHORT"
    assert row_to_extractions(row) == exs


def test_row_parsing_normalises_and_handles_blank_and_false():
    assert row_to_extractions({"transmission_id": "1", "change": ""}) is None
    assert row_to_extractions({"transmission_id": "1", "change": "False"}) == []
    exs = row_to_extractions({"transmission_id": "1", "change": "True", "callsign": " CSA  Three  Eight Whiskey ",
                              "surface_type": "runway", "surface": "one three", "kind": "land", "conditional": "yes"})
    assert exs == [Extraction("csa three eight whiskey", "runway", "13", "LAND", True)]
    twy = row_to_extractions({"transmission_id": "2", "change": "y", "callsign": "x", "surface_type": "taxiway",
                              "surface": "taxiway alpha", "kind": "HOLD_SHORT"})
    assert twy[0].surface == "ALPHA"


def test_row_parsing_rejects_unknown_kind():
    with pytest.raises(ValueError):
        row_to_extractions({"transmission_id": "1", "change": "True", "kind": "PARK"})


def test_score_transmission_fields_and_exact():
    gold = [Extraction("csa three eight whiskey", "runway", "13", "LAND")]
    s = score_transmission("1", gold, [Extraction("csa three eight whiskey", "runway", "31", "LAND")])
    assert s.field_hits == {"callsign": 1, "surface_type": 1, "surface": 0, "kind": 1}
    assert s.exact is False
    s2 = score_transmission("1", gold, gold)
    assert s2.exact is True
    s3 = score_transmission("1", gold, [])
    assert s3.pred_change is False and s3.field_hits["kind"] == 0 and s3.field_totals["kind"] == 1


def test_unknown_gold_field_is_skipped():
    gold = [Extraction("?", "runway", "13", "LAND")]
    s = score_transmission("1", gold, [Extraction("anything", "runway", "13", "LAND")])
    assert s.field_totals["callsign"] == 0 and s.exact is True


def test_extra_prediction_breaks_exact_but_not_fields():
    gold = [Extraction("a", "runway", "13", "LAND")]
    pred = gold + [Extraction("b", "runway", "24", "CROSS")]
    s = score_transmission("1", gold, pred)
    assert s.field_hits["surface"] == 1 and s.exact is False


def test_summarize_two_scores():
    scores = [
        score_transmission("1", [Extraction("a", "runway", "13", "LAND")], [Extraction("a", "runway", "13", "LAND")]),
        score_transmission("2", [], []),
        score_transmission("3", [], [Extraction("z", "runway", "24", "TAKEOFF")]),
        score_transmission("4", [Extraction("b", "runway", "24", "CROSS")], []),
    ]
    s = summarize(scores)
    assert s["change"]["tp"] == 1 and s["change"]["fp"] == 1 and s["change"]["fn"] == 1 and s["change"]["tn"] == 1
    assert s["change"]["accuracy"] == 0.5
    assert s["content"]["n"] == 2 and s["content"]["exact_match"] == 0.5
    assert s["content"]["fields"]["kind"]["accuracy"] == 0.5
    weighted = summarize(scores, {"callsign": 0.0, "surface_type": 0.0, "surface": 1.0, "kind": 0.0})
    assert weighted["content"]["weighted"] == 0.5


def _write(path, rows):
    with path.open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=GOLD_COLUMNS, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)


def test_evaluate_end_to_end_with_sheets(tmp_path):
    gold = [
        {"transmission_id": "1", "change": "True", "callsign": "csa one two", "surface_type": "runway", "surface": "13", "kind": "LAND"},
        {"transmission_id": "2", "change": "False"},
        {"transmission_id": "3", "change": ""},   # unlabelled -> skipped
        {"transmission_id": "4", "change": "True", "callsign": "x", "surface_type": "runway", "surface": "24", "kind": "CROSS"},
    ]
    pred = [
        {"transmission_id": "1", "change": "True", "callsign": "csa one two", "surface_type": "runway", "surface": "13", "kind": "LAND"},
        {"transmission_id": "2", "change": "False"},
        {"transmission_id": "3", "change": "False"},
    ]
    _write(tmp_path / "gold.csv", gold)
    _write(tmp_path / "pred.csv", pred)
    r = evaluate(read_sheet(tmp_path / "gold.csv"), read_sheet(tmp_path / "pred.csv"), n_resamples=50)
    assert r["skipped"] == {"unlabelled": 1, "no_prediction": 1}
    assert r["change"]["n"] == 2 and r["change"]["accuracy"] == 1.0
    assert r["content"]["exact_match"] == 1.0
    lo, hi = r["change"]["accuracy_ci"]
    assert 0.0 <= lo <= hi <= 1.0


def test_write_sheet_columns(tmp_path):
    write_sheet(tmp_path / "s.csv", [{"transmission_id": "1", "change": "", "extra": "ignored"}], GOLD_COLUMNS)
    with (tmp_path / "s.csv").open() as fh:
        assert next(csv.reader(fh)) == GOLD_COLUMNS
