"""Phone call agent API (docs/integrations/calls.md).

Local API only (admin-guarded, main backend). The public telephony gateway
serves only Twilio's webhooks and media streams; nothing here is reachable
through the tunnel. Every outbound call starts from an explicit ``POST /calls``
— there is no queue and no bulk dialing.
"""
from __future__ import annotations

import asyncio
import json
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel, Field, field_validator

from api.dependencies import check_admin, require_admin, _request_presents_admin_credential
from services.telephony import calls, config

async def require_call_control(request: Request) -> None:
    """Only the operator can opt authenticated paired sessions into call control.

    This exception is scoped to calls; settings retain the strict admin gate.
    Share PINs and trusted-network access never authorize billable calls.
    """
    try:
        check_admin(request)
        return
    except HTTPException as exc:
        if exc.status_code != 403:
            raise
        if not _request_presents_admin_credential(request):
            raise
        settings = await asyncio.to_thread(config.load_call_settings)
        if not settings.allow_remote_control:
            raise


router = APIRouter(prefix="/calls", tags=["calls"], dependencies=[Depends(require_call_control)])

_HEARTBEAT_S = 15.0


def _http(exc: calls.CallError) -> HTTPException:
    return HTTPException(status_code=exc.status, detail=exc.detail())


def _live_or_404(call_id: str) -> calls.CallSession:
    session = calls.get_live(call_id)
    if session is None:
        if calls.get_record(call_id) is None:
            raise HTTPException(404, detail={"code": "not_found", "message": "No such call"})
        raise HTTPException(409, detail={"code": "call_ended", "message": "This call has ended"})
    return session


# ── Settings + readiness ────────────────────────────────────────────────────


class _SettingsBody(BaseModel):
    from_number: Optional[str] = Field(None, max_length=32)
    disclosure_template: Optional[str] = Field(None, max_length=config.MAX_DISCLOSURE_CHARS + 100)
    user_name: Optional[str] = Field(None, max_length=config.MAX_NAME_CHARS)
    inbound_mode: Optional[str] = Field(None, max_length=16)
    inbound_brief: Optional[str] = Field(None, max_length=config.MAX_BRIEF_CHARS + 100)
    max_concurrent: Optional[int] = Field(None, ge=1, le=2)
    record_calls: Optional[bool] = None
    allow_remote_control: Optional[bool] = None


@router.get("/settings", dependencies=[Depends(require_admin)])
def get_settings():
    return config.load_call_settings().as_dict()


@router.put("/settings", dependencies=[Depends(require_admin)])
def put_settings(body: _SettingsBody):
    current = config.load_call_settings()
    try:
        mode = current.inbound_mode if body.inbound_mode is None else body.inbound_mode.strip()
        if mode not in config.INBOUND_MODES:
            raise config.ConfigError("invalid_inbound_mode", "Incoming calls are answered with the greeting or the agent")
        updated = config.CallSettings(
            from_number=current.from_number if body.from_number is None
            else (config.normalize_phone_number(body.from_number, code="invalid_from_number")
                  if body.from_number.strip() else ""),
            disclosure_template=current.disclosure_template if body.disclosure_template is None
            else config.normalize_disclosure(body.disclosure_template),
            user_name=current.user_name if body.user_name is None else body.user_name.strip(),
            inbound_mode=mode,
            inbound_brief=current.inbound_brief if body.inbound_brief is None
            else config.normalize_brief(body.inbound_brief, required=False),
            max_concurrent=current.max_concurrent if body.max_concurrent is None else body.max_concurrent,
            record_calls=current.record_calls if body.record_calls is None else body.record_calls,
            allow_remote_control=current.allow_remote_control if body.allow_remote_control is None else body.allow_remote_control,
        )
    except config.ConfigError as exc:
        raise HTTPException(400, detail={"code": exc.code, "message": str(exc)}) from exc
    config.save_call_settings(updated)
    return updated.as_dict()


@router.get("/options")
def get_options():
    settings = config.load_call_settings()
    return {"disclosure": config.render_disclosure(settings.disclosure_template, settings.user_name)}


@router.get("/readiness")
def get_readiness():
    """The guided-setup checklist: ``[{id, ok, detail}]`` for credentials,
    tunnel, number, llm, asr and voice, in that order."""
    return calls.readiness()


# ── Calls ──────────────────────────────────────────────────────────────────


class _CallBody(BaseModel):
    to: str = Field(..., max_length=32)
    brief: str = Field(..., max_length=config.MAX_BRIEF_CHARS + 100)
    profile_id: str = Field(..., max_length=128)
    engine: Optional[str] = Field(None, max_length=128)
    language: Optional[str] = Field(None, max_length=64)
    disclosure: Optional[str] = Field(None, max_length=config.MAX_DISCLOSURE_CHARS + 100)
    max_minutes: int = Field(10, ge=1)

    @field_validator("max_minutes")
    @classmethod
    def _cap(cls, value: int) -> int:
        return min(value, 30)


