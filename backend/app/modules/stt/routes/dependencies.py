"""Shared session lookup and worker readiness checks for STT routes."""

from fastapi import HTTPException


def resources(request):
    return request.app.state.service


def get_session(service, sid):
    result = service.repo.get(sid)
    if not result:
        raise HTTPException(404, "SESSION_NOT_FOUND")
    return result


def check_ready(service, options, live=False):
    if service.management_busy:
        raise HTTPException(409, "MANAGEMENT_BUSY")
    if "model" not in options.model_fields_set:
        options.model = service.settings.default_model
    health = service.workers.health["asr"]
    if not health.get("ready"):
        raise HTTPException(503, "ASR_MODEL_NOT_READY")
    if service.settings.engine != "fake":
        if not health.get("models", {}).get(options.model, {}).get("ready"):
            raise HTTPException(503, "SELECTED_MODEL_NOT_READY")
        if live and not service.workers.health.get("vad", {}).get("ready"):
            raise HTTPException(503, "VAD_NOT_READY")
    if service.active:
        raise HTTPException(409, "BUSY")
