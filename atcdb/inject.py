"""Conflict injection (spec 2026-09-29-evaluation-3b1-design.md, section 4).

A scan that uses no parser finds clearance *sites* in a recording's human gold text. A seeded generator then builds a
sequence in which a later transmission B conflicts with an earlier reservation A on runway R, either by editing real text
or by splicing two real recordings. Each sequence is stored as a new recording under the `synthetic-conflicts` source,
and a human says yes or no to each before it counts as a positive. The scan's regexes are deliberately broader than the
rules parser's (`atcdb/parse_rules` stays frozen): no `runway` token is needed before a designator that carries a side,
and a single digit is a runway.

Kinds (A = anchor site, B = trigger site, R = A's runway):
- runway_swap:        B is a clearance to another strip (not R's other end, which already conflicts); its designator
                      becomes R's.
- holdshort_to_cross: B is `hold short (of) (runway) X`; it becomes `cross runway R`.
- verb_upgrade:       A is a landing clearance on R and B a line-up or landing clearance on R; B's verb becomes
                      `cleared for takeoff`.
- release_delete:     a release between A and a later clearance B on R that conflicts with A is deleted.
- splice:             nothing is edited. Recording X ends holding A (no release of it follows) and a different recording
                      Y, from the same airport, contains a clearance B on R that conflicts with A; the sequence is X
                      followed by Y, shifted to start SPLICE_GAP_S after X ends. Only a splice whose B falls within A's
                      staleness timeout is kept, so the engine still holds A when B arrives. The four text edits yield
                      about ten candidates on this corpus (few clips hold two clearances); splicing supplies the rest.
"""
import json
import random
import re
import sqlite3
from dataclasses import dataclass

from atcdb.engine import MATRIX, RESERVATION_KINDS, STALE_S, normalize_runway, reciprocal
from atcdb.parsing import Transmission
from atcdb.replay import SYNTHETIC_SOURCE, default_transcript_model, load_recording

SOURCE = SYNTHETIC_SOURCE
TRANSCRIPT_MODEL = "synthetic"   # gold transcripts of synthetic recordings
ASR_VERSION = "synthetic"        # model_version of an edited trigger's ASR row, which holds the edited gold text
EDIT_KINDS = ("runway_swap", "holdshort_to_cross", "verb_upgrade", "release_delete", "splice")
ANCHOR_ROLES = ("controller", "mixed")
SPLICE_GAP_S = 5.0               # silence between the end of X and the start of Y in a splice

_D = r"(?:zero|one|two|three|four|five|six|seven|eight|nine)"
_SIDE = r"(?:left|right|centre|center)"
_DESIG = rf"{_D}(?: {_D})?(?: {_SIDE})?"
_RUNWAY_RE = re.compile(rf"\brunway (?P<rwy>{_DESIG})\b|\b(?P<bare>{_D}(?: {_D})? {_SIDE})\b")
_HOLD_RE = re.compile(rf"\bhold(?:ing)? short (?:of )?(?:runway )?(?P<rwy>{_DESIG})\b")
_CROSS_RE = re.compile(rf"\bcross (?:runway )?(?P<rwy>{_DESIG})\b")
_VERB_RE = {"TAKEOFF": re.compile(r"\bcleared for take ?off\b"), "LAND": re.compile(r"\bcleared to land\b"),
            "LUAW": re.compile(r"\bline up(?: and wait)?\b")}
_RELEASE_RE = re.compile(r"\bcontact (?:ruzyne |praha |prague )?(?P<to>ground|apron|radar|director|departure)\b"
                         r"|\b(?P<vacated>vacated)\b")
# which reservation kinds a release frees (engine.apply: ground frees LAND and CROSS, departure frees TAKEOFF)
_RELEASES = {"ground": ("LAND", "CROSS"), "departure": ("TAKEOFF",), "vacated": RESERVATION_KINDS}


@dataclass(frozen=True)
class Site:
    index: int                 # position of the transmission in the recording
    kind: str                  # LAND | TAKEOFF | LUAW | CROSS | HOLD_SHORT | RELEASE
    runway: str | None         # normalized designator; None for RELEASE
    words: str = ""            # the designator as spoken, e.g. "three one"
    rwy_span: tuple[int, int] = (0, 0)    # character span of the designator in the text
    edit_span: tuple[int, int] = (0, 0)   # character span an edit replaces: the verb, or the whole hold-short phrase
    released: tuple[str, ...] = ()        # RELEASE only: reservation kinds it frees


