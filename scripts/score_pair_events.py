#!/usr/bin/env python3
"""Score the rules parser and the Claude parser against human event labels on the readback sheet's instructions.

The readback sheet (data/labels/readback_sheet_A.csv) came back labelled with each instruction's runway events
(`land <three one> [csa one two three]`, `handoff <tower> [...]`, `noop`) instead of readback consistency. This script
reads those labels as event labels for the 200 instruction transmissions, converts them to the event-sheet syntax of
atcdb/event_labels.py, parses the same transmissions with each parser (gold transcripts, `role` context, through the
events cache) and scores the match. The rules parser (`--model rules`) is free; the Claude models are billed on a cache
miss. It is a supplementary parser check, not the Level 1 measure: the pairs are not a
uniform sample, and most come from approach/radar recordings rather than the replayable tower recordings.

Usage:
    python scripts/score_pair_events.py --labels ~/Downloads/readback_sheet_A.csv --dry-run
    python scripts/score_pair_events.py --labels ~/Downloads/readback_sheet_A.csv [--model rules] [--workers 8]

    python scripts/score_pair_events.py --cases

Writes data/labels/pair_events_A.csv (the converted labels) and data/eval/pair_events/<model>.jsonl (per-pair rows).
`--model` is repeatable; without it, the rules parser and both Claude models are scored. Every run, and `--cases` alone
(no parsing, free), also writes docs/results/extraction-pair-events-cases.csv: each instruction's outcome under every
model that has rows, with kinds and runways but no transcript text or callsigns, since the per-pair rows are git-ignored.
"""
import argparse
import csv
import json
import re
import sys
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from atcdb import parse_llm  # noqa: E402
from atcdb.engine import Handoff, NoOp, normalize_runway  # noqa: E402
from atcdb.event_labels import parse_event_cell  # noqa: E402
from atcdb.parsing import KINDS, Context, Transmission  # noqa: E402
from atcdb.replay import get_events  # noqa: E402
from atcdb.schema import connect  # noqa: E402

LABEL_RE = re.compile(r"^(land|takeoff|luaw|cross|hold short|hold_short|handoff) <([^>]*)> \[([^\]]*)\]$")
CONTEXT = "role"
MODELS = ("rules", *parse_llm.MODELS)


def parser_of(model: str) -> str:
    return "rule" if model == "rules" else "llm"


def convert_label(label: str) -> str:
    """One sheet label (`kind <runway or target> [callsign]`, or `noop`) as an event-sheet cell."""
    label = " ".join(label.split())
    if label == "noop":
        return "noop"
    m = LABEL_RE.match(label)
    if not m:
        raise ValueError(f"unrecognised label {label!r}")
    kind, arg, callsign = m.group(1).replace(" ", "_"), m.group(2).strip(), m.group(3).strip()
    callsign = "" if callsign == "?" else callsign
    if kind != "handoff":
        arg = normalize_runway(arg)
        if not arg:
            raise ValueError(f"runway in {label!r} does not normalise")
    return " ".join(p for p in (kind, arg, callsign) if p)


def key(e) -> tuple[str, str | None]:
    """What an event must agree on to count as the same event: kind and runway (a handoff's target is scored apart)."""
    return KINDS[type(e)], getattr(e, "runway", None)


def score_pair(gold: list, pred: list) -> dict:
    """Greedy multiset match on `key`; matched pairs are then checked for callsign and handoff target."""
    pred = [e for e in pred if not isinstance(e, NoOp)]
    left = list(pred)
    matched, missed = [], []
    for g in gold:
        hit = next((p for p in left if key(p) == key(g)), None)
        if hit is None:
            missed.append(g)
        else:
            left.remove(hit)
            matched.append((g, hit))
    return {"matched": matched, "missed": missed, "extra": left}


def describe(e) -> str:
    kind, runway = key(e)
    arg = runway or (e.to if isinstance(e, Handoff) else "")
    return " ".join(p for p in (kind, arg, f"[{e.callsign}]" if e.callsign else "[]") if p)


def load_pairs(conn, labels_path: Path) -> list[dict]:
    rows = list(csv.DictReader(labels_path.open(newline="", encoding="utf-8-sig")))
    pairs = []
    for r in rows:
        p = conn.execute(
            """SELECT x.id, x.start_s, x.speaker_role, t.id AS transcript_id, t.normalized_text
               FROM readback_pairs rp JOIN transmissions x ON x.id = rp.instruction_tid
               JOIN transcripts t ON t.id = (SELECT id FROM transcripts WHERE transmission_id = x.id AND kind = 'gold'
                                             ORDER BY id LIMIT 1)
               WHERE rp.id = ?""", (int(r["pair_id"]),)).fetchone()
        tx = Transmission(id=p["id"], transcript_id=p["transcript_id"], text=p["normalized_text"], role=p["speaker_role"],
                          start_s=p["start_s"] or 0.0)
        cell = convert_label(r["human_label"])
        pairs.append({"pair_id": int(r["pair_id"]), "recording_id": int(r["recording_id"]), "tx": tx, "cell": cell,
                      "gold": parse_event_cell(cell), "notes": r["notes"]})
    return pairs


def write_converted(pairs: list[dict], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["pair_id", "transmission_id", "recording_id", "text", "events", "notes"])
        for p in pairs:
            w.writerow([p["pair_id"], p["tx"].id, p["recording_id"], p["tx"].text, p["cell"], p["notes"]])


CASES = ROOT / "docs/results/extraction-pair-events-cases.csv"
CALLSIGN_RE = re.compile(r" \[[^\]]*\]")


