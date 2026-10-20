"""Real incidents replayed through the rules parser and the engine (spec addendum A.3.9).

Austin is NTSB public record and is committed as a fixture. Recording 528 comes from the UWB-ATCC corpus (CC BY-NC-ND),
which is not redistributed, so its test reads the local corpus DB read-only and skips without it. Both pin the frozen
rules-parser baseline (parse_rules v1, spec addendum A.7): these are findings the evaluation reports, not bugs to fix.
"""
import contextlib
import sqlite3
from pathlib import Path

import pytest

from atcdb import parse_rules
from atcdb.engine import Conflict, State, apply
from atcdb.incidents import load_ntsb_transcript
from atcdb.parsing import Transmission
from atcdb.replay import build_context, load_recording

FIXTURES = Path(__file__).parent / "fixtures"
CORPUS = Path(__file__).resolve().parents[1] / "data" / "atc.sqlite"


def fold_rules(txs: list[Transmission]) -> list[tuple[list[Conflict], int]]:
    """Per transmission: the conflicts it raised and the instructions the rules parser dropped, in `window` mode."""
    state, out = State(), []
    for k, tx in enumerate(txs):
        ctx = build_context("window", tx, txs[:k], state)
        conflicts = []
        for e in parse_rules.parse(tx, ctx):
            state, new = apply(state, e)
            conflicts.extend(new)
        out.append((conflicts, parse_rules.count_unresolved(tx, ctx)))
    return out


def test_austin_fixture_is_the_full_on_frequency_transcript():
    rows = load_ntsb_transcript(FIXTURES / "austin_dca23fa149.txt")
    assert len(rows) == 89   # 94 NTSB lines less 5 intrafacility
    assert (rows[0][0], rows[-1][0]) == ("0547:52", "0642:14")


def test_austin_rules_baseline():
    rows = load_ntsb_transcript(FIXTURES / "austin_dca23fa149.txt")
    at = {hhmm: i for i, (hhmm, _) in enumerate(rows)}
    result = fold_rules([tx for _, tx in rows])
    runway = [(hhmm, c) for (hhmm, _), (cs, _) in zip(rows, result) for c in cs if c.type == "RUNWAY" and c.runway == "18L"]
    # The engine models the incident: a RUNWAY conflict on 18L between FedEx's landing and Southwest's takeoff.
    assert any("southwest seven zero eight" in c.callsigns for _, c in runway)
    # v1 findings (spec addendum A.2): the 0634:14 landing clearance has no "runway" token and is dropped ...
    assert result[at["0634:14"]] == ([], 1)
    # ... so nothing fires at 0638:58, when the conflicting takeoff clearance is issued ...
    assert result[at["0638:58"]][0] == []
    # ... and the conflict fires at the 0639:34 re-confirmation instead, capped at warning by the unparsed US callsign.
    hhmm, c = runway[-1]
    assert (hhmm, c.severity, c.callsigns, c.basis) == ("0639:34", "warning", ("", "southwest seven zero eight"),
                                                        "icao-4444-7.10.1")


@pytest.mark.skipif(not CORPUS.exists(), reason="corpus DB not present (UWB-ATCC is not redistributed)")
def test_recording_528_keeps_its_known_false_alert():
    # Air France 198R is cleared to cross 13, then CSA 38W is cleared to land 13. The crossing is complete (Air France is
    # next told to hold short of 24) but nobody says so on frequency. Extraction is correct; the release is not in the audio.
    with contextlib.closing(sqlite3.connect(f"file:{CORPUS}?mode=ro", uri=True)) as conn:
        conn.row_factory = sqlite3.Row
        txs = load_recording(conn, 528, "gold", "human")
        result = fold_rules(txs)
        raised = [(k + 1, c.type, c.severity, c.runway, c.callsigns) for k, (cs, _) in enumerate(result) for c in cs if c.type == "RUNWAY"]
        assert raised == [(17, "RUNWAY", "alert", "13", ("csa three eight whiskey", "air france one nine eight romeo"))]
