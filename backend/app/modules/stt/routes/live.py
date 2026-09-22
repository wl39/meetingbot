"""Authenticated microphone WebSocket protocol and streaming lifetime."""

import asyncio

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect
from meetingbot_access import COOKIE

from app.access import require_owner

from ..live_service import LiveSession
from ..schemas import Options, StartFrame, StopFrame
from .dependencies import check_ready, get_session

router = APIRouter()


@router.websocket("/sessions/{sid}/stream")
async def stream(websocket: WebSocket, sid: str):
    app = websocket.app
    s = app.state.service
    if websocket.headers.get("origin") not in s.settings.origins:
        await websocket.close(code=1008)
        return
    protocols = websocket.headers.get("sec-websocket-protocol", "").split(",")
    credential = next((p.strip()[4:] for p in protocols if p.strip().startswith("stt.")), "")
    principal = app.state.access.key(credential) if credential else app.state.access.session(
        websocket.cookies.get(COOKIE, ""), allow_guest=s.settings.demo_mode or s.settings.keyless_login)
    websocket.state.principal = principal
    if not principal:
        await websocket.close(code=1008)
        return
    try:
        require_owner(app, principal, sid)
    except HTTPException:
        await websocket.close(code=1008)
        return
    await websocket.accept(subprotocol="stt")
    live = None
    sender = None
    closing = False
    send_lock = asyncio.Lock()

    async def send(data):
        async with send_lock:
            await websocket.send_json(data)

    async def updates():
        while True:
            session = s.repo.get(sid)
            if not session:
                await send({"type": "deleted"})
                await websocket.close(code=1000)
                return
            await send({"type": "snapshot", "session": session})
            await asyncio.sleep(0.5)

    try:
        session = get_session(s, sid)
        if session["state"] != "CREATED" or session["mode"] != "microphone":
            raise ValueError("SESSION_NOT_STARTABLE")
        first = await asyncio.wait_for(websocket.receive_json(), timeout=10)
        start = StartFrame.model_validate(first)
        check_ready(s, Options(**session["options"]), live=True)
        s.claim(sid)
        try:
            live = LiveSession(sid, start, s)
            await live.initialize()
        except BaseException:
            s.release(sid)
            raise
        sender = asyncio.create_task(updates())
        await send({"type": "ack", "action": "start", "stream_id": start.stream_id})
        while True:
            message = await asyncio.wait_for(websocket.receive(), timeout=15)
            if message["type"] == "websocket.disconnect":
                raise WebSocketDisconnect()
            if message.get("bytes") is not None:
                warning = await live.receive(message["bytes"])
                if warning:
                    await send(warning)
                await send({"type": "ack", "sequence": live.stream.next_sequence - 1})
            else:
                stop = StopFrame.model_validate_json(message.get("text", ""))
                if stop.last_sequence != live.stream.next_sequence - 1:
                    await send(
                        {
                            "type": "error",
                            "code": "STOP_SEQUENCE_MISMATCH",
                            "received_sequence": live.stream.next_sequence - 1,
                        }
                    )
                    continue
                closing = True
                finish_task = s.launch(live.finish())
                await send({"type": "ack", "action": "stop", "last_sequence": stop.last_sequence})
                await asyncio.shield(finish_task)
                await send({"type": "snapshot", "session": s.repo.get(sid)})
                await send({"type": "completed"})
                break
    except WebSocketDisconnect:
        pass
    except Exception as exc:
        try:
            await send(
                {
                    "type": "error",
                    "code": str(exc) if isinstance(exc, (ValueError, HTTPException)) else type(exc).__name__,
                }
            )
        except Exception:
            pass
        if live and live.alive():
            s.repo.warning(sid, {"type": "stream.interrupted", "code": type(exc).__name__})
    finally:
        if live and not closing:
            s.launch(live.finish(interrupted=True))
        if sender:
            sender.cancel()
            await asyncio.gather(sender, return_exceptions=True)
        try:
            await websocket.close()
        except Exception:
            pass