@dataclass(frozen=True)
class Injection:
    recording_id: int          # the original recording (X, for a splice)
    edit_kind: str
    anchor: int                # index of A in the sequence (X's transmissions, then Y's for a splice)
    trigger: int                # index of B in the same sequence
    runway: str                # R, normalized
    after: str                  # B's text as stored (unchanged for release_delete and splice)
    deleted: int | None = None # index of the deleted release (release_delete only)
    second: int | None = None  # Y (splice only)
    offset: float = 0.0        # seconds added to Y's start times (splice only)


def _runway_near(text: str, verb: tuple[int, int]) -> tuple[str, str, tuple[int, int]] | None:
    """The runway designator closest to the verb at character span `verb`, measured as the gap between the verb and the
    whole `runway X` phrase on either side: (normalized, spoken words, designator span), or None."""
    best = None
    for m in _RUNWAY_RE.finditer(text):
        group = "rwy" if m.group("rwy") else "bare"
        rwy = normalize_runway(m.group(group))
        if rwy is None:
            continue
        dist = m.start() - verb[1] if m.start() >= verb[1] else verb[0] - m.end()
        if best is None or dist < best[0]:
            best = (dist, rwy, m.group(group), m.span(group))
    return best[1:] if best else None


def scan(txs: list[Transmission]) -> list[Site]:
    """Every clearance, hold-short and release site in a recording, in transmission order. Clearances and hold-shorts
    count only from controller (or mixed) transmissions; a release counts from anyone (pilots report `vacated`)."""
    sites: list[Site] = []
    for k, tx in enumerate(txs):
        text = tx.text
        if tx.role in ANCHOR_ROLES:
            for kind, rx in (("HOLD_SHORT", _HOLD_RE), ("CROSS", _CROSS_RE)):
                for m in rx.finditer(text):
                    rwy = normalize_runway(m.group("rwy"))
                    if rwy:
                        sites.append(Site(k, kind, rwy, m.group("rwy"), m.span("rwy"), m.span()))
            verbs = ("TAKEOFF", "LAND") if _VERB_RE["TAKEOFF"].search(text) else ("TAKEOFF", "LAND", "LUAW")
            for kind in verbs:   # `line up runway 31 cleared for takeoff` is one takeoff clearance, not two sites
                m = _VERB_RE[kind].search(text)
                near = _runway_near(text, m.span()) if m else None
                if near:
                    sites.append(Site(k, kind, near[0], near[1], near[2], m.span()))
        for m in _RELEASE_RE.finditer(text):
            to = "vacated" if m.group("vacated") else ("ground" if m.group("to") in ("ground", "apron") else "departure")
            sites.append(Site(k, "RELEASE", None, released=_RELEASES[to]))
    seen, unique = set(), []
    for s in sorted(sites, key=lambda s: (s.index, s.edit_span)):   # "cross runway 13 cross runway 13" is one site
        if s.kind == "RELEASE" or (s.index, s.kind, s.runway) not in seen:
            seen.add((s.index, s.kind, s.runway))
            unique.append(s)
    return unique


def _replace(text: str, span: tuple[int, int], new: str) -> str:
    return text[:span[0]] + new + text[span[1]:]


def _releases(sites: list[Site], kind: str, lo: int, hi: int) -> list[Site]:
    """Release sites strictly between transmissions `lo` and `hi` that free a reservation of `kind`."""
    return [s for s in sites if s.kind == "RELEASE" and lo < s.index < hi and kind in s.released]


def candidates(recording_id: int, txs: list[Transmission]) -> list[Injection]:
    """Every text edit the first four kinds allow in one recording. A and B are in different transmissions, and no
    release of A's kind lies between them (except the one release_delete removes)."""
    sites = scan(txs)
    out: list[Injection] = []
    for a in (s for s in sites if s.kind in RESERVATION_KINDS):
        for b in sites:
            if b.index <= a.index:
                continue
            text = txs[b.index].text
            between = _releases(sites, a.kind, a.index, b.index)
            if not between and b.kind in RESERVATION_KINDS and b.runway not in (a.runway, reciprocal(a.runway)) and MATRIX[(b.kind, a.kind)] == "alert":
                out.append(Injection(recording_id, "runway_swap", a.index, b.index, a.runway,
                                     _replace(text, b.rwy_span, a.words)))
            if not between and b.kind == "HOLD_SHORT" and MATRIX[("CROSS", a.kind)] == "alert":
                out.append(Injection(recording_id, "holdshort_to_cross", a.index, b.index, a.runway,
                                     _replace(text, b.edit_span, f"cross runway {a.words}")))
            if not between and a.kind == "LAND" and b.kind in ("LUAW", "LAND") and b.runway == a.runway:
                upgraded = _replace(text, b.edit_span, "cleared for takeoff")
                out.append(Injection(recording_id, "verb_upgrade", a.index, b.index, a.runway,
                                     re.sub(r" and wait\b", "", upgraded, count=1)))
            if len(between) == 1 and b.kind in RESERVATION_KINDS and b.runway == a.runway \
                    and MATRIX[(b.kind, a.kind)] == "alert":
                out.append(Injection(recording_id, "release_delete", a.index, b.index, a.runway, text,
                                     deleted=between[0].index))
    return list(dict.fromkeys(out))   # two sites of one transmission can yield the same edit


