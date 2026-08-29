# Readback consistency — model comparison (29 Aug 2026)

Test set: 715 auto-labelled examples (387 natural, 328 synthetic one-digit perturbations), split by recording.

| Model | Overall acc | F1 | Natural acc | Synthetic negatives caught | Weakest item |
|---|---:|---:|---:|---:|---|
| Rules (exact / accepted forms) | 99.3% | 99.2% | 100% | 98.5% | frequency 97.9% |
| Logistic regression (alignment features) | 99.2% | 99.1% | 99.7% | 98.5% | frequency 97.4% |
| BERT cross-encoder, 3 epochs | 70.5% | 72.2% | 78.0% | 61.6% | squawk 43.5% |
| **BERT cross-encoder, 10 epochs, lr 3e-5** | **92.9%** | **92.6%** | **95.1%** | **90.2%** | frequency 83.1% |

Reading this honestly:
- The labels on this test set are *derived from the rules*, so rules ≈ 100% by construction and the
  numbers above measure how well each model imitates the rules — not which is better in reality.
- BERT went from 70% to 93% with more training (loss 0.67 → ~0.15); frequencies (long digit strings
  with "decimal") remain hardest. More synthetic negatives per positive and digit-aware features are the
  next levers if needed.
- The decisive comparison is on the human-labelled sheet (`data/labels/readback_sheet_A.csv`), where
  rules are expected to fail on paraphrase ("one fifty five"), reordering and clipped audio.