def write_cases(out_dir: Path, path: Path = CASES) -> None:
    """One row per instruction: `exact`, or what the model missed and invented (kind and runway, callsign dropped)."""
    by_model = {f.stem: {r["pair_id"]: r for r in map(json.loads, f.open())} for f in sorted(out_dir.glob("*.jsonl"))}
    pair_ids = sorted(set().union(*by_model.values())) if by_model else []

    def cell(r: dict | None) -> str:
        if r is None:
            return "not_run"
        parts = [f"{label} {CALLSIGN_RE.sub('', e)}" for label, key_ in (("missed", "missed"), ("invented", "extra"))
                 for e in r[key_]]
        return "; ".join(parts) or "exact"

    with path.open("w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["pair_id", *by_model])
        for pid in pair_ids:
            w.writerow([pid, *(cell(rows.get(pid)) for rows in by_model.values())])
    print(f"wrote {path} ({len(pair_ids)} instructions, {len(by_model)} models)")


def report(model: str, results: list[dict]) -> None:
    tp, fn, fp = Counter(), Counter(), Counter()
    cs_ok = cs_n = to_ok = to_n = 0
    noop = Counter()
    for r in results:
        s = r["score"]
        for g, p in s["matched"]:
            tp[key(g)[0]] += 1
            cs_n += 1
            cs_ok += g.callsign == p.callsign
            if isinstance(g, Handoff):
                to_n += 1
                to_ok += g.to == p.to
        for g in s["missed"]:
            fn[key(g)[0]] += 1
        for p in s["extra"]:
            fp[key(p)[0]] += 1
        gold_empty, pred_empty = not r["gold"], not [e for e in r["pred"] if not isinstance(e, NoOp)]
        noop[("noop" if gold_empty else "event", "noop" if pred_empty else "event")] += 1
    exact = sum(1 for r in results if not r["score"]["missed"] and not r["score"]["extra"])
    print(f"\n== {model} (context {CONTEXT}, gold transcripts, {len(results)} instructions) ==")
    print(f"transmissions with exactly the labelled events (kind + runway): {exact}/{len(results)}")
    print(f"human noop -> parser noop {noop['noop', 'noop']}, parser event {noop['noop', 'event']}; "
          f"human event -> parser event {noop['event', 'event']}, parser noop {noop['event', 'noop']}")
    print(f"{'kind':<12}{'TP':>5}{'FN':>5}{'FP':>5}{'recall':>9}{'precision':>11}")
    for k in sorted(set(tp) | set(fn) | set(fp)):
        rec = tp[k] / (tp[k] + fn[k]) if tp[k] + fn[k] else float("nan")
        prec = tp[k] / (tp[k] + fp[k]) if tp[k] + fp[k] else float("nan")
        print(f"{k:<12}{tp[k]:>5}{fn[k]:>5}{fp[k]:>5}{rec:>9.2f}{prec:>11.2f}")
    T, N, P = sum(tp.values()), sum(fn.values()), sum(fp.values())
    print(f"{'all':<12}{T:>5}{N:>5}{P:>5}{T / (T + N):>9.2f}{T / (T + P):>11.2f}")
    print(f"callsign exact on matched events: {cs_ok}/{cs_n}; handoff target agrees: {to_ok}/{to_n}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--labels", type=Path)
    ap.add_argument("--db", type=Path, default=ROOT / "data/atc.sqlite")
    ap.add_argument("--model", action="append", choices=MODELS)
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--cases", action="store_true", help="only rebuild the case table from the stored rows")
    args = ap.parse_args()
    models = args.model or list(MODELS)
    out_dir = ROOT / "data/eval/pair_events"
    if args.cases:
        write_cases(out_dir)
        return
    if args.labels is None:
        ap.error("--labels is required unless --cases")

    conn = connect(args.db)
    pairs = load_pairs(conn, args.labels)
    write_converted(pairs, ROOT / "data/labels/pair_events_A.csv")
    print(f"{len(pairs)} labelled instructions; converted labels in data/labels/pair_events_A.csv")
    if args.dry_run:
        for m in (m for m in models if parser_of(m) == "llm"):
            prompts = [parse_llm.render_prompt(p["tx"], Context(mode=CONTEXT, role=p["tx"].role)) for p in pairs]
            print(f"{m}: about ${parse_llm.estimate_cost(m, prompts):.2f} if nothing is cached")
        return

    def one(model: str, p: dict) -> dict:
        c = connect(args.db)
        try:
            pred = get_events(c, p["tx"], parser_of(model), Context(mode=CONTEXT, role=p["tx"].role), model=model)
        finally:
            c.close()
        return {**p, "pred": pred, "score": score_pair(p["gold"], pred)}

    out_dir.mkdir(parents=True, exist_ok=True)
    for model in models:
        with ThreadPoolExecutor(args.workers) as pool:
            results = list(pool.map(lambda p: one(model, p), pairs))
        with (out_dir / f"{model}.jsonl").open("w") as fh:
            for r in results:
                s = r["score"]
                fh.write(json.dumps({"pair_id": r["pair_id"], "text": r["tx"].text, "human": r["cell"],
                                     "parsed": [describe(e) for e in r["pred"] if not isinstance(e, NoOp)],
                                     "missed": [describe(e) for e in s["missed"]],
                                     "extra": [describe(e) for e in s["extra"]]}) + "\n")
        report(model, results)
    write_cases(out_dir)


if __name__ == "__main__":
    main()
