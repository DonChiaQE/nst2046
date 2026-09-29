import csv

import pytest

from atcdb.agreement import cohen_kappa, paired_labels, agreement_report


def test_kappa_perfect_agreement():
    assert cohen_kappa(["a", "b", "a", "b"], ["a", "b", "a", "b"]) == pytest.approx(1.0)


def test_kappa_chance_level_is_zero():
    # each rater says "a" half the time, independently of the other -> kappa 0
    a = ["a", "a", "b", "b"]
    b = ["a", "b", "a", "b"]
    assert cohen_kappa(a, b) == pytest.approx(0.0)


def test_kappa_known_value():
    # classic textbook example: po = 0.7, pe = 0.5 -> kappa 0.4
    a = ["y"] * 5 + ["n"] * 5
    b = ["y"] * 3 + ["n"] * 2 + ["n"] * 4 + ["y"]
    assert cohen_kappa(a, b) == pytest.approx(0.4)


def test_kappa_rejects_length_mismatch():
    with pytest.raises(ValueError):
        cohen_kappa(["a"], ["a", "b"])


def test_paired_labels_joins_on_key_and_skips_blanks(tmp_path):
    sheet_a = tmp_path / "A.csv"
    sheet_b = tmp_path / "B.csv"
    rows_a = [{"id": "1", "label": "x"}, {"id": "2", "label": "y"}, {"id": "3", "label": ""}, {"id": "4", "label": "x"}]
    rows_b = [{"id": "2", "label": "y"}, {"id": "1", "label": "z"}, {"id": "3", "label": "x"}]
    for path, rows in ((sheet_a, rows_a), (sheet_b, rows_b)):
        with path.open("w", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=["id", "label"])
            w.writeheader()
            w.writerows(rows)
    a, b = paired_labels(sheet_a, sheet_b, key="id", column="label")
    # id 3 is blank in A, id 4 missing from B -> only ids 1 and 2 remain, in A's order
    assert a == ["x", "y"]
    assert b == ["z", "y"]


def test_agreement_report_per_column(tmp_path):
    sheet_a = tmp_path / "A.csv"
    sheet_b = tmp_path / "B.csv"
    fields = ["id", "space", "trace"]
    rows_a = [{"id": "1", "space": "runway", "trace": "yes"}, {"id": "2", "space": "taxiway", "trace": "no"}]
    rows_b = [{"id": "1", "space": "runway", "trace": "no"}, {"id": "2", "space": "taxiway", "trace": "yes"}]
    for path, rows in ((sheet_a, rows_a), (sheet_b, rows_b)):
        with path.open("w", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=fields)
            w.writeheader()
            w.writerows(rows)
    report = agreement_report(sheet_a, sheet_b, key="id", columns=["space", "trace"])
    assert report["space"]["n"] == 2
    assert report["space"]["kappa"] == pytest.approx(1.0)
    assert report["trace"]["n"] == 2
    assert report["trace"]["kappa"] == pytest.approx(-1.0)
