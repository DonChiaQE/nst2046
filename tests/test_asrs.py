import csv

from atcdb.asrs import TRIAGE_COLUMNS, read_asrs_export, triage_rows, write_sheets


def _write_export(path, with_group_header=True):
    with path.open("w", newline="") as fh:
        w = csv.writer(fh)
        if with_group_header:
            w.writerow(["", "Report 1", "Report 1", ""])
        w.writerow(["ACN", "Report 1.Narrative", "Report 1.Synopsis", "Date"])
        w.writerow(["1234567", "Tower cleared us to cross 31L while ...", "Runway incursion after crossing clearance", "202301"])
        w.writerow(["1234568", "We were told to hold short ...", "Hold short readback error", "202302"])


def test_read_export_skips_group_header(tmp_path):
    p = tmp_path / "export.csv"
    _write_export(p)
    recs = read_asrs_export(p)
    assert [r["ACN"] for r in recs] == ["1234567", "1234568"]


def test_read_export_without_group_header(tmp_path):
    p = tmp_path / "export.csv"
    _write_export(p, with_group_header=False)
    assert len(read_asrs_export(p)) == 2


def test_triage_rows_maps_columns_and_leaves_labels_blank(tmp_path):
    p = tmp_path / "export.csv"
    _write_export(p)
    rows = triage_rows(read_asrs_export(p))
    assert rows[0]["acn"] == "1234567"
    assert rows[0]["synopsis"].startswith("Runway incursion")
    assert rows[0]["narrative"].startswith("Tower cleared")
    assert rows[0]["space"] == rows[0]["comm_trace"] == rows[0]["convertible"] == ""


def test_write_sheets_overlap(tmp_path):
    p = tmp_path / "export.csv"
    _write_export(p)
    rows = triage_rows(read_asrs_export(p))
    a, b = write_sheets(rows, tmp_path / "labels", overlap=1)
    with a.open() as fh:
        ra = list(csv.DictReader(fh))
    with b.open() as fh:
        rb = list(csv.DictReader(fh))
    assert list(ra[0].keys()) == TRIAGE_COLUMNS
    assert len(ra) == 2 and len(rb) == 1
    assert rb[0]["acn"] == ra[0]["acn"]
