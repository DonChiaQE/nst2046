"""LLM judge, the evaluation's ablation arm (spec 2026-09-29-evaluation-3b1-design.md, section 7).

The whole transcript of one recording goes to Claude in one call, and a forced, strict `report_conflicts` tool lists the
incompatible clearances it sees. No parser, no engine: this is the "raw LLM over the transcript" baseline that the
structured system is compared with. The model and request settings match the parser's Sonnet arm (`parse_llm`), so the
comparison is about structure, not reasoning budget. Judgments are cached in the `judgments` table, one per (recording,
transcript kind and model, judge model, VERSION), stored with the sha1 of the sequence judged: a judgment of another
sequence (say, a partial ASR run since completed) is a miss, deleted and judged again. API errors and unusable replies
raise and cache nothing.

Bump VERSION by hand whenever SYSTEM, TOOL, `render_sequence`, `conflicts_from_response` or the request settings change.
"""
import hashlib
import json
import sqlite3
from typing import Any

from atcdb.engine import normalize_runway
from atcdb.parse_llm import MODEL_SETTINGS, PRICES_PER_MTOK, _default_client
from atcdb.parsing import Transmission

VERSION = "j1"
MODELS = ("claude-sonnet-5",)
MAX_TOKENS = 2048   # a recording holds at most a few conflicts; a truncated reply raises JudgeError
_TOOL_USE_OVERHEAD_TOKENS = 350
_OUTPUT_TOKENS = 120

SYSTEM = """You monitor an airport tower frequency. You are given one recorded sequence of radio transmissions, \
numbered in order, each with the speaker's role. Report every conflicting clearance with the report_conflicts tool, \
or an empty list when there is none.

RUNWAY conflict: an aircraft is cleared onto a runway that another aircraft is still cleared to use. For example a \
takeoff, line-up or crossing clearance while an earlier landing clearance on the same runway is still in force, or a \
landing clearance while another aircraft is cleared to take off, line up or cross there. An aircraft stops using a \
runway when it reports vacating it, is handed to ground (after landing or crossing) or to departure or radar (after \
takeoff), is told to go around, or is told to hold short of it. Two successive landing clearances on one runway are \
normal and are not a conflict.

READBACK conflict: a pilot reads back a runway instruction without the runway, or with a different runway.

For each conflict give the runway in digits with an optional L, R or C (for example 31 or 04L), the callsigns involved \
as spoken (the aircraft whose clearance creates the conflict first), and trigger_index, the number of the transmission \
at which the conflict arises. Report only what the transcript shows."""

TOOL: dict[str, Any] = {
    "name": "report_conflicts",
    "description": "Report every conflicting clearance in the sequence. An empty list means none.",
    "strict": True,
    "input_schema": {
        "type": "object",
        "properties": {"conflicts": {"type": "array", "items": {
            "type": "object",
            "properties": {
                "type": {"type": "string", "enum": ["RUNWAY", "READBACK"]},
                "runway": {"type": "string", "description": "digits plus optional L/R/C, e.g. 31 or 04L"},
                "callsigns": {"type": "array", "items": {"type": "string"},
                              "description": "lower-case words as spoken; the aircraft creating the conflict first"},
                "trigger_index": {"type": "integer", "description": "number of the transmission where it arises"},
            },
            "required": ["type", "runway", "callsigns", "trigger_index"],
            "additionalProperties": False,
        }}},
        "required": ["conflicts"],
        "additionalProperties": False,
    },
}


class JudgeError(RuntimeError):
    """The model answered, but not with a usable report_conflicts call: a refusal, a truncated reply, or no call."""


def render_sequence(txs: list[Transmission]) -> str:
    """The user message: every transmission, numbered from 1, with its speaker role."""
    return "\n".join(["Transmissions, in order:"] + [f"[{i}] ({tx.role}) {tx.text}" for i, tx in enumerate(txs, 1)])


def request(model: str, txs: list[Transmission]) -> dict[str, Any]:
    """Keyword arguments for `client.messages.create` for one recording."""
    return {"model": model, "max_tokens": MAX_TOKENS, "system": SYSTEM, "tools": [TOOL],
            "tool_choice": {"type": "tool", "name": TOOL["name"]},
            "messages": [{"role": "user", "content": render_sequence(txs)}], **MODEL_SETTINGS[model]}


