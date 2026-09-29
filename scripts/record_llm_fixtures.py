#!/usr/bin/env python3
"""Record real Claude replies for the parser's regression fixtures (tests/fixtures/llm_responses.json).

Usage:
    ANTHROPIC_API_KEY=... python scripts/record_llm_fixtures.py

Sends each case below to every model in parse_llm.MODELS with exactly the request the parser makes, and stores each
reply's stop reason and content blocks. Re-run it whenever parse_llm.VERSION is bumped, then update the expectations in
tests/test_parse_llm.py. The texts are NTSB public record (Austin, DCA23FA149) or invented: UWB-ATCC corpus text is
CC BY-NC-ND and must never be written into a fixture.
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import anthropic  # noqa: E402

from atcdb.parse_llm import MODELS, VERSION, request  # noqa: E402
from atcdb.parsing import Context, Transmission  # noqa: E402

OUT = ROOT / "tests" / "fixtures" / "llm_responses.json"
AUSTIN_LAND = ("fedex fourteen thirty-two heavy austin tower one eight left r-v-r touchdown one thousand four hundred "
               "midpoint six hundred rollout one thousand eight hundred one eight left cleared to land")
AUSTIN_TAKEOFF = ("southwest seven zero eight austin tower runway one eight left r-v-r one thousand two hundred midpoint six "
                  "hundred rollout one thousand six hundred fly heading one seven zero runway one eight left cleared for "
                  "takeoff traffic three mile final is a heavy seven sixty-seven")

# name -> (role, text, context). Contexts are built by hand so every case is self-contained.
CASES: dict[str, tuple[str, str, Context]] = {
    "austin_landing_clearance": ("controller", AUSTIN_LAND, Context(mode="role", role="controller")),
    "austin_takeoff_clearance": ("controller", AUSTIN_TAKEOFF, Context(mode="role", role="controller")),
    "austin_takeoff_readback": ("pilot", "okay that's one seven zero cleared for takeoff one eight left copy the traffic "
                                "southwest seven zero eight", Context(mode="role", role="pilot")),
    "austin_handoff": ("controller", "american nineteen thirteen contact departure", Context(mode="role", role="controller")),
    "cross_then_hold_short": ("controller", "lufthansa four five six cross runway two four hold short of runway three one",
                              Context(mode="role", role="controller")),
    "window_snaps_to_the_active_runway": ("controller", "csa one two three cleared to land wind calm", Context(
        mode="window", role="controller", history=(("pilot", "csa one two three established runway three one"),),
        active_callsigns=("csa one two three",), active_runways=("31",))),
}


def main() -> None:
    client = anthropic.Anthropic()
    records = []
    for name, (role, text, ctx) in CASES.items():
        tx = Transmission(id=0, transcript_id=0, text=text, role=role, start_s=0.0)
        for model in MODELS:
            reply = client.messages.create(**request(model, tx, ctx))
            records.append({"case": name, "model": model, "version": VERSION, "role": role, "text": text,
                            "context": {"mode": ctx.mode, "role": ctx.role, "history": [list(h) for h in ctx.history],
                                        "active_callsigns": list(ctx.active_callsigns),
                                        "active_runways": list(ctx.active_runways)},
                            "stop_reason": reply.stop_reason,
                            "content": [b.to_dict() for b in reply.content]})
            print(f"{name:36} {model:18} {reply.stop_reason}", flush=True)
    OUT.write_text(json.dumps(records, indent=1) + "\n")
    print(f"wrote {len(records)} replies to {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
