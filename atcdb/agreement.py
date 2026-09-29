"""Inter-rater agreement for the human labelling sheets."""
import csv
from collections import Counter
from pathlib import Path


def cohen_kappa(a: list[str], b: list[str]) -> float:
    """Cohen's kappa between two raters' labels over the same items.

    Re-exported from `atcdb.evaluate`, which is the single implementation: the adjudication sheets
    (spec 2026-09-29, section 6) and the labelling sheets (docs/labelling-protocol.md) must agree on
    what kappa means. Raises ValueError on lists of different length or on empty input; returns 1.0
    when both raters used a single identical label everywhere.
    """
    from atcdb.evaluate import cohen_kappa as _kappa   # local: keeps this module free of the eval runner's imports
    return _kappa(a, b)


def _read(path: Path) -> list[dict[str, str]]:
    with Path(path).open(newline="") as fh:
        return list(csv.DictReader(fh))


def paired_labels(sheet_a: Path, sheet_b: Path, key: str, column: str) -> tuple[list[str], list[str]]:
    """Labels for `column` from both sheets, joined on `key`, in sheet A's order.

    Rows are dropped when the key is missing from either sheet or the label is blank in either.
    """
    by_key_b = {r[key]: r[column].strip() for r in _read(sheet_b)}
    a, b = [], []
    for r in _read(sheet_a):
        la = r[column].strip()
        lb = by_key_b.get(r[key], "")
        if la and lb:
            a.append(la)
            b.append(lb)
    return a, b


def agreement_report(sheet_a: Path, sheet_b: Path, key: str, columns: list[str]) -> dict[str, dict]:
    report = {}
    for col in columns:
        a, b = paired_labels(sheet_a, sheet_b, key, col)
        report[col] = {
            "n": len(a),
            "kappa": cohen_kappa(a, b) if a else float("nan"),
            "raw_agreement": sum(x == y for x, y in zip(a, b)) / len(a) if a else float("nan"),
            "labels_a": dict(Counter(a)),
            "labels_b": dict(Counter(b)),
        }
    return report
