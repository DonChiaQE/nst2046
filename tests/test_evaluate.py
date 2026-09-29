import pytest

from atcdb import engine
from atcdb.evaluate import (ARMS, PRIMARY, Arm, Pending, adjudication_kappa, adjudication_rows, alert_key, alert_keys,
                            bootstrap, cohen_kappa, detection, evaluation_sets, false_alarm_units, in_overlap, overlap_rows,
                            paired_bootstrap, per_hour, rate, read_rows, read_verdicts, recall, recording_row, refold,
                            run_arm, sweep, uncached, usable, write_rows)
from atcdb.inject import apply_check, check_rows, generate, write_injection
from atcdb.schema import init_db


def _seed(conn, turns, external_id="r1", split="test"):
    """One tower recording with human gold transcripts at 10 s spacing (each 3 s long). Returns its id."""
    conn.execute("INSERT OR IGNORE INTO sources (id, name, kind) VALUES (1, 'test', 'corpus')")
    rid = conn.execute("INSERT INTO recordings (source_id, external_id, facility, airport_icao) VALUES (1, ?, 'Tower', 'LKPR')",
                       (external_id,)).lastrowid
    for i, (role, text) in enumerate(turns):
        xid = conn.execute(
            """INSERT INTO transmissions (recording_id, external_id, start_s, end_s, speaker_role, split)
               VALUES (?, ?, ?, ?, ?, ?)""", (rid, f"x{i}", 10.0 * i, 10.0 * i + 3, role, split)).lastrowid
        conn.execute("INSERT INTO transcripts (transmission_id, kind, model, raw_text, normalized_text) VALUES (?, 'gold', 'human', ?, ?)",
                     (xid, text, text))
    conn.commit()
    return rid


CONFLICT = [
    ("controller", "csa one two three runway three one cleared to land wind calm"),
    ("pilot", "cleared to land runway three one csa one two three"),
    ("controller", "lufthansa four five six cross runway three one"),
    ("pilot", "crossing runway three one lufthansa four five six"),
]
QUIET = [
    ("controller", "csa one two three runway three one cleared to land wind calm"),
    ("pilot", "cleared to land runway three one csa one two three"),
    ("controller", "lufthansa four five six hold short of runway one three"),
    ("pilot", "holding short one three lufthansa four five six"),
]


def test_the_arms_cover_every_extractor_context_and_transcript():
    assert len(ARMS) == 18 and len(set(ARMS)) == 18
    assert {a.parser for a in ARMS} == {"rule", "llm"} and {a.transcript for a in ARMS} == {"gold", "asr"}
    assert PRIMARY == (Arm("rule", "rules", "window", "gold"), Arm("llm", "claude-sonnet-5", "window", "gold"))
    assert PRIMARY[1].name == "llm-claude-sonnet-5-window-gold"


def test_evaluation_sets_are_real_recordings_plus_valid_injections(tmp_path):
    conn = init_db(tmp_path / "t.sqlite")
    rid = _seed(conn, QUIET + [("controller", "jet one line up runway one three")])
    for i, inj in enumerate(generate(conn, [rid], n=10, seed=0)):
        write_injection(conn, inj, seed=0, ordinal=i)
    rows = check_rows(conn)
    rows[0]["valid"] = "yes"
    apply_check(conn, rows)
    sets = evaluation_sets(conn)
    assert sets[0] == (rid, "negatives", None) and len(sets) == 2
    sid, name, truth = sets[1]
    assert name == "positives" and set(truth) == {"runway", "trigger_tx", "edit_kind"}


