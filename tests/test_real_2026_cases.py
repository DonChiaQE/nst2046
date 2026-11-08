"""The two 2026 real-incident reconstructions, and the §4.5 claim they carry.

The report claims that neither incident produces a runway reservation under any extractor, so no alert can be
raised whatever reads the text. That claim is load-bearing — it is what makes the two cases evidence about the
*framing* rather than about either parser — so it is asserted here rather than left to a script's output. If a
parser change ever puts a reservation on these transmissions, this fails and the report needs rewriting.

The record/load roundtrip is tested with a stub parser so the paid path is exercised without a key or a bill.
"""
import json

import pytest

from atcdb import parse_llm, parse_rules
from atcdb.engine import RESERVATION_KINDS, ClearTakeoff, HoldShort
from atcdb.incidents import fold_window as fold
from atcdb.parsing import KINDS
from scripts.real_2026_cases import (
    PROVENANCE_API, PROVENANCE_TRANSCRIBED, SHEET, cases, derive, drift, load_recorded,
    record, recording_path, reservations_in, show,
)


@pytest.fixture
def by_case():
    return cases(SHEET)


def test_the_sheet_holds_both_reconstructed_incidents(by_case):
    assert set(by_case) == {"goa-2026-04-03", "houston-2026-04-24"}
    assert sum(len(v) for v in by_case.values()) == 7


def test_neither_2026_incident_yields_a_runway_reservation_under_the_rules_parser(by_case):
    """§4.5: the engine knows four reservation kinds and none of these transmissions maps to any of them."""
    for case, txs in by_case.items():
        kinds = [KINDS[type(e)] for _, events, _ in fold(txs, parse_rules.parse) for e in events]
        assert not set(kinds) & set(RESERVATION_KINDS), f"{case} produced a reservation: {kinds}"


def test_no_conflict_is_raised_on_either_case(by_case):
    for case, txs in by_case.items():
        conflicts = [c for _, _, cs in fold(txs, parse_rules.parse) for c in cs]
        assert conflicts == [], f"{case} raised {conflicts}"


def test_the_committed_sonnet_recording_also_yields_no_reservation():
    """Guards the claim for the arm that costs money: the recording is what the report cites."""
    data = load_recorded("claude-sonnet-5")
    if data is None:
        pytest.skip("claude-sonnet-5 not recorded yet (scripts/real_2026_cases.py --record)")
    for case, rows in data["cases"].items():
        bad = [e for row in rows for e in row["events"] if e["kind"] in RESERVATION_KINDS]
        assert not bad, f"{case} produced a reservation under Sonnet 5: {bad}"


def test_a_recording_round_trips_without_a_key(tmp_path, monkeypatch, by_case):
    """record() must write what load_recorded() reads, so the keyless path reproduces the paid one."""
    monkeypatch.setattr("scripts.real_2026_cases.RECORDED", tmp_path)
    monkeypatch.setattr(parse_llm, "make_parser", lambda model: lambda tx, ctx: [])
    written = record("claude-sonnet-5", by_case)
    assert recording_path("claude-sonnet-5").exists()
    assert json.loads(recording_path("claude-sonnet-5").read_text()) == written
    assert set(written["cases"]) == set(by_case)
    assert written["parse_version"] == parse_llm.VERSION


def test_a_recording_made_under_an_older_prompt_is_flagged(tmp_path, monkeypatch, capsys, by_case):
    """The report cites these events, so a silent prompt change must not pass unnoticed."""
    monkeypatch.setattr("scripts.real_2026_cases.RECORDED", tmp_path)
    monkeypatch.setattr(parse_llm, "make_parser", lambda model: lambda tx, ctx: [])
    record("claude-sonnet-5", by_case)
    stale = json.loads(recording_path("claude-sonnet-5").read_text())
    stale["parse_version"] = "p0"
    recording_path("claude-sonnet-5").write_text(json.dumps(stale))

    load_recorded("claude-sonnet-5")
    assert "re-record before citing it" in capsys.readouterr().out


