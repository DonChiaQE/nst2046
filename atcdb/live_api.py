"""The live demo app's routes, under /api/live/ (spec 2026-10-20-live-demo-app-design.md, Section 6).

Routing only: sessions live in atcdb/live.py, what they share in atcdb/live_hub.py. A clip is posted as the raw WAV
body with its fields in the query string, so no multipart parser is needed. Results come back on one server-sent
event stream per session; `after` (or the Last-Event-ID header) resumes it after a dropped connection.
"""
import json
from typing import Iterator

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel

from atcdb.live import LiveSession
from atcdb.live_hub import LiveHub

HEARTBEAT_S = 15.0   # a comment line this often keeps the connection from idling out


class TextLine(BaseModel):
    role: str
    t: float
    text: str
    source: str = "typed"


class RetryRequest(BaseModel):
    extractor: str
    seq: int


class LabelRequest(BaseModel):
    label: str


def sse(event: dict) -> str:
    return f"id: {event['id']}\nevent: {event['type']}\ndata: {json.dumps(event)}\n\n"


def make_router(hub: LiveHub) -> APIRouter:
    r = APIRouter(prefix="/api/live")

    def session(sid: str) -> LiveSession:
        s = hub.get(sid)
        if s is None:
            raise HTTPException(404, f"no live session {sid}")
        return s

    def unprocessable(call):
        try:
            return call()
        except ValueError as e:
            raise HTTPException(422, str(e)) from None

    @r.get("/health")
    def health():
        hub.whisper.start()   # the app polls this at launch, so Whisper starts loading then
        return hub.health()

    @r.post("/sessions")
    def new_session():
        hub.whisper.start()
        return {"session_id": hub.new_session().session_id}

    @r.post("/sessions/{sid}/text")
    def text(sid: str, line: TextLine):
        s = session(sid)
        return {"seq": unprocessable(lambda: s.submit_text(line.role, line.t, line.text, line.source))}

    @r.post("/sessions/{sid}/audio")
    async def audio(sid: str, request: Request, role: str, t: float, source: str = "speech",
                    transcriber: str = "whisper", preview_text: str = ""):
        s = session(sid)
        wav = await request.body()
        seq = unprocessable(lambda: s.submit_audio(role, t, wav, preview_text, transcriber, source))
        return {"seq": seq, "dropped": None if seq is not None else "Too short"}

    @r.post("/sessions/{sid}/undo")
    def undo(sid: str):
        return {"seq": session(sid).undo()}

    @r.post("/sessions/{sid}/retry")
    def retry(sid: str, req: RetryRequest):
        s = session(sid)
        unprocessable(lambda: s.retry(req.extractor, req.seq))
        return {"ok": True}

    @r.post("/sessions/{sid}/label")
    def label(sid: str, req: LabelRequest):
        try:
            hub.label(sid, req.label)
        except KeyError:
            raise HTTPException(404, f"no saved session {sid}") from None
        return {"ok": True}

    @r.get("/sessions/{sid}/stream")
    def stream(sid: str, request: Request, after: int = -1, max_events: int | None = None):
        s = session(sid)
        if request.headers.get("last-event-id", "").isdigit():
            after = int(request.headers["last-event-id"])

        def events() -> Iterator[str]:
            cursor, sent = after, 0
            while max_events is None or sent < max_events:
                batch = s.events_after(cursor, timeout=HEARTBEAT_S)
                if not batch:
                    yield ": keep-alive\n\n"
                    continue
                for event in batch[: None if max_events is None else max_events - sent]:
                    yield sse(event)
                    cursor, sent = event["id"], sent + 1

        return StreamingResponse(events(), media_type="text/event-stream", headers={"Cache-Control": "no-cache"})

    @r.get("/sessions/{sid}/clips/{seq}")
    def clip(sid: str, seq: int):
        path = hub.clip_path(sid, seq)
        if path is None:
            raise HTTPException(404, f"no clip {seq} in session {sid}")
        return FileResponse(path, media_type="audio/wav")

    @r.get("/scenarios")
    def scenarios():
        return hub.scenarios()

    @r.get("/scenarios/{sid}")
    def scenario(sid: str):
        try:
            return hub.scenario_lines(sid)
        except KeyError:
            raise HTTPException(404, f"no scenario {sid}") from None

    return r
