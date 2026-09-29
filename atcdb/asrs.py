"""Turn an ASRS Database Online CSV export into a human triage sheet."""
import csv
from pathlib import Path

TRIAGE_COLUMNS = ["acn", "synopsis", "narrative", "space", "comm_trace", "convertible", "notes"]

SPACE_LABELS = ("runway", "taxiway", "airborne", "other")
COMM_TRACE_LABELS = ("wrong_readback", "query", "correction", "none", "cant_tell")
CONVERTIBLE_LABELS = ("yes", "no")


def _find(fieldnames: list[str], *needles: str) -> str | None:
    for name in fieldnames:
        low = name.lower()
        if all(n in low for n in needles):
            return name
    return None


def read_asrs_export(path: Path) -> list[dict[str, str]]:
    """Read an ASRS export. The online tool writes a group-header row above the field names;
    skip leading rows until one contains an ACN column."""
    with Path(path).open(newline="", encoding="utf-8-sig") as fh:
        rows = list(csv.reader(fh))
    for i, row in enumerate(rows):
        if any(c.strip().lower() == "acn" for c in row):
            header = [c.strip() for c in row]
            return [dict(zip(header, r)) for r in rows[i + 1 :] if any(r)]
    raise ValueError(f"{path}: no ACN column found")


def triage_rows(records: list[dict[str, str]]) -> list[dict[str, str]]:
    if not records:
        return []
    fields = list(records[0].keys())
    acn = _find(fields, "acn")
    synopsis = _find(fields, "synopsis")
    narrative = _find(fields, "narrative")
    out = []
    for r in records:
        out.append({
            "acn": r.get(acn, "") if acn else "",
            "synopsis": r.get(synopsis, "") if synopsis else "",
            "narrative": r.get(narrative, "") if narrative else "",
            "space": "", "comm_trace": "", "convertible": "", "notes": "",
        })
    return out


def write_sheets(rows: list[dict[str, str]], out_dir: Path, overlap: int, stem: str = "asrs_triage") -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    written = []
    for name, subset in (("A", rows), ("B", rows[:overlap])):
        path = out_dir / f"{stem}_{name}.csv"
        with path.open("w", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=TRIAGE_COLUMNS)
            w.writeheader()
            w.writerows(subset)
        written.append(path)
    return written
