import json
from pathlib import Path

import pytest

from atcdb.inject import (EDIT_KINDS, SPLICE_GAP_S, Injection, apply_check, candidates, check_rows, generate, missing_asr,
                          pool, scan, select, splice_anchor, splice_candidate, synthetic_recordings, write_injection)
from atcdb.parsing import Transmission
from atcdb.replay import build_timeline, default_transcript_model, load_recording
from atcdb.schema import init_db

DB = Path(__file__).resolve().parents[1] / "data/atc.sqlite"


def _txs(*turns):
    return [Transmission(id=i + 1, transcript_id=i + 1, text=text, role=role, start_s=10.0 * i)
            for i, (role, text) in enumerate(turns)]


def _seed(conn, turns, external_id="r1", asr=False, airport="LKPR"):
    """One tower recording with human gold transcripts (and, with `asr`, a Whisper transcript of each). Returns its id."""
    conn.execute("INSERT OR IGNORE INTO sources (id, name, kind) VALUES (1, 'test', 'corpus')")
    rid = conn.execute("INSERT INTO recordings (source_id, external_id, facility, airport_icao) VALUES (1, ?, 'Tower', ?)",
                       (external_id, airport)).lastrowid
    for i, (role, text) in enumerate(turns):
        xid = conn.execute(
            """INSERT INTO transmissions (recording_id, external_id, start_s, end_s, speaker_role, clip_path, pcm_sha1, split)
               VALUES (?, ?, ?, ?, ?, ?, ?, 'test')""",
            (rid, f"x{i}", 10.0 * i, 10.0 * i + 3, role, f"clips/{external_id}-{i}.wav", f"sha-{external_id}-{i}")).lastrowid
        conn.execute("INSERT INTO transcripts (transmission_id, kind, model, raw_text, normalized_text) VALUES (?, 'gold', 'human', ?, ?)",
                     (xid, text, text))
        if asr:
            conn.execute("""INSERT INTO transcripts (transmission_id, kind, model, model_version, raw_text, normalized_text)
                            VALUES (?, 'asr', 'whisper', 'v', ?, ?)""", (xid, f"asr {text}", f"asr {text}"))
    conn.commit()
    return rid


LAND_31 = ("controller", "csa one two three runway three one cleared to land wind calm")
LINEUP_13 = ("controller", "lufthansa four five six line up runway one three")
LINEUP_31 = ("controller", "lufthansa four five six line up runway three one")
# another strip: 13 is the other end of 31, so a swap from 13 would inject nothing (one strip is one runway)
LINEUP_22 = ("controller", "lufthansa four five six line up runway two two")
HOLD_13 = ("controller", "lufthansa four five six hold short of runway one three")
TO_31 = ("controller", "lufthansa four five six runway three one cleared for takeoff")
GROUND = ("controller", "csa one two three contact ruzyne ground one two one nine")
READBACK = ("pilot", "cleared to land runway three one csa one two three")


def test_scan_finds_clearances_hold_shorts_and_releases():
    sites = scan(_txs(LAND_31, READBACK, LINEUP_13, HOLD_13, GROUND,
                      ("controller", "jet one line up runway three one cleared for takeoff"),
                      ("controller", "fedex one four heavy one eight left cleared to land"),
                      ("pilot", "runway vacated csa one two three")))
    assert [(s.index, s.kind, s.runway) for s in sites] == [
        (0, "LAND", "31"), (2, "LUAW", "13"), (3, "HOLD_SHORT", "13"), (4, "RELEASE", None),
        (5, "TAKEOFF", "31"), (6, "LAND", "18L"), (7, "RELEASE", None)]
    assert sites[0].words == "three one" and sites[2].released == ()
    assert sites[3].released == ("LAND", "CROSS") and sites[6].released == ("LAND", "TAKEOFF", "LUAW", "CROSS")


def test_a_repeated_clearance_in_one_transmission_is_one_site():
    sites = scan(_txs(("mixed", "air france one nine eight cross runway one three cross runway one three")))
    assert [(s.index, s.kind, s.runway) for s in sites] == [(0, "CROSS", "13")]


def test_scan_ignores_pilot_clearances_and_bare_numbers_without_a_side():
    assert scan(_txs(READBACK, ("controller", "csa one two three cleared to land"))) == []