def test_an_unrecorded_model_loads_as_none(tmp_path, monkeypatch):
    monkeypatch.setattr("scripts.real_2026_cases.RECORDED", tmp_path)
    assert load_recorded("claude-sonnet-5") is None


def test_show_counts_reservations_so_the_summary_can_fail_loudly(capsys):
    """`show` is what the §4.5 summary line reads; a reservation must raise its count."""
    rows = [{"role": "controller", "text": "csa one cleared for takeoff runway one three",
             "events": [{"kind": "TAKEOFF", "callsign": "csa one", "runway": "13", "to": None}],
             "conflicts": []}]
    assert show("stub", rows) == 1
    assert "TAKEOFF 13 [csa one]" in capsys.readouterr().out


def test_show_renders_a_handoffs_destination_rather_than_a_runway(capsys):
    """The rules parser reads the Goa handoff's frequency into the callsign field; the table must show it."""
    rows = [{"role": "controller", "text": "contact navy approach one one niner decimal seven",
             "events": [{"kind": "HANDOFF", "callsign": "one one niner", "runway": None, "to": "approach"}],
             "conflicts": []}]
    assert show("stub", rows) == 0
    assert "HANDOFF approach [one one niner]" in capsys.readouterr().out


def test_the_rules_parser_reads_the_goa_frequency_as_a_callsign(by_case):
    """A real extraction error on real text, reported in §4.5: `one one niner` is a frequency, not an aircraft."""
    handoffs = [e for _, events, _ in fold(by_case["goa-2026-04-03"], parse_rules.parse)
                for e in events if type(e).__name__ == "Handoff"]
    assert [e.callsign for e in handoffs] == ["one one niner"]


def test_takeoff_is_one_of_the_kinds_the_claim_is_about():
    """Pins the vocabulary the §4.5 argument names, so renaming a kind cannot quietly void the test above."""
    assert KINDS[ClearTakeoff] == "TAKEOFF"
    assert set(RESERVATION_KINDS) == {"LAND", "TAKEOFF", "LUAW", "CROSS"}


# --- verification: the recording has to be a falsifiable claim, not hardcoded data -----------------

def _fake_parser(events_by_text):
    """A stand-in for the Claude parser: returns the given events for a matching transmission, else nothing."""
    def parse(tx, ctx):
        return events_by_text.get(tx.text, [])
    return lambda model: parse


def test_a_fresh_derivation_matching_the_recording_shows_no_drift(tmp_path, monkeypatch, by_case):
    monkeypatch.setattr("scripts.real_2026_cases.RECORDED", tmp_path)
    monkeypatch.setattr(parse_llm, "make_parser", _fake_parser({}))
    recorded = record("claude-sonnet-5", by_case)
    assert drift(recorded, derive("claude-sonnet-5", by_case)) == []


def test_drift_names_the_case_and_row_that_changed(tmp_path, monkeypatch, by_case):
    """A changed reply must be reported per row, so a refresh is an informed decision rather than a blind rewrite."""
    monkeypatch.setattr("scripts.real_2026_cases.RECORDED", tmp_path)
    monkeypatch.setattr(parse_llm, "make_parser", _fake_parser({}))
    recorded = record("claude-sonnet-5", by_case)

    backtrack = "expect backtrack"
    monkeypatch.setattr(parse_llm, "make_parser",
                        _fake_parser({backtrack: [HoldShort(callsign="", runway="08")]}))
    lines = drift(recorded, derive("claude-sonnet-5", by_case))
    assert len(lines) == 1
    assert "goa-2026-04-03 row 4" in lines[0] and "HOLD_SHORT 08" in lines[0]


def test_drift_reports_a_recording_with_a_different_number_of_rows(by_case):
    recorded = {"cases": {"goa-2026-04-03": [{"text": "x", "role": "controller", "events": []}]}}
    fresh = {"cases": {"goa-2026-04-03": []}}
    assert drift(recorded, fresh) == ["goa-2026-04-03: 1 rows recorded, 0 derived"]