def test_recording_row_keeps_steps_conflicts_and_span(tmp_path):
    conn = init_db(tmp_path / "t.sqlite")
    rid = _seed(conn, CONFLICT)
    row = recording_row(conn, PRIMARY[0], rid, "negatives", None)
    assert row["span_s"] == 33.0 and row["all_test"] is True and row["incomplete"] is False
    assert len(row["tx_ids"]) == 4 and row["t"] == [0.0, 10.0, 20.0, 30.0]
    assert row["events"][0] == [["LAND", "csa one two three", "31", None]]
    [c] = row["conflicts"]
    assert (c["type"], c["severity"], c["runway"], c["step"], c["tx_id"]) == ("RUNWAY", "alert", "31", 2, row["tx_ids"][2])
    assert c["callsigns"] == ["lufthansa four five six", "csa one two three"]
    assert row["missing_transcripts"] == 0 and usable(row)
    asr_arm = Arm("rule", "rules", "window", "asr")
    asr = recording_row(conn, asr_arm, rid, "negatives", None)
    assert asr["tx_ids"] == [] and asr["span_s"] == 33.0 and not usable(asr)   # no ASR yet: same span, not scored
    conn.execute("""INSERT INTO transcripts (transmission_id, kind, model, raw_text, normalized_text)
                    VALUES (?, 'asr', 'whisper', 'x', 'x')""", (row["tx_ids"][0],))
    partial = recording_row(conn, asr_arm, rid, "negatives", None)
    assert partial["missing_transcripts"] == 3 and not usable(partial)        # an ASR run that has not finished


def test_run_arm_is_the_same_serial_and_threaded_and_round_trips_through_jsonl(tmp_path):
    db = tmp_path / "t.sqlite"
    conn = init_db(db)
    items = [(_seed(conn, CONFLICT, external_id=f"r{i}"), "negatives", None) for i in range(4)]
    serial = run_arm(db, PRIMARY[0], items)
    assert run_arm(db, PRIMARY[0], items, workers=3) == serial
    write_rows(tmp_path / "out" / "a.jsonl", serial)
    assert read_rows(tmp_path / "out" / "a.jsonl") == serial


def test_uncached_counts_what_an_arm_still_has_to_parse(tmp_path):
    db = tmp_path / "t.sqlite"
    conn = init_db(db)
    rid = _seed(conn, CONFLICT)
    assert uncached(conn, PRIMARY[0], [rid]) == (4, 0.0)
    run_arm(db, PRIMARY[0], [(rid, "negatives", None)])
    assert uncached(conn, PRIMARY[0], [rid]) == (0, 0.0)
    n, cost = uncached(conn, PRIMARY[1], [rid])
    assert n == 4 and cost > 0


def _row(conflicts, tx_ids=(1, 2, 3, 4), truth=None, span=36.0, incomplete=False, rid=7, missing=0):
    return {"recording_id": rid, "set": "positives" if truth else "negatives", "truth": truth, "span_s": span,
            "incomplete": incomplete, "missing_transcripts": missing, "tx_ids": list(tx_ids), "conflicts": conflicts}


def _c(step, severity="alert", runway="31", type_="RUNWAY", tx=None):
    return {"type": type_, "severity": severity, "runway": runway, "callsigns": ["a", "b"], "step": step,
            "tx_id": tx if tx is not None else step + 1}


TRUTH = {"runway": "31", "trigger_tx": 3, "edit_kind": "splice"}


@pytest.mark.parametrize("conflicts, expected", [
    ([_c(2)], "strict"),
    ([_c(3)], "lenient"),                          # fired late, at a re-confirmation
    ([_c(2, severity="warning")], "partial"),
    ([_c(1)], "miss"),                             # before the trigger: not the injected conflict
    ([_c(2, runway="13")], "miss"),
    ([_c(2, type_="READBACK")], "miss"),
    ([], "miss"),
])
def test_detection(conflicts, expected):
    assert detection(_row(conflicts, truth=TRUTH)) == expected


def test_detection_of_a_trigger_without_a_transcript_is_unscorable():
    assert detection(_row([_c(1)], tx_ids=(1, 2), truth=TRUTH)) == "unscorable"


def test_recall_counts_strict_inside_lenient_and_skips_what_cannot_be_scored():
    rows = [_row([_c(2)], truth=TRUTH), _row([_c(3)], truth=TRUTH), _row([_c(2, severity="warning")], truth=TRUTH),
            _row([], truth=TRUTH), _row([_c(2)], truth=TRUTH, incomplete=True), _row([], tx_ids=(1,), truth=TRUTH),
            _row([_c(2)], truth=TRUTH, missing=1)]
    assert recall(rows) == {"n": 4, "strict": 1, "lenient": 2, "partial": 1, "miss": 1}


