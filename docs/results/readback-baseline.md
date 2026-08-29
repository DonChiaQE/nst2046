# Readback consistency — baselines (train 3008, test 715 examples)

## rules

- overall: n=715 acc=99.3% P=98.5% R=100.0% F1=99.2%
- source=natural: n=387 acc=100.0% P=100.0% R=100.0% F1=100.0%
- source=synthetic: n=328 acc=98.5% P=0.0% R=0.0% F1=0.0%
- item_kind=altitude: n=22 acc=100.0% P=100.0% R=100.0% F1=100.0%
- item_kind=frequency: n=195 acc=97.9% P=95.3% R=100.0% F1=97.6%
- item_kind=heading: n=50 acc=100.0% P=100.0% R=100.0% F1=100.0%
- item_kind=level: n=247 acc=99.6% P=99.2% R=100.0% F1=99.6%
- item_kind=runway: n=178 acc=100.0% P=100.0% R=100.0% F1=100.0%
- item_kind=squawk: n=23 acc=100.0% P=100.0% R=100.0% F1=100.0%

## logreg

- overall: n=715 acc=99.2% P=98.5% R=99.7% F1=99.1%
- source=natural: n=387 acc=99.7% P=100.0% R=99.7% F1=99.8%
- source=synthetic: n=328 acc=98.5% P=0.0% R=0.0% F1=0.0%
- item_kind=altitude: n=22 acc=100.0% P=100.0% R=100.0% F1=100.0%
- item_kind=frequency: n=195 acc=97.4% P=95.3% R=98.8% F1=97.0%
- item_kind=heading: n=50 acc=100.0% P=100.0% R=100.0% F1=100.0%
- item_kind=level: n=247 acc=99.6% P=99.2% R=100.0% F1=99.6%
- item_kind=runway: n=178 acc=100.0% P=100.0% R=100.0% F1=100.0%
- item_kind=squawk: n=23 acc=100.0% P=100.0% R=100.0% F1=100.0%

> Caveat: labels for natural positives and synthetic negatives are derived from the same rules,
> so the rule baseline is near-perfect by construction on those. Only the human-labelled
> evaluation sheet (data/labels/) can show whether a model beats the rules.
