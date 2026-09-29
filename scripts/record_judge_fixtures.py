#!/usr/bin/env python3
"""Record real Claude replies for the judge's regression fixtures (tests/fixtures/judge_responses.json).

Usage:
    ANTHROPIC_API_KEY=... python scripts/record_judge_fixtures.py

Sends each case below to every model in judge.MODELS with exactly the request the judge makes, and stores each reply's
stop reason and content blocks. Re-run it whenever judge.VERSION is bumped, then update the expectations in
tests/test_judge.py. The sequences are invented: UWB-ATCC corpus text is CC BY-NC-ND and must never be written into a
fixture.
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import anthropic  # noqa: E402

from atcdb.judge import MODELS, VERSION, request  # noqa: E402
from atcdb.parsing import Transmission  # noqa: E402

OUT = ROOT / "tests" / "fixtures" / "judge_responses.json"

# name -> [(role, text), ...]
CASES: dict[str, list[tuple[str, str]]] = {
    "crossing_against_a_landing": [
        ("controller", "csa one two three runway three one cleared to land wind calm"),
        ("pilot", "cleared to land runway three one csa one two three"),
        ("controller", "lufthansa four five six cross runway three one"),
        ("pilot", "crossing runway three one lufthansa four five six"),
    ],
    "released_before_the_takeoff": [
        ("controller", "csa one two three runway three one cleared to land wind calm"),
        ("pilot", "cleared to land runway three one csa one two three"),
        ("pilot", "runway vacated csa one two three"),
        ("controller", "csa one two three contact ground one two one decimal nine"),
        ("controller", "lufthansa four five six runway three one cleared for takeoff"),
        ("pilot", "cleared for takeoff runway three one lufthansa four five six"),
    ],
}


def main() -> None:
    client = anthropic.Anthropic()
    records = []
    for name, turns in CASES.items():
        txs = [Transmission(id=i, transcript_id=i, text=text, role=role, start_s=10.0 * i) for i, (role, text) in enumerate(turns)]
        for model in MODELS:
            reply = client.messages.create(**request(model, txs))
            records.append({"case": name, "model": model, "version": VERSION, "turns": [list(t) for t in turns],
                            "stop_reason": reply.stop_reason, "content": [b.to_dict() for b in reply.content]})
            print(f"{name:32} {model:18} {reply.stop_reason}", flush=True)
    OUT.write_text(json.dumps(records, indent=1) + "\n")
    print(f"wrote {len(records)} replies to {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