def test_an_invented_takeoff_breaches_the_invariant_the_report_cites(by_case):
    """This is the failure --verify exists to catch: a model inventing the clearance §4.5 says nobody issued."""
    fresh = {"cases": {"goa-2026-04-03": [
        {"text": "expect backtrack", "role": "controller",
         "events": [{"kind": "TAKEOFF", "callsign": "vt bxl", "runway": "08", "to": None}]}]}}
    found = reservations_in(fresh)
    assert [e["kind"] for _, e in found] == ["TAKEOFF"]


def test_a_hold_short_is_not_a_reservation_so_sonnets_real_output_passes():
    """Sonnet's HOLD_SHORT 08 is the correct reading and holds no runway, so it must not trip the invariant."""
    fresh = {"cases": {"goa-2026-04-03": [
        {"text": "taxi via november two hold at holding point runway zero eight", "role": "controller",
         "events": [{"kind": "HOLD_SHORT", "callsign": "", "runway": "08", "to": None}]}]}}
    assert reservations_in(fresh) == []


# --- provenance: a hand-seeded recording must never pass as an API-written one --------------------

def test_the_committed_sonnet_recording_is_complete_and_matches_the_sheet():
    """Whatever its provenance, the recording must line up with the sheet row for row."""
    data = load_recorded("claude-sonnet-5")
    assert data is not None, "the Sonnet recording should be committed"
    sheet = cases(SHEET)
    assert set(data["cases"]) == set(sheet)
    for case, rows in data["cases"].items():
        assert [r["text"] for r in rows] == [tx.text for tx in sheet[case]]
        assert [r["role"] for r in rows] == [tx.role for tx in sheet[case]]


def test_derive_always_marks_its_output_as_api_written(tmp_path, monkeypatch, by_case):
    monkeypatch.setattr(parse_llm, "make_parser", lambda model: lambda tx, ctx: [])
    assert derive("claude-sonnet-5", by_case)["provenance"] == PROVENANCE_API


def test_a_transcribed_recording_is_announced_as_such(capsys):
    """The committed Sonnet events are real output read back from a pasted run, so anything citing them has to be
    able to tell. `--record` is what replaces it with an API-written one."""
    data = load_recorded("claude-sonnet-5")
    out = capsys.readouterr().out
    if data["provenance"] == PROVENANCE_TRANSCRIBED:
        assert "transcribed" in out and "--record" in out
    else:
        assert data["provenance"] == PROVENANCE_API and out == ""


def test_recording_marks_provenance_api_once_rewritten_from_the_api(tmp_path, monkeypatch, by_case, capsys):
    """After a real --record the warning must stop, so the flag cannot become background noise."""
    monkeypatch.setattr("scripts.real_2026_cases.RECORDED", tmp_path)
    monkeypatch.setattr(parse_llm, "make_parser", lambda model: lambda tx, ctx: [])
    record("claude-sonnet-5", by_case)
    capsys.readouterr()
    assert load_recorded("claude-sonnet-5")["provenance"] == PROVENANCE_API
    assert "transcribed" not in capsys.readouterr().out


# --- the §4.5 summary guard ----------------------------------------------------------------------------------------

def test_the_summary_claims_no_alert_is_possible_only_when_every_arm_produced_nothing():
    from scripts.real_2026_cases import summary_lines
    lines = "\n".join(summary_lines({("goa", "rules"): 0, ("houston", "rules"): 0}))
    assert "Every arm produces 0 runway reservations" in lines
    assert "no longer holds" not in lines


def test_one_reservation_is_enough_to_withdraw_the_claim():
    """The earlier version asserted the claim unconditionally and warned only at two or more, so a single
    reservation printed a false statement with no warning beside it."""
    from scripts.real_2026_cases import summary_lines
    lines = "\n".join(summary_lines({("goa", "rules"): 0, ("houston", "rules"): 1}))
    assert "Every arm produces 0 runway reservations" not in lines
    assert "produced 1 runway reservation(s)" in lines
    assert "max reservations in any arm: 1" in lines