@router.post("", status_code=201)
async def place_call(body: _CallBody):
    from core.config import VOICES_DIR
    from core.db import db_conn
    from core.path_security import contained_join
    from services.consent_ledger import enforce_checkpoint_consent

    pid = body.profile_id.strip()
    ref_path = None
    p_kind = None
    if pid:
        with db_conn() as conn:
            row = conn.execute("SELECT * FROM voice_profiles WHERE id=?", (pid,)).fetchone()
        if row:
            try:
                p_kind = row["kind"] or "clone"
            except (KeyError, IndexError):
                p_kind = "clone"
            rel = row["locked_audio_path"] if row["is_locked"] and row["locked_audio_path"] else row["ref_audio_path"]
            if rel:
                ref_path = contained_join(VOICES_DIR, rel)
    if p_kind == "clone" or ref_path or (pid and row is None):
        enforce_checkpoint_consent(
            pid,
            checkpoint="call_enqueue",
            reference_path=ref_path,
            has_ref_audio=bool(ref_path),
            profile_kind=p_kind,
            engine_id=(body.engine or "").strip() or None,
        )
    try:
        session = calls.create_outbound(
            to=body.to,
            brief=body.brief,
            profile_id=pid,
            engine=(body.engine or "").strip(),
            language=(body.language or "").strip(),
            disclosure=body.disclosure,
            max_minutes=body.max_minutes,
        )
        await asyncio.to_thread(calls.dial, session)
    except calls.CallError as exc:
        raise _http(exc) from exc
    return {"call": session.as_record(transcript=True)}


@router.get("")
def list_calls(limit: int = Query(50, ge=1, le=200)):
    return {"calls": calls.list_records(limit)}


@router.get("/{call_id}")
def get_call(call_id: str):
    record = calls.get_record(call_id)
    if record is None:
        raise HTTPException(404, detail={"code": "not_found", "message": "No such call"})
    return record


@router.delete("/{call_id}")
def delete_call(call_id: str):
    try:
        deleted = calls.delete_record(call_id)
    except calls.CallError as exc:
        raise _http(exc) from exc
    if not deleted:
        raise HTTPException(404, detail={"code": "not_found", "message": "No such call"})
    return {"deleted": call_id}


@router.get("/{call_id}/recording")
def get_recording(call_id: str):
    path = calls.recording_path(call_id)
    if path is None:
        raise HTTPException(404, detail={"code": "no_recording", "message": "This call was not recorded"})
    return FileResponse(path, media_type="audio/wav", headers={"Cache-Control": "no-store"})


def _sse(event: dict) -> str:
    return f"data: {json.dumps(event)}\n\n"


@router.get("/{call_id}/events")
async def call_events(call_id: str, request: Request):
    """Server-sent events until the call ends: status, transcript,
    agent_state, outcome, then ended (after which the stream closes)."""
    session = calls.get_live(call_id)
    if session is None:
        record = calls.get_record(call_id)
        if record is None:
            raise HTTPException(404, detail={"code": "not_found", "message": "No such call"})

        async def _replay():
            yield _sse({"type": "status", "status": record["status"], "t": record.get("duration_s") or 0})
            yield _sse({"type": "outcome", "outcome": record["outcome"], "summary": record["summary"]})
            yield _sse({"type": "ended", "call": {k: v for k, v in record.items() if k not in ("transcript", "timeline")}})

        return StreamingResponse(_replay(), media_type="text/event-stream", headers={"Cache-Control": "no-store"})

    queue = session.subscribe()

    async def _stream():
        try:
            yield _sse({"type": "status", "status": session.status, "t": session._elapsed()})
            if session.agent_state:
                yield _sse({"type": "agent_state", "state": session.agent_state})
            while True:
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=_HEARTBEAT_S)
                except asyncio.TimeoutError:
                    if await request.is_disconnected():
                        return
                    yield ": ping\n\n"
                    continue
                yield _sse(event)
                if event.get("type") == "ended":
                    return
        finally:
            session.unsubscribe(queue)

    return StreamingResponse(
        _stream(), media_type="text/event-stream", headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"}
    )


class _SayBody(BaseModel):
    text: str = Field(..., max_length=config.MAX_DISCLOSURE_CHARS + 100)


@router.post("/{call_id}/say")
def say(call_id: str, body: _SayBody):
    session = _live_or_404(call_id)
    try:
        calls.say(session, body.text)
    except calls.CallError as exc:
        raise _http(exc) from exc
    return {"ok": True}


class _TakeoverBody(BaseModel):
    enabled: bool


@router.post("/{call_id}/takeover")
def takeover(call_id: str, body: _TakeoverBody):
    session = _live_or_404(call_id)
    calls.set_takeover(session, body.enabled)
    return {"ok": True, "takeover": body.enabled}


@router.post("/{call_id}/hangup")
async def hangup(call_id: str):
    session = _live_or_404(call_id)
    try:
        await asyncio.to_thread(calls.hangup, session)
    except calls.CallError as exc:
        raise _http(exc) from exc
    return {"ok": True}
