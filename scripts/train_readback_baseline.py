#!/usr/bin/env python3
"""Evaluate the rule baseline and a feature-based logistic regression on data/readback/{train,test}.jsonl.

Usage:
    python scripts/train_readback_baseline.py [--data data/readback] [--report docs/results/readback-baseline.md]
"""
import argparse
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from atcdb.readback_model import evaluate, load_examples, predict_logreg, rule_predict, train_logreg  # noqa: E402


def fmt(m):
    return f"n={m['n']} acc={100*m['accuracy']:.1f}% P={100*m['precision']:.1f}% R={100*m['recall']:.1f}% F1={100*m['f1']:.1f}%"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data", type=Path, default=ROOT / "data/readback")
    ap.add_argument("--report", type=Path)
    args = ap.parse_args()
    train, test = load_examples(args.data)
    model = train_logreg(train)
    y = [e["label"] for e in test]
    preds = {"rules": [rule_predict(e) for e in test], "logreg": list(predict_logreg(model, test))}
    lines = [f"# Readback consistency — baselines (train {len(train)}, test {len(test)} examples)", ""]
    for name, p in preds.items():
        lines += [f"## {name}", "", f"- overall: {fmt(evaluate(y, p))}"]
        for key in ("source", "item_kind"):
            groups = defaultdict(lambda: ([], []))
            for e, yy, pp in zip(test, y, p):
                groups[e[key]][0].append(yy); groups[e[key]][1].append(pp)
            for k, (yt, yp) in sorted(groups.items()):
                lines.append(f"- {key}={k}: {fmt(evaluate(yt, yp))}")
        lines.append("")
    lines += ["> Caveat: labels for natural positives and synthetic negatives are derived from the same rules,",
              "> so the rule baseline is near-perfect by construction on those. Only the human-labelled",
              "> evaluation sheet (data/labels/) can show whether a model beats the rules.", ""]
    text = "\n".join(lines)
    print(text)
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(text)


if __name__ == "__main__":
    main()
