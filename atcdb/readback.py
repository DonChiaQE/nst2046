"""Instruction / readback pairs: extract mandatory read-back items from a controller transmission,
check whether the pilot's next transmission reads them back, and build a labelled dataset.

Mandatory read-back items follow ICAO Doc 4444 §4.5.7.5.1: frequencies, levels/altitudes,
headings, SSR codes (squawk), runway. Text is the normalised gold form (lowercase, digits as words).
"""
import json
import random
import re
import sqlite3
from collections import defaultdict

D = r"(?:zero|one|two|three|four|five|six|seven|eight|nine)"
DIGIT_WORDS = "zero one two three four five six seven eight nine".split()

ITEM_PATTERNS = [
    ("frequency", re.compile(rf"\b({D} {D} {D} decimal {D}(?: {D})*)\b")),
    ("frequency", re.compile(rf"\bcontact (?:(?!{D}\b)[a-z]+ ){{1,2}}({D} {D} {D}(?: {D}){{1,3}})\b(?! decimal)")),
    ("level", re.compile(rf"\b(?:flight level|level) ({D} {D} {D}|{D} hundred|{D} thousand)\b")),
    ("altitude", re.compile(rf"\b({D} thousand(?: {D} hundred)?) feet\b")),
    ("heading", re.compile(rf"\bheading ({D} {D} {D})\b")),
    ("squawk", re.compile(rf"\bsqu?awk ({D} {D} {D} {D})\b")),
    # Two digit-words only, deliberately, and NOT switched by `parse_rules.make_parser`'s single-digit convention:
    # widening it would make the readback check see a runway item in the 110 ASR-truncated mentions ("runway three o")
    # that carry no designator, changing every published readback number for a convention no transcript here uses.
    # The cost is a real asymmetry -- under that convention the clearance side books "runway four left" while this
    # side cannot, so a runway read-back miss on a single-digit designator is not detected. See
    # tests/test_readback.py, the asymmetry test, and report §7.
    ("runway", re.compile(rf"\brunway ({D} {D}(?: left| right| centre| center)?)\b")),
]
CUE_RE = re.compile(r"\b(i say again|say again|confirm|correction|sorry|repeat|negative|standby)\b")
CALLSIGN_RUN_RE = re.compile(rf"\b{D}(?: {D}){{1,3}}\b")


def extract_items(text: str) -> list[tuple[str, str]]:
    """Mandatory read-back items in document order as (kind, value)."""
    found = []
    for kind, rx in ITEM_PATTERNS:
        for m in rx.finditer(text):
            found.append((m.start(1), kind, m.group(1)))
    found.sort()
    return [(k, v) for _, k, v in found]


def _accepted_forms(kind: str, value: str) -> list[str]:
    forms = [value, value.replace(" decimal", "")]
    if kind == "frequency":  # trailing zeros after the decimal are commonly dropped: 134.440 -> "one three four decimal four four"
        for f in list(forms):
            g = f
            while g.endswith(" zero") and len(g.split()) > 4:
                g = g[: -len(" zero")]
                forms.append(g)
    return forms


def check_readback(items: list[tuple[str, str]], readback: str) -> list[tuple[str, str, str]]:
    """For each instruction item: 'ok' if an accepted form appears in the readback, else 'missing'."""
    padded = f" {readback} "
    out = []
    for kind, value in items:
        ok = any(f" {f} " in padded for f in _accepted_forms(kind, value))
        out.append((kind, value, "ok" if ok else "missing"))
    return out


def shares_callsign(a: str, b: str) -> bool:
    """Crude same-aircraft test: the two texts share a run of 2-4 digit words."""
    return bool(set(CALLSIGN_RUN_RE.findall(a)) & set(CALLSIGN_RUN_RE.findall(b)))


def perturb_digit(readback: str, item_value: str, seed: int = 0) -> str:
    """Synthetic inconsistent readback: change one digit word inside the item as it appears in the readback."""
    words = readback.split()
    for form in _accepted_forms("frequency", item_value):
        fw = form.split()
        for i in range(len(words) - len(fw) + 1):
            if words[i:i + len(fw)] == fw:
                rng = random.Random(seed)
                digit_positions = [i + j for j, w in enumerate(fw) if w in DIGIT_WORDS]
                pos = rng.choice(digit_positions)
                words[pos] = rng.choice([d for d in DIGIT_WORDS if d != words[pos]])
                return " ".join(words)
    return readback


