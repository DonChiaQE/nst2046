#!/usr/bin/env python3
"""Fine-tune a BERT cross-encoder for readback consistency.

Input text:  "<instruction> [SEP] <item_kind>: <item_value> [SEP] <readback>"  ->  label 1/0
Usage:
    python scripts/train_readback_bert.py [--model bert-base-uncased] [--epochs 3] [--batch 16] [--lr 2e-5]
                                          [--max-steps N] [--out data/models/readback-bert] [--report docs/results/readback-bert.md]
Runs on Apple GPU (MPS) when available.
"""
import argparse
import sys
import time
from collections import defaultdict
from pathlib import Path

import numpy as np
import torch
from torch.utils.data import DataLoader, Dataset

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from atcdb.readback_model import evaluate, load_examples  # noqa: E402


def text_of(e: dict) -> str:
    return f"{e['instruction']} [SEP] {e['item_kind']}: {e['item_value']} [SEP] {e['readback']}"


class PairDataset(Dataset):
    def __init__(self, examples, tokenizer, max_len=96):
        self.enc = tokenizer([text_of(e) for e in examples], truncation=True, max_length=max_len, padding="max_length", return_tensors="pt")
        self.labels = torch.tensor([e["label"] for e in examples])

    def __len__(self):
        return len(self.labels)

    def __getitem__(self, i):
        return {k: v[i] for k, v in self.enc.items()}, self.labels[i]


def predict(model, loader, device):
    model.eval()
    out = []
    with torch.no_grad():
        for batch, _ in loader:
            logits = model(**{k: v.to(device) for k, v in batch.items()}).logits
            out.extend(logits.argmax(-1).cpu().tolist())
    return out


def main() -> None:
    from transformers import AutoModelForSequenceClassification, AutoTokenizer
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data", type=Path, default=ROOT / "data/readback")
    ap.add_argument("--model", default="bert-base-uncased")
    ap.add_argument("--epochs", type=int, default=3)
    ap.add_argument("--batch", type=int, default=16)
    ap.add_argument("--lr", type=float, default=2e-5)
    ap.add_argument("--max-steps", type=int, help="stop early (smoke test)")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--out", type=Path, default=ROOT / "data/models/readback-bert")
    ap.add_argument("--report", type=Path)
    args = ap.parse_args()

    torch.manual_seed(args.seed)
    device = "mps" if torch.backends.mps.is_available() else "cpu"
    train, test = load_examples(args.data)
    tok = AutoTokenizer.from_pretrained(args.model)
    model = AutoModelForSequenceClassification.from_pretrained(args.model, num_labels=2, ignore_mismatched_sizes=True).to(device)
    train_loader = DataLoader(PairDataset(train, tok), batch_size=args.batch, shuffle=True)
    test_loader = DataLoader(PairDataset(test, tok), batch_size=64)
    opt = torch.optim.AdamW(model.parameters(), lr=args.lr)
    step, t0 = 0, time.time()
    for epoch in range(args.epochs):
        model.train()
        for batch, labels in train_loader:
            loss = model(**{k: v.to(device) for k, v in batch.items()}, labels=labels.to(device)).loss
            loss.backward(); opt.step(); opt.zero_grad()
            step += 1
            if step % 50 == 0:
                print(f"epoch {epoch+1} step {step} loss {loss.item():.4f} ({time.time()-t0:.0f}s)", flush=True)
            if args.max_steps and step >= args.max_steps:
                break
        if args.max_steps and step >= args.max_steps:
            break
    preds = predict(model, test_loader, device)
    y = [e["label"] for e in test]
    lines = [f"# Readback consistency — BERT cross-encoder ({args.model}, {step} steps, {time.time()-t0:.0f}s on {device})", ""]
    m = evaluate(y, preds)
    lines.append(f"- overall: n={m['n']} acc={100*m['accuracy']:.1f}% P={100*m['precision']:.1f}% R={100*m['recall']:.1f}% F1={100*m['f1']:.1f}%")
    for key in ("source", "item_kind"):
        groups = defaultdict(lambda: ([], []))
        for e, yy, pp in zip(test, y, preds):
            groups[e[key]][0].append(yy); groups[e[key]][1].append(pp)
        for k, (yt, yp) in sorted(groups.items()):
            g = evaluate(yt, yp)
            lines.append(f"- {key}={k}: n={g['n']} acc={100*g['accuracy']:.1f}% F1={100*g['f1']:.1f}%")
    text = "\n".join(lines) + "\n"
    print(text)
    args.out.mkdir(parents=True, exist_ok=True)
    model.save_pretrained(args.out); tok.save_pretrained(args.out)
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(text)


if __name__ == "__main__":
    main()
