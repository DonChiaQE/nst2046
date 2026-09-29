"""Level 2 evaluation: run arms over recordings, then score (spec 2026-09-29-evaluation-3b1-design.md, sections 5 to 9).

An *arm* is one (parser, model, context, transcript) configuration. `run_arm` replays every recording of a set through
`build_timeline` (so parses come from, and go to, the `events` cache exactly as in the app) and returns one row per
recording; `write_rows`/`read_rows` keep them as JSONL. Everything below `read_rows` is pure: scoring reads rows, the
injection truth carried on positive rows, and the adjudication verdicts, and never touches the database.
"""
import hashlib
import json
import random
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable

from atcdb import engine, judge, parse_llm
from atcdb.engine import State
from atcdb.inject import synthetic_recordings
from atcdb.parsing import CONTEXT_MODES, event_to_row, row_to_event
from atcdb.replay import build_timeline, default_transcript_model, load_recording, real_recordings, uncached_parses
from atcdb.schema import connect

TRANSCRIPTS = ("gold", "asr")


@dataclass(frozen=True)
class Arm:
    parser: str       # rule | llm | judge
    model: str        # "rules", or a Claude model id
    context: str      # none | role | window; "sequence" for the judge, which sees the whole recording at once
    transcript: str   # gold | asr

    @property
    def name(self) -> str:
        return f"{self.parser}-{self.model}-{self.context}-{self.transcript}"


ARMS: tuple[Arm, ...] = tuple(Arm(p, m, c, t) for p, models in (("rule", ("rules",)), ("llm", parse_llm.MODELS))
                              for m in models for c in CONTEXT_MODES for t in TRANSCRIPTS)
# the ablation (spec section 7): the whole transcript to Claude, conflicts out, no parser and no engine
JUDGE_ARMS: tuple[Arm, ...] = tuple(Arm("judge", m, "sequence", t) for m in judge.MODELS for t in TRANSCRIPTS)
# the pre-registered primary comparison (spec addendum A.5): rules vs Sonnet, window context, human transcripts
PRIMARY = (Arm("rule", "rules", "window", "gold"), Arm("llm", "claude-sonnet-5", "window", "gold"))


# --- sets and running ---------------------------------------------------------------------------------------------

def evaluation_sets(conn: sqlite3.Connection) -> list[tuple[int, str, dict | None]]:
    """(recording_id, set, truth) for every recording scored: `negatives` are the real replayable tower recordings (by
    their gold transcripts, so both transcript arms score the same recordings); `positives` are the injections a human
    marked valid, each with its truth (runway, trigger transmission, kind)."""
    out: list[tuple[int, str, dict | None]] = [(r["id"], "negatives", None) for r in real_recordings(conn)]
    for inj in synthetic_recordings(conn, valid_only=True):
        out.append((inj["recording_id"], "positives", {"runway": inj["runway"], "trigger_tx": inj["trigger_tx"],
                                                       "edit_kind": inj["edit_kind"]}))
    return out


def _judge_steps(conn: sqlite3.Connection, arm: Arm, recording_id: int) -> dict:
    """The judge arm's part of a row: the transmissions it saw and the conflicts it reported, each an alert (the judge
    has no severities) placed at its trigger transmission. A failed call marks the row incomplete."""
    model = default_transcript_model(conn, arm.transcript, recording_id)
    txs = load_recording(conn, recording_id, arm.transcript, model)
    try:
        found, dropped = judge.judge(conn, recording_id, txs, arm.transcript, model or "", arm.model)
        error = False
    except Exception:   # an API error must not stop the run; nothing was cached, the next run retries
        found, dropped, error = [], 0, True
    return {"incomplete": error, "dropped": dropped, "tx_ids": [tx.id for tx in txs], "t": [tx.start_s for tx in txs],
            "events": [[] for _ in txs],
            "conflicts": [{"type": c["type"], "severity": "alert", "runway": c["runway"], "callsigns": c["callsigns"],
                           "tx_id": txs[c["step"]].id, "step": c["step"]} for c in found]}


