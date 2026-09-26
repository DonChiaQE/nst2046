"""Plain-dict views of replay objects, shaped for the JSON API (spec Section 3 addendum).

Pure: no web framework, no DB. `atcdb/api.py` only routes; every response shape is defined and tested here.
"""
from atcdb.engine import Conflict, Event, State
from atcdb.parsing import KINDS, Transmission
from atcdb.replay import Step, Timeline


def event_dict(e: Event) -> dict:
    """Every event has the same four keys; `runway` is set on runway instructions, `to` on handoffs."""
    return {"kind": KINDS[type(e)], "callsign": e.callsign, "runway": getattr(e, "runway", None), "to": getattr(e, "to", None)}


def conflict_dict(c: Conflict) -> dict:
    return {"type": c.type, "severity": c.severity, "runway": c.runway, "callsigns": list(c.callsigns), "seq": c.seq,
            "explanation": c.explanation, "basis": c.basis}


def transmission_dict(tx: Transmission) -> dict:
    return {"id": tx.id, "transcript_id": tx.transcript_id, "start_s": tx.start_s, "role": tx.role, "text": tx.text}


def board_dict(state: State) -> dict[str, list[dict]]:
    """Active reservations per runway, in the order they were made."""
    return {rwy: [{"callsign": r.callsign, "kind": r.kind} for r in res] for rwy, res in sorted(state.runways.items())}


def aircraft_list(state: State) -> list[dict]:
    """Every aircraft the engine has seen, by callsign."""
    return [{"callsign": a.callsign, "runway": a.runway, "kind": a.kind, "holding_short": a.holding_short, "pending": a.pending}
            for _, a in sorted(state.aircraft.items())]


def step_dict(index: int, step: Step) -> dict:
    return {"index": index, "transmission": transmission_dict(step.tx), "events": [event_dict(e) for e in step.events],
            "conflicts": [conflict_dict(c) for c in step.conflicts], "error": step.error, "dropped": step.dropped,
            "board": board_dict(step.state), "aircraft": aircraft_list(step.state)}


def runways_named(tl: Timeline) -> list[str]:
    """Every runway any event in the recording names, so the UI can lay out the board once and never reflow."""
    return sorted({e.runway for s in tl.steps for e in s.events if getattr(e, "runway", None)})


def timeline_dict(tl: Timeline, recording: dict, transcript_model: str | None) -> dict:
    return {"recording": recording, "parser": tl.parser, "model": tl.model, "model_version": tl.model_version,
            "context": tl.context, "transcript_kind": tl.transcript_kind, "transcript_model": transcript_model,
            "runways": runways_named(tl), "dropped": tl.dropped, "steps": [step_dict(i, s) for i, s in enumerate(tl.steps)]}