def conflicts_from_response(response: Any, n: int) -> tuple[list[dict], int]:
    """(conflicts, dropped) from a reply about a sequence of `n` transmissions. Each conflict is {type, runway,
    callsigns, step}, `step` being the 0-based transmission index. A reported conflict whose trigger_index is outside
    1..n or whose runway does not normalise is dropped and counted. Raises JudgeError on an unusable reply."""
    if response.stop_reason == "refusal":
        raise JudgeError("the model refused this sequence")
    if response.stop_reason == "max_tokens":
        raise JudgeError(f"reply truncated at max_tokens={MAX_TOKENS}")
    call = next((b for b in response.content if b.type == "tool_use" and b.name == TOOL["name"]), None)
    if call is None:
        raise JudgeError("no report_conflicts call in the reply")
    out, dropped = [], 0
    for it in call.input["conflicts"]:
        runway = normalize_runway(it.get("runway") or "")
        index = it.get("trigger_index")
        if runway is None or not isinstance(index, int) or not 1 <= index <= n:
            dropped += 1
            continue
        out.append({"type": it["type"], "runway": runway, "step": index - 1,
                    "callsigns": [" ".join(c.lower().split()) for c in it.get("callsigns") or []]})
    return out, dropped


_KEY_SQL = "recording_id = ? AND transcript_kind = ? AND transcript_model = ? AND judge_model = ? AND judge_version = ?"


def sequence_sha1(txs: list[Transmission]) -> str:
    """The fingerprint of the sequence a judgment was made from."""
    return hashlib.sha1(render_sequence(txs).encode()).hexdigest()


def _cached(conn: sqlite3.Connection, key: tuple, sha: str) -> tuple[list[dict], int] | None:
    """The stored judgment for `key`, if it was made from the sequence with fingerprint `sha`."""
    row = conn.execute(f"SELECT conflicts_json, dropped, sequence_sha1 FROM judgments WHERE {_KEY_SQL}", key).fetchone()
    return (json.loads(row["conflicts_json"]), row["dropped"]) if row and row["sequence_sha1"] == sha else None


def judge(conn: sqlite3.Connection, recording_id: int, txs: list[Transmission], transcript_kind: str,
          transcript_model: str, model: str = MODELS[0], client: Any = None) -> tuple[list[dict], int]:
    """(conflicts, dropped) for one recording's transmissions `txs`: from the `judgments` cache, or asked and stored.
    An empty sequence is judged empty without a call. Errors propagate and nothing is stored; if another request stored
    the same judgment first, that one is returned."""
    if model not in MODELS:
        raise ValueError(f"unknown judge model {model!r}; expected one of {MODELS}")
    if not txs:
        return [], 0
    key, sha = (recording_id, transcript_kind, transcript_model, model, VERSION), sequence_sha1(txs)
    cached = _cached(conn, key, sha)
    if cached is not None:
        return cached
    response = (client or _default_client()).messages.create(**request(model, txs))
    conflicts, dropped = conflicts_from_response(response, len(txs))
    # a judgment of another sequence under the same key is stale: replace it
    conn.execute(f"DELETE FROM judgments WHERE {_KEY_SQL} AND sequence_sha1 != ?", (*key, sha))
    conn.execute("""INSERT OR IGNORE INTO judgments (recording_id, transcript_kind, transcript_model, judge_model,
                    judge_version, conflicts_json, dropped, sequence_sha1) VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                 (*key, json.dumps(conflicts), dropped, sha))
    conn.commit()
    return _cached(conn, key, sha)


def estimate_cost(model: str, prompts: list[str]) -> float:
    """Rough USD for one call per sequence prompt (four characters a token); for dry runs only."""
    fixed = (len(SYSTEM) + len(json.dumps(TOOL))) / 4 + _TOOL_USE_OVERHEAD_TOKENS
    tokens_in = sum(fixed + len(p) / 4 for p in prompts)
    price_in, price_out = PRICES_PER_MTOK[model]
    return (tokens_in * price_in + len(prompts) * _OUTPUT_TOKENS * price_out) / 1e6


def is_cached(conn: sqlite3.Connection, recording_id: int, transcript_kind: str, transcript_model: str,
              model: str = MODELS[0], txs: list[Transmission] | None = None) -> bool:
    """Whether a judgment is stored for the key; with `txs`, only one made from that very sequence counts."""
    key = (recording_id, transcript_kind, transcript_model, model, VERSION)
    if txs is not None:
        return _cached(conn, key, sequence_sha1(txs)) is not None
    return conn.execute(f"SELECT 1 FROM judgments WHERE {_KEY_SQL}", key).fetchone() is not None