def test_alert_keys_ignore_callsigns_and_warnings():
    row = _row([_c(2), {**_c(2), "callsigns": ["", "b"]}, _c(3, severity="warning"), _c(1, type_="READBACK")])
    assert alert_keys(row) == {"7:RUNWAY:31:3", "7:READBACK:31:2"}
    assert alert_keys(row, "RUNWAY") == {"7:RUNWAY:31:3"}
    assert alert_key(7, _c(0, runway=None)) == "7:RUNWAY:-:1"


def test_false_alarms_per_hour_use_verdicts_and_refuse_to_guess():
    rows = [_row([_c(2)], span=1800.0, rid=1), _row([_c(0), _c(3)], span=1800.0, rid=2), _row([], span=3600.0, rid=3),
            _row([_c(2)], span=3600.0, rid=4, incomplete=True)]
    verdicts = {"1:RUNWAY:31:3": "parse_error", "2:RUNWAY:31:1": "genuine", "2:RUNWAY:31:4": "missing_info"}
    units = false_alarm_units(rows, verdicts)
    assert units == [(1.0, 1800.0), (1.0, 1800.0), (0.0, 3600.0)]
    assert per_hour(units) == 1.0                  # two false alarms over two hours; the genuine one does not count
    with pytest.raises(Pending, match="1 alerts"):
        false_alarm_units(rows, {k: v for k, v in verdicts.items() if k != "2:RUNWAY:31:4"})
    assert false_alarm_units(rows, {}, conflict_type="READBACK") == [(0.0, 1800.0), (0.0, 1800.0), (0.0, 3600.0)]


def test_bootstrap_is_seeded_and_brackets_the_point_estimate():
    units = [1.0] * 30 + [0.0] * 70
    lo, hi = bootstrap(units, rate, seed=0)
    assert (lo, hi) == bootstrap(units, rate, seed=0)
    assert lo < 0.3 < hi and 0.15 < lo and hi < 0.45
    assert bootstrap([], rate) == (0.0, 0.0)
    assert bootstrap([1.0] * 5, rate) == (1.0, 1.0)


def test_paired_bootstrap_of_a_difference():
    pairs = [(1.0, 0.0)] * 20 + [(1.0, 1.0)] * 20 + [(0.0, 0.0)] * 60
    point, lo, hi = paired_bootstrap(pairs, rate, seed=0)
    assert point == pytest.approx(0.2) and lo > 0 and lo < 0.2 < hi
    same = [(1.0, 1.0)] * 10 + [(0.0, 0.0)] * 10
    assert paired_bootstrap(same, rate) == (0.0, 0.0, 0.0)   # paired draws: identical arms never differ


def test_cohen_kappa():
    assert cohen_kappa(["a", "b", "a", "b"], ["a", "b", "a", "b"]) == 1.0
    assert cohen_kappa(["a", "a"], ["a", "a"]) == 1.0
    assert cohen_kappa(["a", "a", "b", "b"], ["a", "b", "a", "b"]) == 0.0
    assert cohen_kappa(["a", "a", "a", "b"], ["a", "a", "b", "b"]) == pytest.approx(0.5)
    with pytest.raises(ValueError):
        cohen_kappa(["a"], [])


def test_the_adjudication_sheet_pools_alerts_across_arms_and_keeps_verdicts(tmp_path):
    db = tmp_path / "t.sqlite"
    conn = init_db(db)
    rid = _seed(conn, CONFLICT)
    quiet = _seed(conn, QUIET, external_id="quiet")
    rules = run_arm(db, PRIMARY[0], [(rid, "negatives", None), (quiet, "negatives", None)])
    other = [{**r, "conflicts": [{**c, "callsigns": ["", c["callsigns"][1]]} for c in r["conflicts"]]} for r in rules]
    positive = [{**rules[0], "set": "positives"}]
    sheet = adjudication_rows(conn, {"rule-a": rules, "rule-b": other, "rule-c": positive})
    [row] = sheet
    tx = rules[0]["tx_ids"][2]
    assert row["key"] == f"{rid}:RUNWAY:31:{tx}" and row["arms"] == "rule-a; rule-b"
    assert row["callsigns"] == "lufthansa four five six / csa one two three; ? / csa one two three"
    assert row["context"].splitlines()[-1] == f">> [controller] {CONFLICT[2][1]}"
    assert len(row["context"].splitlines()) == 3 and row["verdict"] == ""
    row["verdict"], row["notes"] = "parse_error", "x"
    stale = {**row, "key": "999:RUNWAY:31:1", "recording_id": "999", "tx_id": "1", "verdict": "genuine"}
    again = adjudication_rows(conn, {"rule-a": rules}, existing=[row, stale])
    assert [(r["key"], r["verdict"]) for r in again] == [(row["key"], "parse_error"), (stale["key"], "genuine")]
    assert read_verdicts(again) == {row["key"]: "parse_error", stale["key"]: "genuine"}


