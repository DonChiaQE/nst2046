#!/usr/bin/env python3
"""Build instruction/readback pairs in the DB and export a labelled JSONL dataset.

Usage:
    python scripts/build_readback_dataset.py [--db data/atc.sqlite] [--out data/readback] [--seed 0]

Writes <out>/train.jsonl and <out>/test.jsonl (one example per line) and prints a census.
"""
import argparse
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from atcdb.readback import build_readback_pairs, make_examples  # noqa: E402
from atcdb.schema import init_db  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", type=Path, default=ROOT / "data/atc.sqlite")
    ap.add_argument("--out", type=Path, default=ROOT / "data/readback")
    ap.add_argument("--seed", type=int, default=0)
    args = ap.parse_args()
    conn = init_db(args.db)
    n_new = build_readback_pairs(conn)
    total = conn.execute("SELECT count(*) FROM readback_pairs").fetchone()[0]
    print(f"readback_pairs: {total} rows ({n_new} new)")
    print("  verdict x same_aircraft:", dict(Counter((r[0], r[1]) for r in
          conn.execute("SELECT rule_verdict, same_aircraft FROM readback_pairs").fetchall())))
    examples = make_examples(conn, seed=args.seed)
    args.out.mkdir(parents=True, exist_ok=True)
    for split in ("train", "test"):
        rows = [e for e in examples if e["split"] == split]
        with (args.out / f"{split}.jsonl").open("w") as fh:
            for e in rows:
                fh.write(json.dumps(e) + "\n")
        c = Counter((e["label"], e["source"]) for e in rows)
        print(f"  {split}: {len(rows)} examples  pos={c[(1, 'natural')]}  neg_natural={c[(0, 'natural')]}  neg_synthetic={c[(0, 'synthetic')]}")
    print("  by item kind:", dict(Counter(e["item_kind"] for e in examples)))
    print(f"wrote {args.out}/train.jsonl, test.jsonl")


if __name__ == "__main__":
    main()
