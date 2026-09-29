"""Per-transmission surface-clearance extraction: the schema, the gold-sheet format, and the scoring.

One transmission -> zero or more Extractions. Two scores:
  score 1  did the model get `change` right (any surface-related instruction present?)
  score 2  on transmissions where gold has a change: are callsign / surface / kind right?
"""
import csv
import random
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from atcdb.engine import Event, Handoff, RunwayInstruction, normalize_runway
from atcdb.parsing import KINDS

BLOCK_KINDS = ("LAND", "TAKEOFF", "LUAW", "CROSS")
HOLD_KINDS = ("HOLD_SHORT",)
CLEAR_KINDS = ("VACATED", "HANDOFF", "GO_AROUND", "CANCEL")
ALL_KINDS = BLOCK_KINDS + HOLD_KINDS + CLEAR_KINDS
SURFACE_TYPES = ("runway", "taxiway")
FIELDS = ("callsign", "surface_type", "surface", "kind")

GOLD_COLUMNS = ["transmission_id", "change", "callsign", "surface_type", "surface", "kind", "conditional", "notes"]
UNKNOWN = "?"   # a labeller could not tell; the field is skipped in scoring


def effect(kind: str) -> str:
    if kind in BLOCK_KINDS:
        return "block"
    if kind in CLEAR_KINDS:
        return "clear"
    if kind in HOLD_KINDS:
        return "hold"
    raise ValueError(f"unknown kind {kind!r}")


@dataclass(frozen=True)
class Extraction:
    callsign: str            # normalized words, e.g. "csa three eight whiskey"; "" unknown
    surface_type: str        # runway | taxiway | ""  (HANDOFF / GO_AROUND / VACATED may have none)
    surface: str             # "13", "24L", "A" ...; "" if none
    kind: str                # one of ALL_KINDS
    conditional: bool = False

    @property
    def change(self) -> bool:
        return True


def normalize_surface(surface_type: str, text: str) -> str:
    text = (text or "").strip()
    if not text:
        return ""
    if surface_type == "runway":
        return normalize_runway(text) or text.upper()
    return text.upper().replace("TAXIWAY", "").strip()


def norm_callsign(cs: str) -> str:
    return " ".join((cs or "").lower().split())


# --- engine events -> extractions ------------------------------------------------------------

def events_to_extractions(events: list[Event]) -> list[Extraction]:
    """Map the engine's typed events onto the extraction schema. READBACK and NOOP are not changes."""
    out = []
    for e in events:
        kind = KINDS[type(e)]
        if kind in ("READBACK", "NOOP"):
            continue
        if isinstance(e, RunwayInstruction):
            out.append(Extraction(norm_callsign(e.callsign), "runway", e.runway, kind))
        elif isinstance(e, Handoff):
            out.append(Extraction(norm_callsign(e.callsign), "", "", "HANDOFF"))
        else:
            out.append(Extraction(norm_callsign(e.callsign), "", "", kind))
    return out


# --- sheet rows <-> extractions ---------------------------------------------------------------

def _split(cell: str, n: int) -> list[str]:
    parts = [p.strip() for p in (cell or "").split(";")]
    if parts == [""]:
        parts = []
    if n and len(parts) < n:
        parts += [""] * (n - len(parts))
    return parts


def row_to_extractions(row: dict[str, str]) -> list[Extraction] | None:
    """A gold or prediction row -> its extractions. None if the row is unlabelled (change blank)."""
    change = (row.get("change") or "").strip().lower()
    if change == "":
        return None
    if change in ("false", "0", "no", "n"):
        return []
    kinds = _split(row.get("kind", ""), 0)
    n = len(kinds)
    callsigns = _split(row.get("callsign", ""), n)
    types = _split(row.get("surface_type", ""), n)
    surfaces = _split(row.get("surface", ""), n)
    conds = _split(row.get("conditional", ""), n)
    out = []
    for i, kind in enumerate(kinds):
        kind = kind.strip().upper()
        if kind not in ALL_KINDS:
            raise ValueError(f"transmission {row.get('transmission_id')}: unknown kind {kind!r}")
        st = types[i].strip().lower()
        if st and st not in SURFACE_TYPES:
            raise ValueError(f"transmission {row.get('transmission_id')}: unknown surface_type {st!r}")
        out.append(Extraction(norm_callsign(callsigns[i]) if callsigns[i] != UNKNOWN else UNKNOWN,
                              st, normalize_surface(st, surfaces[i]) if surfaces[i] != UNKNOWN else UNKNOWN,
                              kind, conds[i].strip().lower() in ("true", "1", "yes", "y")))
    return out


def extractions_to_row(transmission_id: int | str, exs: list[Extraction]) -> dict[str, str]:
    return {
        "transmission_id": str(transmission_id),
        "change": "True" if exs else "False",
        "callsign": ";".join(e.callsign for e in exs),
        "surface_type": ";".join(e.surface_type for e in exs),
        "surface": ";".join(e.surface for e in exs),
        "kind": ";".join(e.kind for e in exs),
        "conditional": ";".join("True" if e.conditional else "False" for e in exs),
        "notes": "",
    }


def read_sheet(path: Path) -> dict[str, dict[str, str]]:
    with Path(path).open(newline="") as fh:
        return {r["transmission_id"]: r for r in csv.DictReader(fh)}