def recording_row(conn: sqlite3.Connection, arm: Arm, recording_id: int, set_name: str, truth: dict | None) -> dict:
    """Replay one recording under one arm and keep what scoring needs: per step the transmission, its time and events,
    and every conflict with the step that raised it (for the judge arm, what the judge reported). `span_s` covers all
    the recording's transmissions (first start to last end), whatever the transcript kind, so both transcript arms
    share a denominator. `missing_transcripts` counts transmissions with a gold transcript but none of the arm's kind
    (an ASR run that has not reached them); such a row is not scored. `all_test` says whether every transmission is in
    the ASR model's `test` split (spec section 3: the clean ASR headline)."""
    if arm.parser == "judge":
        steps = _judge_steps(conn, arm, recording_id)
    else:
        tl = build_timeline(conn, recording_id, parser=arm.parser, transcript_kind=arm.transcript, context=arm.context,
                            model=arm.model, transcript_model=default_transcript_model(conn, arm.transcript, recording_id))
        steps = {"incomplete": any(s.error for s in tl.steps), "dropped": tl.dropped,
                 "tx_ids": [s.tx.id for s in tl.steps], "t": [s.tx.start_s for s in tl.steps],
                 "events": [[list(event_to_row(e)) for e in s.events] for s in tl.steps],
                 "conflicts": [{"type": c.type, "severity": c.severity, "runway": c.runway, "callsigns": list(c.callsigns),
                                "tx_id": s.tx.id, "step": k} for k, s in enumerate(tl.steps) for c in s.conflicts]}
    span, all_test = conn.execute(
        """SELECT MAX(end_s) - MIN(start_s), MIN(CASE WHEN split = 'test' THEN 1 ELSE 0 END)
           FROM transmissions WHERE recording_id = ?""", (recording_id,)).fetchone()
    gold = {tx.id for tx in load_recording(conn, recording_id, "gold", default_transcript_model(conn, "gold", recording_id))}
    return {"recording_id": recording_id, "set": set_name, "truth": truth, "span_s": span or 0.0,
            "all_test": bool(all_test), "missing_transcripts": len(gold - set(steps["tx_ids"])), **steps}


def run_arm(db: Path, arm: Arm, recordings: list[tuple[int, str, dict | None]], workers: int = 1) -> list[dict]:
    """`recording_row` for every recording, in order. With `workers` > 1, recordings run on a thread pool, each thread
    with its own connection (a `window` replay stays sequential inside its recording; `get_events` settles two threads
    racing to cache the same transcript)."""
    def one(item: tuple[int, str, dict | None]) -> dict:
        conn = connect(db)
        try:
            return recording_row(conn, arm, *item)
        finally:
            conn.close()

    if workers <= 1:
        return [one(item) for item in recordings]
    with ThreadPoolExecutor(max_workers=workers) as pool:
        return list(pool.map(one, recordings))


def uncached(conn: sqlite3.Connection, arm: Arm, recording_ids: Iterable[int]) -> tuple[int, float]:
    """(calls still to make, rough USD) for one arm over the given recordings: transmissions to parse, or for the judge
    recordings to judge. Calls and stores nothing."""
    if arm.parser == "judge":
        prompts = []
        for rid in recording_ids:
            model = default_transcript_model(conn, arm.transcript, rid)
            txs = load_recording(conn, rid, arm.transcript, model)
            if txs and not judge.is_cached(conn, rid, arm.transcript, model or "", arm.model):
                prompts.append(judge.render_sequence(txs))
        return len(prompts), judge.estimate_cost(arm.model, prompts)
    misses = [m for rid in recording_ids for m in uncached_parses(
        conn, rid, parser=arm.parser, transcript_kind=arm.transcript, context=arm.context, model=arm.model,
        transcript_model=default_transcript_model(conn, arm.transcript, rid))]
    cost = parse_llm.estimate_cost(arm.model, [parse_llm.render_prompt(tx, ctx) for tx, ctx in misses]) \
        if arm.parser == "llm" else 0.0
    return len(misses), cost


