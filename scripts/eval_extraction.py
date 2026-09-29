#!/usr/bin/env python3
"""Score a model's per-transmission surface-clearance extractions against the human gold sheet.

Two scores:
  1. change   -- did the model correctly say whether the transmission changes a surface's status
                 (accuracy, precision, recall, F1 over all transmissions)
  2. content  -- on transmissions where gold has a change: callsign / surface_type / surface / kind
                 per-field accuracy, exact-match rate, and a weighted aggregate

Usage:
    # score a predictions file (any model; same columns as the gold sheet)
    python scripts/eval_extraction.py data/labels/event_sheet_A.csv predictions.csv [--report docs/results/x.md]

    # or produce predictions from the rules parser first, with an adjustable context level
    python scripts/eval_extraction.py data/labels/event_sheet_A.csv --parser rule --context none
    python scripts/eval_extraction.py data/labels/event_sheet_A.csv --parser rule --context window --save-pred pred.csv

    # weights for the content aggregate (default equal); e.g. from docs/results/consequence-weights.md
    --weights callsign=0.1,surface_type=0.1,surface=0.5,kind=0.3

Predictions file columns: transmission_id, change, callsign, surface_type, surface, kind[, conditional].
Multiple events in one transmission are ';'-separated, aligned by position. See docs/eval-extraction.md.
"""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from atcdb.extraction import FIELDS, GOLD_COLUMNS, evaluate, events_to_extractions, extractions_to_row, read_sheet, write_sheet  # noqa: E402
from atcdb.parsing import CONTEXT_MODES, WINDOW, Context, Transmission  # noqa: E402


def context_from_row(row: dict[str, str], mode: str) -> Context:
    """Build the parser's context from the sheet's context columns, limited to `mode`."""
    if mode == "none":
        return Context(mode="none")
    role = row.get("speaker_role") or "unknown"
    if mode == "role":
        return Context(mode="role", role=role)
    history = []
    for i in range(WINDOW, 0, -1):
        cell = (row.get(f"prev_{i}") or "").strip()
        if cell:
            r, _, t = cell.partition(": ")
            history.append((r if t else "unknown", t or r))
    split = lambda s: tuple(x.strip() for x in (s or "").split(";") if x.strip())  # noqa: E731
    return Context(mode="window", role=role, history=tuple(history),
                   active_callsigns=split(row.get("active_callsigns")), active_runways=split(row.get("active_runways")))


def predict_with_parser(name: str, gold_rows: dict[str, dict[str, str]], mode: str) -> dict[str, dict[str, str]]:
    if name == "rule":
        from atcdb.parse_rules import parse
    else:
        raise SystemExit(f"unknown parser {name!r}; the LLM parser is not wired in yet")
    preds = {}
    for tid, row in gold_rows.items():
        tx = Transmission(id=int(tid), transcript_id=0, text=row.get("text", ""), role=row.get("speaker_role") or "unknown",
                          start_s=float(row.get("start_s") or 0.0))
        events = parse(tx, context_from_row(row, mode))
        preds[tid] = extractions_to_row(tid, events_to_extractions(events))
    return preds


def parse_weights(spec: str | None) -> dict[str, float] | None:
    if not spec:
        return None
    w = {f: 0.0 for f in FIELDS}
    for part in spec.split(","):
        k, _, v = part.partition("=")
        if k.strip() not in FIELDS:
            raise SystemExit(f"unknown field {k!r} in --weights")
        w[k.strip()] = float(v)
    return w


def format_report(result: dict, title: str) -> str:
    c, k = result["change"], result["content"]
    ci = lambda key, d: f" [{d[key][0]:.2f}, {d[key][1]:.2f}]" if key in d else ""  # noqa: E731
    lines = [f"# {title}", "",
             f"Transmissions scored: {c['n']} (skipped: {result['skipped'] or 'none'})", "",
             "## Score 1 - change detection", "",
             "| metric | value |", "|---|---|",
             f"| accuracy | {c['accuracy']:.3f}{ci('accuracy_ci', c)} |",
             f"| precision | {c['precision']:.3f} |",
             f"| recall | {c['recall']:.3f} |",
             f"| F1 | {c['f1']:.3f}{ci('f1_ci', c)} |",
             f"| TP / FP / FN / TN | {c['tp']} / {c['fp']} / {c['fn']} / {c['tn']} |", "",
             f"## Score 2 - content, on the {k['n']} transmissions with a gold change", "",
             "| field | hits / n | accuracy | weight |", "|---|---|---|---|"]
    for f in FIELDS:
        d = k["fields"][f]
        lines.append(f"| {f} | {d['hits']} / {d['n']} | {d['accuracy']:.3f} | {k['weights'][f]:.2f} |")
    lines += ["", f"Exact match (all events, all fields): {k['exact_match']:.3f}{ci('exact_match_ci', k)}",
              f"Weighted content score: {k['weighted']:.3f}{ci('weighted_ci', k)}", ""]
    by_role = result.get("by_role")
    if by_role:
        lines += ["## By speaker role", "", "| role | n | change acc | exact match |", "|---|---|---|---|"]
        for role, r in by_role.items():
            lines.append(f"| {role} | {r['change']['n']} | {r['change']['accuracy']:.3f} | {r['content']['exact_match']:.3f} |")
        lines.append("")
    return "\n".join(lines)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("gold", type=Path)
    ap.add_argument("predictions", type=Path, nargs="?")
    ap.add_argument("--parser", choices=["rule"], help="generate predictions with this parser instead of reading a file")
    ap.add_argument("--context", choices=CONTEXT_MODES, default="none", help="context given to --parser (default none)")
    ap.add_argument("--save-pred", type=Path, help="write the generated predictions here")
    ap.add_argument("--weights", help="field=weight,... for the content aggregate (default equal)")
    ap.add_argument("--resamples", type=int, default=1000)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--report", type=Path, help="write a markdown report here")
    ap.add_argument("--json", type=Path, help="write the full result as JSON here")
    args = ap.parse_args()

    gold = read_sheet(args.gold)
    if args.parser:
        preds = predict_with_parser(args.parser, gold, args.context)
        title = f"Extraction: {args.parser} parser, context={args.context}, gold={args.gold.name}"
        if args.save_pred:
            write_sheet(args.save_pred, list(preds.values()), [c for c in GOLD_COLUMNS if c != "notes"])
    elif args.predictions:
        preds = read_sheet(args.predictions)
        title = f"Extraction: {args.predictions.name} vs gold {args.gold.name}"
    else:
        raise SystemExit("give a predictions file or --parser")

    weights = parse_weights(args.weights)
    result = evaluate(gold, preds, weights, args.resamples, args.seed)
    roles = {r.get("speaker_role") for r in gold.values() if r.get("speaker_role")}
    if roles:
        result["by_role"] = {}
        for role in sorted(roles):
            sub = {t: r for t, r in gold.items() if r.get("speaker_role") == role}
            result["by_role"][role] = evaluate(sub, preds, weights, n_resamples=0)
    report = format_report(result, title)
    print(report)
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(report + "\n")
    if args.json:
        slim = {k: v for k, v in result.items() if k not in ("per_transmission", "by_role")}
        args.json.write_text(json.dumps(slim, indent=2))


if __name__ == "__main__":
    main()