def splice_anchor(txs: list[Transmission]) -> Site | None:
    """The reservation a recording ends holding: its last reservation site with no release of that kind after it."""
    sites = scan(txs)
    held = [a for a in sites if a.kind in RESERVATION_KINDS and not _releases(sites, a.kind, a.index, len(txs))]
    return held[-1] if held else None


def splice_candidate(x_id: int, x_txs: list[Transmission], x_end: float,
                     y_id: int, y_txs: list[Transmission]) -> Injection | None:
    """X followed by Y, if X ends holding A and Y's first clearance on A's runway conflicts with A within A's staleness
    timeout. None otherwise."""
    a = splice_anchor(x_txs)
    if a is None:
        return None
    b = next((s for s in scan(y_txs) if s.kind in RESERVATION_KINDS and s.runway == a.runway), None)
    if b is None or MATRIX[(b.kind, a.kind)] != "alert":
        return None
    offset = x_end + SPLICE_GAP_S - y_txs[0].start_s
    if y_txs[b.index].start_s + offset - x_txs[a.index].start_s > STALE_S[a.kind]:
        return None
    return Injection(x_id, "splice", a.index, len(x_txs) + b.index, a.runway, y_txs[b.index].text,
                     second=y_id, offset=offset)


def select(found: list[Injection], n: int, seed: int) -> list[Injection]:
    """Up to `n` injections, stratified across EDIT_KINDS by round robin (a kind that runs out leaves its share to the
    others), at most one per (original recording, kind), chosen with `seed`."""
    rng = random.Random(seed)
    by_kind: dict[str, list[Injection]] = {}
    for kind in EDIT_KINDS:
        per_recording: dict[int, list[Injection]] = {}
        for inj in found:
            if inj.edit_kind == kind:
                per_recording.setdefault(inj.recording_id, []).append(inj)
        picks = [rng.choice(v) for _, v in sorted(per_recording.items())]
        rng.shuffle(picks)
        by_kind[kind] = picks
    chosen: list[Injection] = []
    while len(chosen) < n and any(by_kind.values()):
        for kind in EDIT_KINDS:
            if by_kind[kind] and len(chosen) < n:
                chosen.append(by_kind[kind].pop())
    return chosen


def _gold(conn: sqlite3.Connection, recording_id: int) -> list[Transmission]:
    return load_recording(conn, recording_id, "gold", default_transcript_model(conn, "gold", recording_id))


def pool(conn: sqlite3.Connection, recording_ids: list[int]) -> list[Injection]:
    """Every candidate of every kind over the given recordings' gold text; splices pair recordings from one airport."""
    txs = {rid: _gold(conn, rid) for rid in recording_ids}
    meta = {r["id"]: r for r in conn.execute(
        f"""SELECT r.id, r.airport_icao, MAX(x.end_s) AS end_s FROM recordings r JOIN transmissions x ON x.recording_id = r.id
            WHERE r.id IN ({','.join('?' * len(recording_ids))}) GROUP BY r.id""", recording_ids)}
    out = [c for rid in recording_ids for c in candidates(rid, txs[rid])]
    for x in recording_ids:
        if splice_anchor(txs[x]) is None:
            continue
        for y in recording_ids:
            if y != x and txs[y] and meta[y]["airport_icao"] == meta[x]["airport_icao"]:
                c = splice_candidate(x, txs[x], meta[x]["end_s"] or txs[x][-1].start_s, y, txs[y])
                if c:
                    out.append(c)
    return out


def generate(conn: sqlite3.Connection, recording_ids: list[int], n: int = 100, seed: int = 0) -> list[Injection]:
    """`select` over `pool`."""
    return select(pool(conn, recording_ids), n, seed)


