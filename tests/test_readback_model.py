import json

from atcdb.readback_model import (evaluate, load_examples, predict_logreg, rule_predict, train_logreg)

EX = [
    {"instruction": "contact rhein one three six decimal four zero five", "readback": "one three six decimal four zero five bye",
     "item_kind": "frequency", "item_value": "one three six decimal four zero five", "label": 1, "source": "natural", "split": "train"},
    {"instruction": "contact rhein one three six decimal four zero five", "readback": "one four six decimal four zero five bye",
     "item_kind": "frequency", "item_value": "one three six decimal four zero five", "label": 0, "source": "synthetic", "split": "train"},
    {"instruction": "descend flight level one hundred", "readback": "descending flight level one hundred swiss one two four",
     "item_kind": "level", "item_value": "one hundred", "label": 1, "source": "natural", "split": "train"},
    {"instruction": "descend flight level one hundred", "readback": "descending flight level one thousand swiss one two four",
     "item_kind": "level", "item_value": "one hundred", "label": 0, "source": "synthetic", "split": "train"},
    {"instruction": "runway three one cleared to land", "readback": "cleared to land three one lufthansa",
     "item_kind": "runway", "item_value": "three one", "label": 1, "source": "natural", "split": "test"},
    {"instruction": "runway three one cleared to land", "readback": "cleared to land one three lufthansa",
     "item_kind": "runway", "item_value": "three one", "label": 0, "source": "synthetic", "split": "test"},
]


def test_rule_predict_matches_check_readback_semantics():
    assert rule_predict(EX[0]) == 1
    assert rule_predict(EX[1]) == 0
    assert rule_predict(EX[5]) == 0


def test_evaluate_reports_accuracy_precision_recall_f1():
    m = evaluate([1, 1, 0, 0], [1, 0, 0, 1])
    assert m == {"n": 4, "accuracy": 0.5, "precision": 0.5, "recall": 0.5, "f1": 0.5}


def test_load_examples_reads_jsonl_splits(tmp_path):
    d = tmp_path / "rb"
    d.mkdir()
    for split in ("train", "test"):
        (d / f"{split}.jsonl").write_text("".join(json.dumps(e) + "\n" for e in EX if e["split"] == split))
    train, test = load_examples(d)
    assert len(train) == 4 and len(test) == 2


def test_logreg_learns_the_toy_task():
    model = train_logreg(EX[:4] * 5, seed=0)
    preds = predict_logreg(model, EX[4:])
    assert list(preds) == [1, 0]
