"""Claude parser (spec Section 2, amended by addendum A.4): one forced `report_events` tool call per transmission.

The tool mirrors the engine's events one to one. `make_parser(model)` returns a `Parser` for the registry in
`atcdb/replay.py`. The Anthropic client is created on the first call that needs one, so importing this module never
imports `anthropic` and a replay served from the events cache never touches the API. API errors propagate as the SDK
raised them, and a refusal, a truncated reply or a reply without the tool call raises `ParseError`; `get_events` caches
nothing for either, so the next replay retries. A reported event that cannot become an engine event (a runway that does
not normalise, a runway instruction without a runway, a handoff without a target) becomes `Unresolved`, which the engine
counts as dropped.

Bump VERSION by hand whenever SYSTEM, TOOL, `render_prompt`, `to_events` (it shapes the cached rows) or the request
settings change: it is part of the cache key.
"""
import functools
import json
import os
from typing import Any

from atcdb.engine import (HANDOFF_TARGETS, ClearTakeoff, ClearToCross, ClearToLand, Event, GoAround, Handoff, HoldShort,
                          LineUpAndWait, ReadbackObserved, RunwayVacated, Unresolved, normalize_runway)
from atcdb.parsing import Context, Parser, Transmission

VERSION = "p1"
# The cheap and the strong evaluation arm (spec addendum A.4), then the live demo app's model (live demo spec, Section 8).
MODELS = ("claude-haiku-4-5", "claude-sonnet-5", "claude-haiku-5-5")

# Every model does one-shot extraction with thinking off. anthropic 1.x has no `temperature` parameter, so Haiku 4.5's
# goes in extra_body; Sonnet 5 and Haiku 5.5 reject a non-default temperature and run with thinking disabled at low
# effort instead.
MODEL_SETTINGS: dict[str, dict[str, Any]] = {
    "claude-haiku-4-5": {"extra_body": {"temperature": 0}},
    "claude-sonnet-5": {"thinking": {"type": "disabled"}, "output_config": {"effort": "low"}},
    "claude-haiku-5-5": {"thinking": {"type": "disabled"}, "output_config": {"effort": "low"}},
}
MAX_TOKENS = 1024   # a transmission yields a handful of events; a truncated reply raises ParseError

# For `parse_events.py --dry-run` only. USD per million tokens, (input, output), as listed 2026-06 (Haiku 5.5: 2026-10,
# prompts up to 100K tokens).
PRICES_PER_MTOK: dict[str, tuple[float, float]] = {"claude-haiku-4-5": (1.00, 5.00), "claude-sonnet-5": (2.00, 10.00),
                                                   "claude-haiku-5-5": (0.10, 0.50)}
# Tokens per token of the older tokenizers for the same text: Haiku 5.5's newer tokenizer counts about 30% more.
_TOKENIZER_FACTOR: dict[str, float] = {"claude-haiku-5-5": 1.3}
_TOOL_USE_OVERHEAD_TOKENS = 350   # the system prompt the API adds when tools are present (rough)
_OUTPUT_TOKENS = 150              # a tool call with a handful of events (rough)

_RUNWAY_EVENTS = {"LAND": ClearToLand, "TAKEOFF": ClearTakeoff, "LUAW": LineUpAndWait, "CROSS": ClearToCross,
                  "HOLD_SHORT": HoldShort}
EVENT_KINDS = (*_RUNWAY_EVENTS, "VACATED", "GO_AROUND", "HANDOFF", "READBACK", "NOOP")

SYSTEM = """You read one radio transmission from an airport tower frequency and report its runway events with the \
report_events tool, in the order they are spoken. Report an empty list when there are none.

Event kinds:
- LAND, TAKEOFF, LUAW (line up and wait), CROSS (cross a runway), HOLD_SHORT: a controller's instruction to an \
aircraft about a runway. Give the runway.
- HANDOFF: the controller tells an aircraft to contact another frequency. Give `to`: ground, departure, tower or \
approach.
- READBACK: a pilot repeating an instruction back to the controller. Report one READBACK for the pilot's transmission, \
never the instructions it repeats: pilots do not issue instructions.
- VACATED: a pilot reporting that it has left the runway.
- GO_AROUND: an instruction to go around, or a pilot reporting one.
- NOOP: nothing relevant. You may leave it out.

Fields:
- callsign: the aircraft's callsign in the transcript's own words, lower case, for example "csa one two three". Use \
the same words for the same aircraft every time; the tracked aircraft, when shown, are the forms already in use. Use \
an empty string when no callsign is said.
- runway: the designator in digits with an optional L, R or C, for example "31" or "04L", or null. When an \
instruction names no runway and exactly one runway has an active clearance, use that runway.
- to: only for HANDOFF; otherwise null.

Report only what the transmission says."""

TOOL: dict[str, Any] = {
    "name": "report_events",
    "description": "Report every runway event in the transmission, in spoken order. An empty list means none.",
    "strict": True,
    "input_schema": {
        "type": "object",
        "properties": {"events": {"type": "array", "items": {
            "type": "object",
            "properties": {
                "kind": {"type": "string", "enum": list(EVENT_KINDS)},
                "callsign": {"type": "string", "description": "lower-case words as spoken; empty if none"},
                "runway": {"anyOf": [{"type": "string"}, {"type": "null"}],
                           "description": "digits plus optional L/R/C, e.g. 31 or 04L; null if none"},
                "to": {"anyOf": [{"type": "string", "enum": list(HANDOFF_TARGETS)}, {"type": "null"}],
                       "description": "the frequency handed to; HANDOFF only"},
            },
            "required": ["kind", "callsign", "runway", "to"],
            "additionalProperties": False,
        }}},
        "required": ["events"],
        "additionalProperties": False,
    },
}