def test_runway_swap_moves_a_later_clearance_onto_the_anchor_runway():
    txs = _txs(LAND_31, READBACK, LINEUP_22)
    [inj] = [c for c in candidates(7, txs) if c.edit_kind == "runway_swap"]
    assert inj == Injection(7, "runway_swap", 0, 2, "31", "lufthansa four five six line up runway three one")


def test_holdshort_to_cross_turns_a_hold_short_into_a_crossing_of_the_anchor_runway():
    txs = _txs(LAND_31, HOLD_13)
    [inj] = [c for c in candidates(7, txs) if c.edit_kind == "holdshort_to_cross"]
    assert inj.after == "lufthansa four five six cross runway three one" and (inj.anchor, inj.trigger) == (0, 1)


def test_verb_upgrade_turns_a_line_up_behind_a_landing_into_a_takeoff():
    txs = _txs(LAND_31, LINEUP_31, ("controller", "jet two line up and wait runway three one"))
    ups = [c for c in candidates(7, txs) if c.edit_kind == "verb_upgrade"]
    assert [(c.trigger, c.after, c.runway) for c in ups] == [
        (1, "lufthansa four five six cleared for takeoff runway three one", "31"),
        (2, "jet two cleared for takeoff runway three one", "31")]


def test_release_delete_removes_the_one_release_before_a_conflicting_clearance():
    txs = _txs(LAND_31, GROUND, TO_31)
    kinds = [c.edit_kind for c in candidates(7, txs)]
    [inj] = [c for c in candidates(7, txs) if c.edit_kind == "release_delete"]
    assert (inj.anchor, inj.deleted, inj.trigger, inj.after) == (0, 1, 2, TO_31[1])
    assert "runway_swap" not in kinds   # the takeoff is already on 31


def test_the_runway_is_the_one_closest_to_the_verb():
    [site] = scan(_txs(("controller", "klm one you can use runway two two and line up runway three one")))
    assert (site.kind, site.runway) == ("LUAW", "31")


def test_a_release_between_anchor_and_trigger_blocks_the_edits():
    txs = _txs(LAND_31, GROUND, LINEUP_13)
    assert [c.edit_kind for c in candidates(7, txs)] == []


def test_no_candidate_means_no_injection():
    assert candidates(7, _txs(READBACK, GROUND)) == []
    assert select([], 10, seed=0) == []


def test_select_is_seeded_stratified_and_takes_one_per_recording_and_kind():
    pool = [Injection(r, k, 0, 1, "31", f"{r}{k}{i}") for r in range(6) for k in EDIT_KINDS[:2] for i in range(2)]
    chosen = select(pool, 5, seed=0)
    assert len(chosen) == 5 and chosen == select(pool, 5, seed=0)
    assert [c.edit_kind for c in chosen] == ["runway_swap", "holdshort_to_cross"] * 2 + ["runway_swap"]
    assert len({(c.recording_id, c.edit_kind) for c in chosen}) == 5
    assert len(select(pool, 100, seed=0)) == 12   # six recordings x two kinds, one each
    assert select(pool, 5, seed=0) != select(pool, 5, seed=1)


def test_a_stored_injection_differs_from_its_original_only_at_the_trigger(tmp_path):
    conn = init_db(tmp_path / "t.sqlite")
    rid = _seed(conn, [LAND_31, READBACK, LINEUP_22, ("pilot", "lining up two two lufthansa four five six")], asr=True)
    [inj] = [c for c in generate(conn, [rid], n=10, seed=3) if c.edit_kind == "runway_swap"]
    sid = write_injection(conn, inj, seed=3, ordinal=0)
    assert write_injection(conn, inj, seed=3, ordinal=0) == sid   # idempotent
    rec = conn.execute("SELECT r.*, s.name FROM recordings r JOIN sources s ON s.id = r.source_id WHERE r.id = ?", (sid,)).fetchone()
    assert (rec["name"], rec["external_id"], rec["facility"], rec["airport_icao"]) == ("synthetic-conflicts", f"{rid}-runway_swap-3-0", "Tower", "LKPR")
    assert default_transcript_model(conn, "gold", sid) == "synthetic"
    orig, synth = load_recording(conn, rid), load_recording(conn, sid, "gold", "synthetic")
    assert [t.text for t in synth] == [t.text for t in orig[:2]] + [inj.after] + [orig[3].text]
    assert [(t.role, t.start_s) for t in synth] == [(t.role, t.start_s) for t in orig]
    xs = conn.execute("SELECT clip_path, pcm_sha1, split FROM transmissions WHERE recording_id = ? ORDER BY start_s", (sid,)).fetchall()
    assert [tuple(x) for x in xs] == [(f"clips/r1-{i}.wav", None, "test") for i in range(4)]
    asr = load_recording(conn, sid, "asr", "whisper")
    assert [t.text for t in asr] == [f"asr {t.text}" for t in orig[:2]] + [inj.after] + [f"asr {orig[3].text}"]
    edited = conn.execute("SELECT model_version FROM transcripts WHERE id = ?", (asr[2].transcript_id,)).fetchone()[0]
    assert edited == "synthetic"
    [meta] = synthetic_recordings(conn)
    assert (meta["recording_id"], meta["edit_kind"], meta["runway"], meta["before"], meta["after"]) == (
        sid, "runway_swap", "31", LINEUP_22[1], inj.after)
    assert (meta["anchor_tx"], meta["trigger_tx"]) == (synth[0].id, synth[2].id) and meta["deleted"] is None