def build_readback_pairs(conn: sqlite3.Connection, gold_model: str = "human") -> int:
    """Upsert one row per adjacent controller->pilot turn within a recording (ids stay stable on rebuild)."""
    rows = conn.execute(
        """SELECT x.id, x.recording_id, x.start_s, x.end_s, x.speaker_role, g.normalized_text AS text
           FROM transmissions x JOIN transcripts g ON g.transmission_id = x.id AND g.kind = 'gold' AND g.model = ?
           ORDER BY x.recording_id, x.start_s, x.id""", (gold_model,)).fetchall()
    by_rec = defaultdict(list)
    for r in rows:
        by_rec[r["recording_id"]].append(r)
    inserted = 0
    for rec_id, turns in by_rec.items():
        for a, b in zip(turns, turns[1:]):
            if a["speaker_role"] != "controller" or b["speaker_role"] != "pilot":
                continue
            items = extract_items(a["text"])
            checked = check_readback(items, b["text"])
            n_missing = sum(1 for _, _, v in checked if v == "missing")
            verdict = "no_items" if not items else ("inconsistent" if n_missing else "consistent")
            cue = CUE_RE.search(b["text"])
            gap = (b["start_s"] - a["end_s"]) if a["end_s"] is not None and b["start_s"] is not None else None
            cur = conn.execute(
                """INSERT INTO readback_pairs (recording_id, instruction_tid, readback_tid, gold_model, gap_s,
                       same_aircraft, instruction_text, readback_text, clarification_cue, items_json, n_items, n_missing, rule_verdict)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT (instruction_tid, readback_tid, gold_model) DO UPDATE SET
                       gap_s = excluded.gap_s, same_aircraft = excluded.same_aircraft,
                       instruction_text = excluded.instruction_text, readback_text = excluded.readback_text,
                       clarification_cue = excluded.clarification_cue, items_json = excluded.items_json,
                       n_items = excluded.n_items, n_missing = excluded.n_missing, rule_verdict = excluded.rule_verdict""",
                (rec_id, a["id"], b["id"], gold_model, gap, int(shares_callsign(a["text"], b["text"])), a["text"], b["text"],
                 cue.group(1) if cue else None, json.dumps(checked), len(items), n_missing, verdict))
            inserted += cur.rowcount
    conn.commit()
    return inserted


def split_by_recording(pairs: list[dict], test_fraction: float = 0.2, seed: int = 0) -> list[str]:
    """Assign 'train'/'test' per pair so that all pairs of a recording share a split (no leakage)."""
    recs = sorted({p["recording_id"] for p in pairs})
    rng = random.Random(seed)
    rng.shuffle(recs)
    n_test = max(1, round(len(recs) * test_fraction)) if len(recs) > 1 else 0
    test = set(recs[:n_test])
    return ["test" if p["recording_id"] in test else "train" for p in pairs]


def make_examples(conn: sqlite3.Connection, seed: int = 0, gold_model: str = "human",
                  test_fraction: float = 0.2) -> list[dict]:
    """Labelled (instruction, readback, item) examples for the readback-consistency model.

    label 1 = item read back correctly (rule-verified natural pair)
    label 0 = 'natural' (rule says missing — noisy: clipped audio, paraphrase) or
              'synthetic' (a correct readback with one digit of the item changed)
    Split is assigned per recording so a recording never straddles train/test.
    """
    pairs = [dict(r) for r in conn.execute(
        "SELECT * FROM readback_pairs WHERE gold_model = ? AND same_aircraft = 1 AND n_items > 0 ORDER BY id",
        (gold_model,)).fetchall()]
    splits = split_by_recording(pairs, test_fraction=test_fraction, seed=seed)
    examples = []
    for p, split in zip(pairs, splits):
        base = {"pair_id": p["id"], "recording_id": p["recording_id"], "instruction": p["instruction_text"], "split": split}
        for i, (kind, value, verdict) in enumerate(json.loads(p["items_json"])):
            item = {**base, "item_kind": kind, "item_value": value}
            if verdict == "ok":
                examples.append({**item, "readback": p["readback_text"], "label": 1, "source": "natural"})
                perturbed = perturb_digit(p["readback_text"], value, seed=seed * 1_000_003 + p["id"] * 31 + i)
                if perturbed != p["readback_text"]:
                    examples.append({**item, "readback": perturbed, "label": 0, "source": "synthetic"})
            else:
                examples.append({**item, "readback": p["readback_text"], "label": 0, "source": "natural"})
    return examples


def sample_label_sheet(conn: sqlite3.Connection, n_consistent: int = 100, n_inconsistent: int = 80,
                       n_unmatched: int = 20, seed: int = 0, gold_model: str = "human") -> list[dict]:
    """Stratified sample of pairs for human judgment. Rule verdicts are deliberately NOT included
    (they are what the human labels will be compared against)."""
    rng = random.Random(seed)

    def pick(where: str, n: int) -> list[sqlite3.Row]:
        rows = conn.execute(
            f"""SELECT p.id, p.instruction_text, p.readback_text, p.items_json, p.recording_id,
                       xi.clip_path AS instruction_clip, xr.clip_path AS readback_clip
                FROM readback_pairs p
                JOIN transmissions xi ON xi.id = p.instruction_tid
                JOIN transmissions xr ON xr.id = p.readback_tid
                WHERE p.gold_model = ? AND p.n_items > 0 AND {where} ORDER BY p.id""", (gold_model,)).fetchall()
        rng.shuffle(rows)
        return rows[:n]

    chosen = (pick("p.same_aircraft = 1 AND p.rule_verdict = 'consistent'", n_consistent)
              + pick("p.same_aircraft = 1 AND p.rule_verdict = 'inconsistent'", n_inconsistent)
              + pick("p.same_aircraft = 0", n_unmatched))
    rng.shuffle(chosen)
    return [{
        "pair_id": r["id"], "recording_id": r["recording_id"],
        "instruction": r["instruction_text"], "readback": r["readback_text"],
        "items": "; ".join(f"{k}: {v}" for k, v, _ in json.loads(r["items_json"])),
        "instruction_clip": r["instruction_clip"], "readback_clip": r["readback_clip"],
        "human_label": "", "notes": "",
    } for r in chosen]