def test_read_verdicts_rejects_unknown_labels():
    assert read_verdicts([{"key": "k", "verdict": " Genuine "}, {"key": "j", "verdict": ""}]) == {"k": "genuine"}
    with pytest.raises(ValueError, match="verdict must be one of"):
        read_verdicts([{"key": "k", "verdict": "false"}])


def test_the_overlap_sheet_is_a_stable_share_that_hides_the_first_verdicts():
    keys = [f"{i}:RUNWAY:31:{i}" for i in range(1000)]
    share = sum(in_overlap(k) for k in keys) / len(keys)
    assert 0.25 < share < 0.35 and in_overlap(keys[0]) == in_overlap(keys[0])
    sheet_a = [{"key": k, "verdict": "genuine", "notes": "a"} for k in keys[:20]]
    b = overlap_rows(sheet_a)
    assert [r["key"] for r in b] == [k for k in keys[:20] if in_overlap(k)] and all(r["verdict"] == "" for r in b)
    b[0]["verdict"] = "engine_rule"
    assert overlap_rows(sheet_a + [{"key": "new", "verdict": ""}], existing_b=b)[0]["verdict"] == "engine_rule"


def test_adjudication_kappa_uses_the_alerts_both_adjudicated():
    a = [{"key": "1", "verdict": "genuine"}, {"key": "2", "verdict": "parse_error"}, {"key": "3", "verdict": "parse_error"}]
    b = [{"key": "1", "verdict": "genuine"}, {"key": "2", "verdict": "parse_error"}, {"key": "3", "verdict": ""}]
    assert adjudication_kappa(a, b) == (1.0, 2)


def test_refold_at_the_default_timeouts_reproduces_the_replay(tmp_path):
    db = tmp_path / "t.sqlite"
    conn = init_db(db)
    [row] = run_arm(db, PRIMARY[0], [(_seed(conn, CONFLICT), "negatives", None)])
    assert refold(row, {}) == [c for c in row["conflicts"] if c["type"] == "RUNWAY"] != []


def _timed(events_by_step, t, truth=None, set_name="positives", rid=1):
    """A row whose steps are at times `t`, with the given event rows."""
    return {"recording_id": rid, "set": set_name, "truth": truth, "span_s": 100.0, "incomplete": False,
            "missing_transcripts": 0, "tx_ids": list(range(1, len(t) + 1)), "t": list(t), "events": events_by_step,
            "conflicts": []}


def test_a_shorter_crossing_timeout_forgets_the_crossing_before_the_landing():
    events = [[["CROSS", "lufthansa four five six", "31", None]], [], [["LAND", "csa one two three", "31", None]]]
    row = _timed(events, [0.0, 20.0, 60.0], truth={"runway": "31", "trigger_tx": 3, "edit_kind": "splice"})
    assert [c["step"] for c in refold(row, {})] == [2]
    assert refold(row, {"CROSS": 30.0}) == []
    assert engine.STALE_S["CROSS"] == 300.0                       # the override never leaks
    negative = {**_timed(events, [0.0, 20.0, 60.0], set_name="negatives", rid=2)}
    result = sweep([row, negative], values=(30.0, 300.0))
    assert [r["stale_s"] for r in result] == [30.0, 300.0]
    assert [r["recall"]["strict"] for r in result] == [0, 1]
    assert [r["negative_alerts"] for r in result] == [0, 1]