def test_release_delete_drops_the_release_transmission(tmp_path):
    conn = init_db(tmp_path / "t.sqlite")
    rid = _seed(conn, [LAND_31, GROUND, TO_31, READBACK])
    [inj] = [c for c in generate(conn, [rid], n=10, seed=0) if c.edit_kind == "release_delete"]
    sid = write_injection(conn, inj, seed=0, ordinal=0)
    assert [t.text for t in load_recording(conn, sid, "gold", "synthetic")] == [LAND_31[1], TO_31[1], READBACK[1]]
    assert synthetic_recordings(conn)[0]["deleted"] == GROUND[1]


def test_a_runway_swap_never_starts_from_the_other_end_of_the_anchor_strip(tmp_path):
    """Crossing at 13 while a landing holds 31 is already a conflict (13 and 31 are one strip), so swapping 13 for 31
    would inject nothing the recording did not already contain."""
    conn = init_db(tmp_path / "t.sqlite")
    rid = _seed(conn, [LAND_31, READBACK, ("controller", "lufthansa four five six cross runway one three")])
    assert [c for c in generate(conn, [rid], n=10, seed=0) if c.edit_kind == "runway_swap"] == []


def test_the_injected_conflict_is_what_the_rules_parser_then_sees(tmp_path):
    conn = init_db(tmp_path / "t.sqlite")
    rid = _seed(conn, [LAND_31, READBACK, ("controller", "lufthansa four five six cross runway two two")])
    [inj] = [c for c in generate(conn, [rid], n=10, seed=0) if c.edit_kind == "runway_swap"]
    sid = write_injection(conn, inj, seed=0, ordinal=0)
    assert not [c for s in build_timeline(conn, rid).steps for c in s.conflicts]
    tl = build_timeline(conn, sid, transcript_model="synthetic")
    assert [(k, c.type, c.severity, c.runway) for k, s in enumerate(tl.steps) for c in s.conflicts] == [(2, "RUNWAY", "alert", "31")]


def test_a_splice_needs_x_to_end_holding_a_and_y_to_clear_the_same_runway_against_it():
    x = _txs(LAND_31, READBACK)
    y = _txs(("pilot", "ruzyne tower lufthansa four five six ready"), TO_31)
    inj = splice_candidate(1, x, 13.0, 2, y)
    assert inj == Injection(1, "splice", 0, 3, "31", TO_31[1], second=2, offset=13.0 + SPLICE_GAP_S - 0.0)
    assert splice_anchor(_txs(LAND_31, GROUND)) is None                       # released before X ends
    assert splice_candidate(1, x, 13.0, 2, _txs(LINEUP_13)) is None          # another runway
    assert splice_candidate(1, x, 13.0, 2, _txs(("controller", "jet one runway three one cleared to land"))) is None  # LAND after LAND is lawful
    assert splice_candidate(1, x, 290.0, 2, y) is None                       # A would be stale by the time B arrives