class ParseError(RuntimeError):
    """The model answered, but not with a usable report_events call: a refusal, a truncated reply, or no call at all."""


def render_prompt(tx: Transmission, ctx: Context) -> str:
    """The user message: the transmission, plus what the context mode allows (spec Section 2)."""
    lines = []
    if ctx.mode == "window":
        if ctx.history:
            lines.append("Previous transmissions, oldest first:")
            lines += [f"  [{role}] {text}" for role, text in ctx.history]
        lines.append("Aircraft being tracked: " + (", ".join(ctx.active_callsigns) or "none"))
        lines.append("Runways with active clearances: " + (", ".join(ctx.active_runways) or "none"))
    if ctx.mode != "none":
        lines.append(f"Speaker: {ctx.role}")
    lines.append(f"Transmission: {tx.text}")
    return "\n".join(lines)


def request(model: str, tx: Transmission, ctx: Context) -> dict[str, Any]:
    """Keyword arguments for `client.messages.create` for one transmission."""
    return {"model": model, "max_tokens": MAX_TOKENS, "system": SYSTEM, "tools": [TOOL],
            "tool_choice": {"type": "tool", "name": TOOL["name"]},
            "messages": [{"role": "user", "content": render_prompt(tx, ctx)}], **MODEL_SETTINGS[model]}


def to_events(items: list[dict], tx: Transmission) -> list[Event]:
    """The tool's event list as engine events. NOOP adds nothing; an item that cannot be placed becomes Unresolved."""
    events: list[Event] = []
    for it in items:
        kind = it.get("kind")
        common = {"callsign": " ".join((it.get("callsign") or "").lower().split()), "t": tx.start_s, "text": tx.text}
        event: Event | None = None
        if kind in _RUNWAY_EVENTS:
            runway = normalize_runway(it.get("runway") or "")
            event = _RUNWAY_EVENTS[kind](runway=runway, **common) if runway else None
        elif kind == "HANDOFF":
            event = Handoff(to=it["to"], **common) if it.get("to") in HANDOFF_TARGETS else None
        elif kind == "READBACK":
            event = ReadbackObserved(callsign=common["callsign"], text=tx.text, t=tx.start_s)
        elif kind == "VACATED":
            event = RunwayVacated(**common)
        elif kind == "GO_AROUND":
            event = GoAround(**common)
        elif kind == "NOOP":
            continue
        events.append(event or Unresolved(raw=json.dumps(it, sort_keys=True), **common))
    return events


def events_from_response(response: Any, tx: Transmission) -> list[Event]:
    """Map a Messages API response to events, or raise ParseError when it holds no usable report_events call."""
    if response.stop_reason == "refusal":
        raise ParseError("the model refused this transmission")
    if response.stop_reason == "max_tokens":
        raise ParseError(f"reply truncated at max_tokens={MAX_TOKENS}")
    call = next((b for b in response.content if b.type == "tool_use" and b.name == TOOL["name"]), None)
    if call is None:
        raise ParseError("no report_events call in the reply")
    return to_events(call.input["events"], tx)


@functools.cache
def _default_client() -> Any:
    import anthropic   # deferred: importing this module, or replaying from the cache, never needs the SDK
    # A bounded timeout so one hung call cannot stall a replay for the SDK's default 10-minute timeout;
    # max_retries stays at the SDK default.
    return anthropic.Anthropic(timeout=60.0)


def make_parser(model: str, client: Any = None) -> Parser:
    """A Parser that asks `model` for one transmission's events. Tests inject `client`; otherwise the default Anthropic
    client is created on the first call."""
    if model not in MODELS:
        raise ValueError(f"unknown Claude model {model!r}; expected one of {MODELS}")

    def parse(tx: Transmission, ctx: Context) -> list[Event]:
        response = (client or _default_client()).messages.create(**request(model, tx, ctx))
        return events_from_response(response, tx)

    return parse


def estimate_cost(model: str, prompts: list[str]) -> float:
    """Rough USD for one call per user prompt: about four characters a token for the prompt, the system prompt and the
    tool, plus the API's tool-use overhead in, and a short tool call out. Good to a factor of two; for dry runs only."""
    fixed = (len(SYSTEM) + len(json.dumps(TOOL))) / 4 + _TOOL_USE_OVERHEAD_TOKENS
    tokens_in = sum(fixed + len(p) / 4 for p in prompts)
    price_in, price_out = PRICES_PER_MTOK[model]
    return _TOKENIZER_FACTOR.get(model, 1.0) * (tokens_in * price_in + len(prompts) * _OUTPUT_TOKENS * price_out) / 1e6


def availability() -> tuple[bool, str | None]:
    """Whether a cold Claude parse can run here, and if not, why (spec addendum A.4, capabilities)."""
    try:
        import anthropic  # noqa: F401
    except ImportError:
        return False, "anthropic not installed"
    # The SDK can also authenticate via ANTHROPIC_AUTH_TOKEN or an `ant auth login` profile; this check only ever
    # looks for the API key, so it can report unavailable when a call would in fact succeed.
    if not os.environ.get("ANTHROPIC_API_KEY"):
        return False, "ANTHROPIC_API_KEY not set"
    return True, None
