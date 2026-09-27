"""FastAPI app: the replay JSON API plus the static front-end (spec Section 3 and its addendum).

Routing only: response shapes live in atcdb/serialize.py, replay logic in atcdb/replay.py. Each handler opens and
closes its own SQLite connection, because FastAPI may run a sync dependency and a sync handler on different pool
threads and a connection must not cross threads. `uvicorn atcdb.api:app` serves the corpus DB; tests build their own
app with `create_app(db_path, project_root)`.
"""
import os
from contextlib import closing
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from atcdb.parsing import CONTEXT_MODES
from atcdb.replay import (PARSER_AVAILABILITY, PARSER_MODELS, PARSER_VERSIONS, build_timeline, default_transcript_model,
                          get_recording, list_recordings, transcript_models)
from atcdb.schema import init_db
from atcdb.serialize import timeline_dict

ROOT = Path(__file__).resolve().parents[1]
STATIC_DIR = Path(__file__).resolve().parent / "static"
TRANSCRIPT_KINDS = ("gold", "asr")   # the kinds a replay can use


def _require(name: str, value: str, allowed) -> None:
    if value not in allowed:
        raise HTTPException(422, f"unknown {name} {value!r}; expected one of {sorted(allowed)}")


def create_app(db_path: Path | str = ROOT / "data/atc.sqlite", project_root: Path | str = ROOT) -> FastAPI:
    root = Path(project_root).absolute()
    app = FastAPI(title="ATC conflict engine", docs_url="/api/docs", redoc_url=None, openapi_url="/api/openapi.json")

    def db():
        if not Path(db_path).is_file():   # never let a request silently create an empty corpus database
            raise HTTPException(503, f"corpus database not found at {db_path}; build it first (see README)")
        return closing(init_db(db_path))

    @app.get("/api/capabilities")
    def capabilities():
        with db() as conn:
            models = transcript_models(conn)
        parsers = []
        for name in sorted(PARSER_MODELS):
            available, reason = PARSER_AVAILABILITY[name]()   # whether a cold parse can run; cached replays always can
            parsers += [{"name": name, "model": m, "model_version": PARSER_VERSIONS[name], "available": available,
                         "reason": reason} for m in PARSER_MODELS[name]]
        return {"parsers": parsers,
                "contexts": list(CONTEXT_MODES),
                "transcripts": {k: models[k] for k in TRANSCRIPT_KINDS if k in models},
                "live": False}

    @app.get("/api/recordings")
    def recordings(facility: str = "Tower", min_transmissions: int = Query(4, ge=1), transcript: str = "gold"):
        _require("transcript kind", transcript, TRANSCRIPT_KINDS)
        with db() as conn:
            return list_recordings(conn, facility=facility, min_transmissions=min_transmissions, transcript_kind=transcript)

    @app.get("/api/recordings/{recording_id}/replay")
    def replay(recording_id: int, parser: str = "rule", model: str | None = None, context: str = "window",
               transcript: str = "gold", transcript_model: str | None = None):
        _require("parser", parser, PARSER_MODELS)
        model = model or PARSER_MODELS[parser][0]
        _require("model", model, PARSER_MODELS[parser])
        _require("context mode", context, CONTEXT_MODES)
        _require("transcript kind", transcript, TRANSCRIPT_KINDS)
        with db() as conn:
            recording = get_recording(conn, recording_id)
            if recording is None:
                raise HTTPException(404, f"no recording {recording_id}")
            pinned = transcript_model or default_transcript_model(conn, transcript, recording_id)
            tl = build_timeline(conn, recording_id, parser=parser, model=model, transcript_kind=transcript, context=context,
                                transcript_model=pinned)
        return timeline_dict(tl, recording, pinned)

    @app.get("/api/clips/{transmission_id}")
    def clip(transmission_id: int):
        with db() as conn:
            row = conn.execute("SELECT clip_path FROM transmissions WHERE id = ?", (transmission_id,)).fetchone()
        # lexical containment check: refuses "../" and absolute clip paths but, unlike resolve(), allows a symlinked data/
        path = Path(os.path.normpath(root / row["clip_path"])) if row and row["clip_path"] else None
        if path is None or not path.is_relative_to(root) or not path.is_file():
            raise HTTPException(404, f"no clip for transmission {transmission_id}")
        return FileResponse(path, media_type="audio/wav")

    # Mounted last: a mount at "/" swallows every route registered after it, so add new routes (such as the phase-4
    # live endpoint) above this line.
    app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")
    return app


app = create_app()