def missing_asr(conn: sqlite3.Connection, injections: list[Injection]) -> list[int]:
    """The original recordings among `injections` (a splice's second recording included) that have a gold-transcribed
    transmission with no ASR transcript. An injection copies the ASR transcripts that exist when it is stored, and a
    later ASR run would transcribe the synthetic copies too (they keep the split), giving an edited trigger Whisper's
    text of the unedited audio; so ASR must be complete on these before injecting."""
    originals = sorted({rid for inj in injections for rid in (inj.recording_id, inj.second) if rid is not None})
    return [rid for rid in originals if conn.execute(
        """SELECT 1 FROM transmissions x WHERE x.recording_id = ?
           AND EXISTS (SELECT 1 FROM transcripts WHERE transmission_id = x.id AND kind = 'gold')
           AND NOT EXISTS (SELECT 1 FROM transcripts WHERE transmission_id = x.id AND kind = 'asr') LIMIT 1""",
        (rid,)).fetchone()]


def _source_id(conn: sqlite3.Connection) -> int:
    conn.execute("INSERT OR IGNORE INTO sources (name, kind, notes) VALUES (?, 'corpus', ?)",
                 (SOURCE, "conflicts injected into real gold transcripts by atcdb/inject.py; same licence as the originals"))
    return conn.execute("SELECT id FROM sources WHERE name = ?", (SOURCE,)).fetchone()[0]


def write_injection(conn: sqlite3.Connection, inj: Injection, seed: int, ordinal: int) -> int:
    """Store one injection as a new recording and return its id. Idempotent: an injection already stored under the same
    external id (`<original id>-<kind>-<seed>-<ordinal>`) is returned as is. Transmissions are copied with their timing
    (a splice's second recording shifted by `offset`, its external ids prefixed `b:`), role and clip path, with
    `pcm_sha1` NULL. Gold transcripts are model `synthetic`, and only an edited trigger's text differs. ASR transcripts
    are copied too, except an edited trigger's, which holds the edited gold text under model_version `synthetic`, since
    its audio does not contain the edit."""
    source = _source_id(conn)
    external_id = f"{inj.recording_id}-{inj.edit_kind}-{seed}-{ordinal}"
    row = conn.execute("SELECT id FROM recordings WHERE source_id = ? AND external_id = ?", (source, external_id)).fetchone()
    if row:
        return row[0]
    parts = [(inj.recording_id, 0.0, "")] + ([(inj.second, inj.offset, "b:")] if inj.second is not None else [])
    txs = [tx for rid, _, _ in parts for tx in _gold(conn, rid)]
    deleted_id = txs[inj.deleted].id if inj.deleted is not None else None
    edited_id = txs[inj.trigger].id if inj.after != txs[inj.trigger].text else None
    rid = conn.execute(
        """INSERT INTO recordings (source_id, external_id, airport_icao, facility, frequency_mhz, started_at_utc, path)
           SELECT ?, ?, airport_icao, facility, frequency_mhz, started_at_utc, path FROM recordings WHERE id = ?""",
        (source, external_id, inj.recording_id)).lastrowid
    new_ids: dict[int, int] = {}
    for part, offset, prefix in parts:
        for x in conn.execute("SELECT * FROM transmissions WHERE recording_id = ? ORDER BY start_s, id", (part,)).fetchall():
            if x["id"] == deleted_id:
                continue
            new_ids[x["id"]] = conn.execute(
                """INSERT INTO transmissions (recording_id, external_id, start_s, end_s, duration_s, speaker_role,
                                              speaker_label, pilot_callsign, clip_path, sample_rate, pcm_sha1, split)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, ?)""",
                (rid, prefix + x["external_id"], None if x["start_s"] is None else x["start_s"] + offset,
                 None if x["end_s"] is None else x["end_s"] + offset, x["duration_s"], x["speaker_role"],
                 x["speaker_label"], x["pilot_callsign"], x["clip_path"], x["sample_rate"], x["split"])).lastrowid
    for tx in txs:
        if tx.id == deleted_id:
            continue
        text = inj.after if tx.id == edited_id else tx.text
        conn.execute("""INSERT INTO transcripts (transmission_id, kind, model, raw_text, normalized_text)
                        VALUES (?, 'gold', ?, ?, ?)""", (new_ids[tx.id], TRANSCRIPT_MODEL, text, text))
    for t in conn.execute(
            f"""SELECT * FROM transcripts WHERE kind = 'asr'
                AND transmission_id IN ({','.join('?' * len(new_ids))}) ORDER BY id""", list(new_ids)).fetchall():
        edited = t["transmission_id"] == edited_id
        conn.execute(
            """INSERT INTO transcripts (transmission_id, kind, model, model_version, raw_text, normalized_text, confidence, words_json)
               VALUES (?, 'asr', ?, ?, ?, ?, ?, ?)""",
            (new_ids[t["transmission_id"]], t["model"], ASR_VERSION if edited else t["model_version"],
             inj.after if edited else t["raw_text"], inj.after if edited else t["normalized_text"],
             None if edited else t["confidence"], None if edited else t["words_json"]))
    first_of_y = next((tx.id for tx in _gold(conn, inj.second)), None) if inj.second is not None else None
    notes = {"original_recording_id": inj.recording_id, "second_recording_id": inj.second, "edit_kind": inj.edit_kind,
             "anchor_tx": new_ids[txs[inj.anchor].id], "trigger_tx": new_ids[txs[inj.trigger].id],
             "splice_tx": new_ids[first_of_y] if first_of_y else None, "runway": inj.runway, "seed": seed,
             "before": txs[inj.trigger].text, "after": inj.after,
             "deleted": txs[inj.deleted].text if inj.deleted is not None else None}
    conn.execute("UPDATE recordings SET notes = ? WHERE id = ?", (json.dumps(notes), rid))
    conn.commit()
    return rid