def write_sheet(path: Path, rows: list[dict[str, str]], columns: list[str]) -> None:
    with Path(path).open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=columns, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)


# --- scoring ----------------------------------------------------------------------------------

def _field_matches(g: Extraction, p: Extraction) -> dict[str, bool | None]:
    """None = gold field unknown, skipped."""
    out: dict[str, bool | None] = {}
    for f in FIELDS:
        gv, pv = getattr(g, f), getattr(p, f)
        out[f] = None if gv == UNKNOWN else (gv == pv)
    return out


def _align(gold: list[Extraction], pred: list[Extraction]) -> list[tuple[Extraction, Extraction | None]]:
    """Greedy one-to-one alignment by number of matching fields; unmatched gold pairs with None."""
    remaining = list(pred)
    pairs = []
    for g in gold:
        best, best_n = None, -1
        for p in remaining:
            n = sum(1 for v in _field_matches(g, p).values() if v)
            if n > best_n:
                best, best_n = p, n
        if best is not None:
            remaining.remove(best)
        pairs.append((g, best))
    return pairs


@dataclass
class TxScore:
    transmission_id: str
    gold_change: bool
    pred_change: bool
    field_hits: dict[str, int]
    field_totals: dict[str, int]
    exact: bool | None        # None when gold has no change


def score_transmission(tid: str, gold: list[Extraction], pred: list[Extraction]) -> TxScore:
    hits = {f: 0 for f in FIELDS}
    totals = {f: 0 for f in FIELDS}
    exact: bool | None = None
    if gold:
        for g, p in _align(gold, pred):
            for f, m in _field_matches(g, p if p else Extraction("", "", "", "LAND")).items():
                if m is None:
                    continue
                totals[f] += 1
                hits[f] += int(bool(m) and p is not None)
        exact = len(pred) == len(gold) and all(v == t for v, t in zip(hits.values(), totals.values()))
    return TxScore(tid, bool(gold), bool(pred), hits, totals, exact)


def summarize(scores: list[TxScore], weights: dict[str, float] | None = None) -> dict:
    weights = weights or {f: 1.0 for f in FIELDS}
    n = len(scores)
    tp = sum(s.gold_change and s.pred_change for s in scores)
    fp = sum((not s.gold_change) and s.pred_change for s in scores)
    fn = sum(s.gold_change and (not s.pred_change) for s in scores)
    tn = n - tp - fp - fn
    prec = tp / (tp + fp) if tp + fp else 0.0
    rec = tp / (tp + fn) if tp + fn else 0.0
    change = {"n": n, "accuracy": (tp + tn) / n if n else 0.0, "precision": prec, "recall": rec,
              "f1": 2 * prec * rec / (prec + rec) if prec + rec else 0.0, "tp": tp, "fp": fp, "fn": fn, "tn": tn}
    pos = [s for s in scores if s.gold_change]
    fields = {}
    for f in FIELDS:
        h = sum(s.field_hits[f] for s in pos)
        t = sum(s.field_totals[f] for s in pos)
        fields[f] = {"hits": h, "n": t, "accuracy": h / t if t else 0.0}
    wsum = sum(weights[f] for f in FIELDS if fields[f]["n"])
    content = {
        "n": len(pos),
        "exact_match": sum(bool(s.exact) for s in pos) / len(pos) if pos else 0.0,
        "fields": fields,
        "weighted": sum(weights[f] * fields[f]["accuracy"] for f in FIELDS if fields[f]["n"]) / wsum if wsum else 0.0,
        "weights": dict(weights),
    }
    return {"change": change, "content": content}


def bootstrap(scores: list[TxScore], stat, n_resamples: int = 1000, seed: int = 0) -> tuple[float, float]:
    """95% CI of `stat(summary)` by resampling transmissions."""
    rng = random.Random(seed)
    vals = []
    for _ in range(n_resamples):
        sample = [scores[rng.randrange(len(scores))] for _ in scores]
        vals.append(stat(summarize(sample)))
    vals.sort()
    return vals[int(0.025 * len(vals))], vals[int(0.975 * len(vals)) - 1]


def evaluate(gold_rows: dict[str, dict[str, str]], pred_rows: dict[str, dict[str, str]],
             weights: dict[str, float] | None = None, n_resamples: int = 1000, seed: int = 0) -> dict:
    scores = []
    skipped = Counter()
    for tid, grow in gold_rows.items():
        gold = row_to_extractions(grow)
        if gold is None:
            skipped["unlabelled"] += 1
            continue
        prow = pred_rows.get(tid)
        if prow is None:
            skipped["no_prediction"] += 1
            continue
        pred = row_to_extractions(prow) or []
        scores.append(score_transmission(tid, gold, pred))
    summary = summarize(scores, weights)
    if scores and n_resamples:
        summary["change"]["accuracy_ci"] = bootstrap(scores, lambda s: s["change"]["accuracy"], n_resamples, seed)
        summary["change"]["f1_ci"] = bootstrap(scores, lambda s: s["change"]["f1"], n_resamples, seed)
        summary["content"]["exact_match_ci"] = bootstrap(scores, lambda s: s["content"]["exact_match"], n_resamples, seed)
        summary["content"]["weighted_ci"] = bootstrap(scores, lambda s: s["content"]["weighted"], n_resamples, seed)
    summary["skipped"] = dict(skipped)
    summary["per_transmission"] = scores
    return summary
