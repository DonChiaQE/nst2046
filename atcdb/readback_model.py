"""Readback-consistency models: rule baseline and a feature-based logistic regression.

An example is {"instruction", "readback", "item_kind", "item_value", "label", ...}; label 1 = the
item was read back correctly.
"""
import json
from pathlib import Path

import numpy as np

from atcdb.readback import DIGIT_WORDS, _accepted_forms, check_readback

ITEM_KINDS = ["frequency", "level", "altitude", "heading", "squawk", "runway"]


def rule_predict(example: dict) -> int:
    (_, _, verdict), = check_readback([(example["item_kind"], example["item_value"])], example["readback"])
    return 1 if verdict == "ok" else 0


def evaluate(y_true, y_pred) -> dict:
    y_true, y_pred = list(y_true), list(y_pred)
    tp = sum(1 for t, p in zip(y_true, y_pred) if t == 1 and p == 1)
    fp = sum(1 for t, p in zip(y_true, y_pred) if t == 0 and p == 1)
    fn = sum(1 for t, p in zip(y_true, y_pred) if t == 1 and p == 0)
    n = len(y_true)
    acc = sum(1 for t, p in zip(y_true, y_pred) if t == p) / n if n else 0.0
    prec = tp / (tp + fp) if tp + fp else 0.0
    rec = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * prec * rec / (prec + rec) if prec + rec else 0.0
    return {"n": n, "accuracy": acc, "precision": prec, "recall": rec, "f1": f1}


def load_examples(directory: Path) -> tuple[list[dict], list[dict]]:
    def read(name):
        with (Path(directory) / f"{name}.jsonl").open() as fh:
            return [json.loads(line) for line in fh if line.strip()]
    return read("train"), read("test")


def _digits(words: list[str]) -> list[str]:
    return [w for w in words if w in DIGIT_WORDS]


def _lcs(a: list[str], b: list[str]) -> int:
    dp = [[0] * (len(b) + 1) for _ in range(len(a) + 1)]
    for i, x in enumerate(a, 1):
        for j, y in enumerate(b, 1):
            dp[i][j] = dp[i - 1][j - 1] + 1 if x == y else max(dp[i - 1][j], dp[i][j - 1])
    return dp[-1][-1]


def features(example: dict) -> list[float]:
    """Alignment features between the instruction item and the readback."""
    item = _digits(example["item_value"].split())
    rb_words = example["readback"].split()
    rb = _digits(rb_words)
    n = len(item)
    # best contiguous window match on the digit sequence
    best = 0.0
    if n and len(rb) >= n:
        for i in range(len(rb) - n + 1):
            best = max(best, sum(1 for a, b in zip(item, rb[i:i + n]) if a == b) / n)
    lcs = _lcs(item, rb) / n if n else 0.0
    exact = float(any(f" {f} " in f" {example['readback']} " for f in _accepted_forms(example["item_kind"], example["item_value"])))
    item_set_cov = len(set(item) & set(rb)) / len(set(item)) if item else 0.0
    kind = [1.0 if example["item_kind"] == k else 0.0 for k in ITEM_KINDS]
    return [exact, best, lcs, item_set_cov, float(n), float(len(rb)), float(len(rb_words)),
            float("decimal" in rb_words), float("correction" in rb_words or "say again" in example["readback"])] + kind


def train_logreg(examples: list[dict], seed: int = 0):
    from sklearn.linear_model import LogisticRegression
    from sklearn.pipeline import make_pipeline
    from sklearn.preprocessing import StandardScaler
    X = np.array([features(e) for e in examples])
    y = np.array([e["label"] for e in examples])
    model = make_pipeline(StandardScaler(), LogisticRegression(max_iter=1000, class_weight="balanced", random_state=seed))
    model.fit(X, y)
    return model


def predict_logreg(model, examples: list[dict]) -> np.ndarray:
    return model.predict(np.array([features(e) for e in examples]))