def write_rows(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w") as fh:
        for r in rows:
            fh.write(json.dumps(r) + "\n")


def read_rows(path: Path) -> list[dict]:
    with path.open() as fh:
        return [json.loads(line) for line in fh if line.strip()]


# --- positives ------------------------------------------------------------------------------------------------------

def usable(row: dict) -> bool:
    """A row that can be scored: its replay finished (no parse failure) and every transmission had a transcript of the
    arm's kind."""
    return not row["incomplete"] and bool(row["tx_ids"]) and not row["missing_transcripts"]


def detection(row: dict) -> str:
    """How an arm did on one positive: `strict` (an alert on the injected runway raised by the trigger transmission),
    `lenient` (an alert on that runway at or after the trigger, but not at it), `partial` (only a warning there),
    `miss`, or `unscorable` (the trigger has no transcript of this arm's kind)."""
    truth = row["truth"]
    if truth["trigger_tx"] not in row["tx_ids"]:
        return "unscorable"
    k = row["tx_ids"].index(truth["trigger_tx"])
    hits = [c for c in row["conflicts"] if c["type"] == "RUNWAY" and c["runway"] == truth["runway"] and c["step"] >= k]
    alerts = [c for c in hits if c["severity"] == "alert"]
    if any(c["step"] == k for c in alerts):
        return "strict"
    if alerts:
        return "lenient"
    return "partial" if hits else "miss"


def recall(rows: list[dict]) -> dict[str, int]:
    """Counts over usable, scorable positives: `n`, `strict`, `lenient` (strict included), `partial`, `miss`."""
    out = {"n": 0, "strict": 0, "lenient": 0, "partial": 0, "miss": 0}
    for row in rows:
        d = detection(row) if usable(row) else "unscorable"
        if d == "unscorable":
            continue
        out["n"] += 1
        out[d] += 1
        if d == "strict":
            out["lenient"] += 1
    return out


# --- negatives -------------------------------------------------------------------------------------------------------

class Pending(Exception):
    """A false-alarm rate was asked for while some of its alerts have no adjudication verdict yet."""


def alert_key(recording_id: int, conflict: dict) -> str:
    """The adjudication key: one alert per (recording, type, runway, triggering transmission), whichever arm raised it
    and whichever callsigns it extracted (the rules parser often extracts none)."""
    return f"{recording_id}:{conflict['type']}:{conflict['runway'] or '-'}:{conflict['tx_id']}"


def alert_keys(row: dict, conflict_type: str | None = None) -> set[str]:
    """The distinct alert-severity conflicts in one row (optionally of one type), as adjudication keys."""
    return {alert_key(row["recording_id"], c) for c in row["conflicts"]
            if c["severity"] == "alert" and conflict_type in (None, c["type"])}


def false_alarm_units(rows: list[dict], verdicts: dict[str, str], conflict_type: str = "RUNWAY") -> list[tuple[float, float]]:
    """(false alarms, span_s) per usable negative row; a false alarm is an alert whose verdict is not `genuine`. Raises
    Pending if any alert has no verdict."""
    units, missing = [], 0
    for row in rows:
        if not usable(row):
            continue
        keys = alert_keys(row, conflict_type)
        missing += sum(k not in verdicts for k in keys)
        units.append((float(sum(verdicts.get(k) != "genuine" for k in keys)), row["span_s"]))
    if missing:
        raise Pending(f"{missing} alerts have no adjudication verdict")
    return units


def per_hour(units: list[tuple[float, float]]) -> float:
    """Sum of counts over hours of span."""
    hours = sum(span for _, span in units) / 3600
    return sum(n for n, _ in units) / hours if hours else 0.0


# --- statistics ------------------------------------------------------------------------------------------------------

def bootstrap(units: list, stat: Callable[[list], float], n: int = 2000, seed: int = 0) -> tuple[float, float]:
    """95% percentile interval of `stat` over `n` resamples (with replacement) of `units`."""
    if not units:
        return (0.0, 0.0)
    rng = random.Random(seed)
    values = sorted(stat([units[rng.randrange(len(units))] for _ in units]) for _ in range(n))
    return values[int(0.025 * n)], values[int(0.975 * n) - 1]


def paired_bootstrap(pairs: list[tuple], stat: Callable[[list], float], n: int = 2000,
                     seed: int = 0) -> tuple[float, float, float]:
    """(point, low, high) of stat(first) - stat(second) over `pairs` of units, both arms resampled with the same draws."""
    def diff(sample: list[tuple]) -> float:
        return stat([a for a, _ in sample]) - stat([b for _, b in sample])
    lo, hi = bootstrap(pairs, diff, n, seed)
    return diff(pairs), lo, hi


def rate(units: list[float]) -> float:
    """Mean of 0/1 units: a recall."""
    return sum(units) / len(units) if units else 0.0


def cohen_kappa(a: list[str], b: list[str]) -> float:
    """Cohen's kappa for two raters' labels of the same items, in order. 1.0 when both agree and use one label."""
    if len(a) != len(b) or not a:
        raise ValueError("kappa needs two equally long, non-empty label lists")
    labels = sorted(set(a) | set(b))
    n = len(a)
    observed = sum(x == y for x, y in zip(a, b)) / n
    expected = sum((a.count(lab) / n) * (b.count(lab) / n) for lab in labels)
    return 1.0 if expected == 1 else (observed - expected) / (1 - expected)


# --- adjudication (spec section 6) -----------------------------------------------------------------------------------

VERDICTS = ("genuine", "parse_error", "missing_info", "engine_rule")
ADJUDICATION_COLUMNS = ["key", "recording_id", "type", "runway", "tx_id", "arms", "callsigns", "context", "verdict", "notes"]
CONTEXT_LINES = 6   # transmissions shown up to and including the trigger


def adjudication_rows(conn: sqlite3.Connection, rows_by_arm: dict[str, list[dict]],
                      existing: Iterable[dict] = ()) -> list[dict]:
    """The adjudication sheet: every alert raised on a usable negative by any arm, pooled on `alert_key`, with the arms
    that raised it, the callsigns each extracted and the human transcript up to the trigger. Verdicts and notes already
    in `existing` are kept, and existing rows no longer raised by any arm stay on the sheet. Sorted by recording, then
    transmission."""
    pooled: dict[str, dict] = {}
    for arm_name, rows in sorted(rows_by_arm.items()):
        for row in rows:
            if row["set"] != "negatives" or not usable(row):
                continue
            for c in row["conflicts"]:
                if c["severity"] != "alert":
                    continue
                key = alert_key(row["recording_id"], c)
                entry = pooled.setdefault(key, {"key": key, "recording_id": row["recording_id"], "type": c["type"],
                                                "runway": c["runway"] or "", "tx_id": c["tx_id"], "arms": [], "callsigns": []})
                if arm_name not in entry["arms"]:
                    entry["arms"].append(arm_name)
                names = " / ".join(cs or "?" for cs in c["callsigns"])
                if names not in entry["callsigns"]:
                    entry["callsigns"].append(names)
    old = {r["key"]: r for r in existing}
    out = []
    for key, entry in pooled.items():
        txs = load_recording(conn, entry["recording_id"], "gold", default_transcript_model(conn, "gold", entry["recording_id"]))
        k = next(i for i, tx in enumerate(txs) if tx.id == entry["tx_id"])
        context = "\n".join(f"{'>>' if i == k else '  '} [{tx.role}] {tx.text}"
                            for i, tx in enumerate(txs) if k - CONTEXT_LINES < i <= k)
        out.append({**entry, "arms": "; ".join(entry["arms"]), "callsigns": "; ".join(entry["callsigns"]),
                    "context": context, "verdict": old.get(key, {}).get("verdict", ""),
                    "notes": old.get(key, {}).get("notes", "")})
    out += [r for key, r in old.items() if key not in pooled]
    return sorted(out, key=lambda r: (int(r["recording_id"]), int(r["tx_id"]), r["key"]))


def in_overlap(key: str, fraction: float = 0.3, seed: int = 0) -> bool:
    """Whether an alert belongs on the second adjudicator's sheet: a fixed pseudo-random share of keys, decided per key,
    so the overlap stays the same as more arms add alerts."""
    digest = hashlib.sha1(f"{seed}:{key}".encode()).digest()
    return int.from_bytes(digest[:8], "big") / 2 ** 64 < fraction


def overlap_rows(sheet_a: list[dict], existing_b: Iterable[dict] = (), fraction: float = 0.3, seed: int = 0) -> list[dict]:
    """Sheet B: the overlap share of sheet A's rows with A's verdicts removed, keeping B's own verdicts already given."""
    old = {r["key"]: r for r in existing_b}
    return [{**r, "verdict": old.get(r["key"], {}).get("verdict", ""), "notes": old.get(r["key"], {}).get("notes", "")}
            for r in sheet_a if in_overlap(r["key"], fraction, seed)]


def read_verdicts(sheet: Iterable[dict]) -> dict[str, str]:
    """key -> verdict for every row with a verdict. Raises ValueError on a verdict outside VERDICTS."""
    out = {}
    for r in sheet:
        v = (r.get("verdict") or "").strip().lower()
        if not v:
            continue
        if v not in VERDICTS:
            raise ValueError(f"{r['key']}: verdict must be one of {', '.join(VERDICTS)}, not {r['verdict']!r}")
        out[r["key"]] = v
    return out


def adjudication_kappa(sheet_a: Iterable[dict], sheet_b: Iterable[dict]) -> tuple[float, int]:
    """(Cohen's kappa, items) over the alerts both adjudicators gave a verdict."""
    a, b = read_verdicts(sheet_a), read_verdicts(sheet_b)
    both = sorted(set(a) & set(b))
    return cohen_kappa([a[k] for k in both], [b[k] for k in both]), len(both)


# --- staleness sweep (spec section 9) --------------------------------------------------------------------------------

SWEEP_KINDS = ("CROSS", "LUAW")
SWEEP_VALUES = (30.0, 60.0, 90.0, 120.0, 300.0)


def refold(row: dict, stale: dict[str, float]) -> list[dict]:
    """The row's RUNWAY conflicts re-derived from its stored events with `engine.STALE_S` overridden by `stale`. No
    parse is repeated, so a `window` arm keeps the context it was parsed with. READBACK conflicts are not re-derived
    (the stored events do not carry the instruction text a readback is checked against)."""
    saved = dict(engine.STALE_S)
    engine.STALE_S.update(stale)
    try:
        state, out = State(), []
        for k, (tx_id, t, events) in enumerate(zip(row["tx_ids"], row["t"], row["events"])):
            for kind, callsign, runway, extra in events:
                state, new = engine.apply(state, row_to_event(kind, callsign, runway, extra, t=t))
                out += [{"type": c.type, "severity": c.severity, "runway": c.runway, "callsigns": list(c.callsigns),
                         "tx_id": tx_id, "step": k} for c in new if c.type == "RUNWAY"]
        return out
    finally:
        engine.STALE_S.clear()
        engine.STALE_S.update(saved)


def sweep(rows: list[dict], values: Iterable[float] = SWEEP_VALUES, kinds: tuple[str, ...] = SWEEP_KINDS) -> list[dict]:
    """For each timeout value applied to `kinds`: recall on the arm's positives and the raw count of distinct RUNWAY
    alerts on its negatives (not adjudicated: the sweep is a sensitivity finding, nothing is chosen from it)."""
    out = []
    for v in values:
        refolded = [{**r, "conflicts": refold(r, {k: v for k in kinds})} for r in rows if usable(r)]
        alerts = set().union(*[alert_keys(r, "RUNWAY") for r in refolded if r["set"] == "negatives"])
        out.append({"stale_s": v, "recall": recall([r for r in refolded if r["set"] == "positives"]),
                    "negative_alerts": len(alerts)})
    return out