def test_splices_pair_recordings_from_one_airport_and_store_both_halves(tmp_path):
    conn = init_db(tmp_path / "t.sqlite")
    x = _seed(conn, [LAND_31, READBACK], external_id="x", asr=True)
    y = _seed(conn, [("pilot", "tower lufthansa four five six ready"), TO_31], external_id="y", asr=True)
    _seed(conn, [TO_31], external_id="z", airport="EDDF")
    splices = [c for c in pool(conn, [x, y, 3]) if c.edit_kind == "splice"]
    # both orders conflict (Y ends holding a takeoff that X's landing clearance meets); Z is at another airport
    assert [(c.recording_id, c.second) for c in splices] == [(x, y), (y, x)]
    sid = write_injection(conn, splices[0], seed=0, ordinal=0)
    synth = load_recording(conn, sid, "gold", "synthetic")
    assert [t.text for t in synth] == [LAND_31[1], READBACK[1], "tower lufthansa four five six ready", TO_31[1]]
    assert [t.start_s for t in synth] == [0.0, 10.0, 13.0 + SPLICE_GAP_S, 23.0 + SPLICE_GAP_S]
    ext = [r[0] for r in conn.execute("SELECT external_id FROM transmissions WHERE recording_id = ? ORDER BY start_s", (sid,))]
    assert ext == ["x0", "x1", "b:x0", "b:x1"]
    assert [t.text for t in load_recording(conn, sid, "asr", "whisper")] == [f"asr {t.text}" for t in synth]   # nothing edited
    [meta] = synthetic_recordings(conn)
    assert (meta["second_recording_id"], meta["splice_tx"], meta["trigger_tx"]) == (y, synth[2].id, synth[3].id)
    tl = build_timeline(conn, sid, transcript_model="synthetic")
    assert [(k, c.runway, c.severity) for k, s in enumerate(tl.steps) for c in s.conflicts] == [(3, "31", "alert")]
    assert "--- recording" in check_rows(conn)[0]["context"]


def test_the_check_sheet_round_trips_verdicts(tmp_path):
    conn = init_db(tmp_path / "t.sqlite")
    rid = _seed(conn, [LAND_31, READBACK, LINEUP_22, HOLD_13])
    for i, inj in enumerate(generate(conn, [rid], n=10, seed=0)):
        write_injection(conn, inj, seed=0, ordinal=i)
    rows = check_rows(conn)
    assert len(rows) == 2 and {r["edit_kind"] for r in rows} == {"runway_swap", "holdshort_to_cross"}
    swap = next(r for r in rows if r["edit_kind"] == "runway_swap")
    assert swap["context"].splitlines()[0] == f"A> [controller] {LAND_31[1]}"
    assert swap["context"].splitlines()[2].startswith("B> [controller] ") and swap["valid"] == ""
    swap["valid"], swap["notes"] = "YES", "fine"
    assert apply_check(conn, rows) == {"yes": 1, "no": 0, "": 1}
    [positive] = synthetic_recordings(conn, valid_only=True)
    assert positive["recording_id"] == swap["recording_id"]
    again = next(r for r in check_rows(conn) if r["edit_kind"] == "runway_swap")
    assert (again["valid"], again["notes"]) == ("yes", "fine")
    swap["valid"] = "maybe"
    with pytest.raises(ValueError, match="yes, no or blank"):
        apply_check(conn, rows)


@pytest.mark.skipif(not DB.exists(), reason="needs the UWB-ATCC corpus in data/atc.sqlite (not redistributed)")
def test_recording_528_yields_injections_on_the_real_corpus():
    from atcdb.schema import connect
    conn = connect(DB)
    pool = candidates(528, load_recording(conn, 528, "gold", "human"))
    # the crossing (steps 11, 13) and the landing clearance (16) on 13; the release in between (15) is another
    # aircraft's handoff, which is exactly what the human check must reject
    assert sorted((c.edit_kind, c.anchor, c.trigger) for c in pool) == [
        ("holdshort_to_cross", 16, 18), ("release_delete", 11, 16), ("release_delete", 13, 16)]


def test_missing_asr_names_the_originals_whose_gold_transmissions_lack_asr(tmp_path):
    conn = init_db(tmp_path / "t.sqlite")
    full = _seed(conn, [LAND_31, LINEUP_13], external_id="full", asr=True)
    bare = _seed(conn, [LAND_31, LINEUP_13], external_id="bare")
    part = _seed(conn, [LAND_31, LINEUP_13], external_id="part", asr=True)
    conn.execute("""DELETE FROM transcripts WHERE kind = 'asr' AND transmission_id =
                    (SELECT MAX(id) FROM transmissions WHERE recording_id = ?)""", (part,))
    chosen = [Injection(full, "runway_swap", 0, 1, "31", "x"), Injection(full, "splice", 0, 2, "31", "x", second=bare),
              Injection(part, "verb_upgrade", 0, 1, "31", "x")]
    assert missing_asr(conn, chosen) == [bare, part]   # a splice's second recording counts too
    assert missing_asr(conn, chosen[:1]) == []