def synthetic_recordings(conn: sqlite3.Connection, valid_only: bool = False) -> list[dict]:
    """Every stored injection: {"recording_id", "external_id", **notes}. With `valid_only`, only those a human marked
    `valid: yes` (the positive set)."""
    rows = conn.execute(
        """SELECT r.id, r.external_id, r.notes FROM recordings r JOIN sources s ON s.id = r.source_id
           WHERE s.name = ? ORDER BY r.id""", (SOURCE,)).fetchall()
    out = [{"recording_id": r["id"], "external_id": r["external_id"], **json.loads(r["notes"])} for r in rows]
    return [o for o in out if o.get("valid") == "yes"] if valid_only else out


CHECK_COLUMNS = ["recording_id", "external_id", "edit_kind", "runway", "context", "before", "after", "valid", "notes"]


def check_rows(conn: sqlite3.Connection) -> list[dict]:
    """The human check sheet: one row per injection, with the lines from just before A to just after B (A and B
    marked, a splice's join shown), B before and after the edit, and any verdict already recorded."""
    rows = []
    for inj in synthetic_recordings(conn):
        txs = load_recording(conn, inj["recording_id"], "gold", TRANSCRIPT_MODEL)
        ids = [tx.id for tx in txs]
        a, b = ids.index(inj["anchor_tx"]), ids.index(inj["trigger_tx"])
        lines = []
        for k in range(max(0, a - 1), min(len(txs), b + 2)):
            if txs[k].id == inj.get("splice_tx"):
                lines.append(f"--- recording {inj['second_recording_id']} follows ---")
            mark = "A>" if k == a else "B>" if k == b else "  "
            lines.append(f"{mark} [{txs[k].role}] {txs[k].text}")
        if inj["deleted"]:
            lines.append(f"(deleted release: {inj['deleted']})")
        rows.append({"recording_id": inj["recording_id"], "external_id": inj["external_id"], "edit_kind": inj["edit_kind"],
                     "runway": inj["runway"], "context": "\n".join(lines), "before": inj["before"], "after": inj["after"],
                     "valid": inj.get("valid", ""), "notes": inj.get("check_notes", "")})
    return rows


def apply_check(conn: sqlite3.Connection, rows: list[dict]) -> dict[str, int]:
    """Record each row's `valid` (yes | no; blank = not checked yet) and `notes` in the injection's recording notes.
    Returns counts of yes, no and blank. Raises ValueError on any other value, before writing anything."""
    counts = {"yes": 0, "no": 0, "": 0}
    for r in rows:
        v = (r.get("valid") or "").strip().lower()
        if v not in counts:
            raise ValueError(f"recording {r['recording_id']}: valid must be yes, no or blank, not {r['valid']!r}")
        counts[v] += 1
    for r in rows:
        notes = json.loads(conn.execute("SELECT notes FROM recordings WHERE id = ?", (int(r["recording_id"]),)).fetchone()[0])
        v = (r.get("valid") or "").strip().lower()
        if v:
            notes["valid"] = v
        else:
            notes.pop("valid", None)
        notes["check_notes"] = r.get("notes") or ""
        conn.execute("UPDATE recordings SET notes = ? WHERE id = ?", (json.dumps(notes), int(r["recording_id"])))
    conn.commit()
    return counts
