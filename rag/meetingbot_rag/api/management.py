"""Embedding installation, runtime settings, LLM connections, and prompts."""

import asyncio
from contextlib import suppress

from fastapi import APIRouter, Request

from ..llm_settings import LLMSettingsUpdate, ModelCheck, PromptActivation, PromptInput, PromptPreview
from ..managed_proxy import CodexAccountAction, CodexCallback
from ..runtime_settings import RAGSettingsUpdate

router = APIRouter(prefix="/api/rag")


def embedding_status(request: Request):
    task = request.app.state.embedding_install
    installing = task is not None and not task.done()
    health = request.app.state.core.model.health()
    if installing and health["state"] != "READY":
        health = {**health, "state": "DOWNLOADING", "error_code": None}
    return {**health, "installing": installing}


@router.get("/embedding")
def embedding(request: Request):
    return embedding_status(request)


@router.post("/embedding/install", status_code=202)
async def install_embedding(request: Request):
    task = request.app.state.embedding_install
    if request.app.state.core.model.health()["state"] == "READY" or (task is not None and not task.done()):
        return embedding_status(request)

    async def install():
        await request.app.state.embedding_prepare
        # Only the administrator-configured, pinned embedding model is installed.
        # LocalEmbedding records a safe error code; never expose download exceptions.
        with suppress(Exception):
            await asyncio.to_thread(request.app.state.core.model.load, download=True)

    request.app.state.embedding_install = asyncio.create_task(install())
    return embedding_status(request)


@router.get("/settings")
def rag_settings(request: Request):
    return request.app.state.core.runtime_settings.public()


@router.put("/settings")
def save_rag_settings(request: Request, body: RAGSettingsUpdate):
    return request.app.state.core.runtime_settings.save(body)


@router.get("/diagnostics")
def diagnostics(request: Request):
    return {
        "model": request.app.state.core.model.health(),
        "llm": request.app.state.answer.policy(),
        "access_mode": request.app.state.core.s.access_mode,
        "public_origin": request.app.state.core.s.public_origin,
        "history_days": request.app.state.core.s.history_days,
        "versions": "명시적 삭제 전까지 보존",
        "limits": {
            k: getattr(request.app.state.core.s, k)
            for k in ("max_files", "max_file_bytes", "max_total_bytes", "max_chunks", "parse_seconds")
        },
    }


@router.post("/diagnostics/llm-check")
def llm_check(request: Request):
    return request.app.state.answer.factory.check()


@router.get("/llm/settings")
def llm_settings(request: Request):
    return request.app.state.answer.settings.public()


@router.patch("/llm/settings")
def save_llm_settings(request: Request, body: LLMSettingsUpdate):
    return request.app.state.answer.settings.save(body)


@router.get("/llm/models")
def llm_models(request: Request):
    return request.app.state.answer.settings.catalog()


@router.post("/llm/models/refresh")
def refresh_llm_models(request: Request):
    return request.app.state.answer.factory.models()


@router.post("/llm/check")
def check_llm_model(request: Request, body: ModelCheck):
    return request.app.state.answer.factory.check(body.model)


@router.get("/llm/codex/status")
def codex_status(request: Request):
    return request.app.state.proxy.status()


@router.post("/llm/codex/login")
def codex_login(request: Request):
    return request.app.state.proxy.start()


@router.post("/llm/codex/accounts/select")
def codex_select_account(request: Request, body: CodexAccountAction):
    return request.app.state.proxy.select_account(body)


@router.post("/llm/codex/accounts/delete")
def codex_delete_account(request: Request, body: CodexAccountAction):
    return request.app.state.proxy.delete_account(body)


@router.post("/llm/codex/callback")
def codex_callback(request: Request, body: CodexCallback):
    return request.app.state.proxy.callback(body)


@router.post("/llm/codex/use")
def codex_use(request: Request, body: LLMSettingsUpdate):
    return request.app.state.proxy.use(body.expected_version)


@router.get("/prompts")
def prompts(request: Request):
    return request.app.state.answer.prompts.list()


@router.get("/prompts/active")
def active_prompt(request: Request):
    return request.app.state.answer.prompts.active()


@router.post("/prompts/preview")
def preview_prompt(request: Request, body: PromptPreview):
    return request.app.state.answer.preview(body)


@router.post("/prompts/test")
def test_prompt(request: Request, body: PromptPreview):
    return request.app.state.answer.preview(body, live=True)


@router.get("/prompts/{pid}")
def prompt(request: Request, pid: str):
    return request.app.state.answer.prompts.get(pid)


@router.post("/prompts", status_code=201)
def save_prompt(request: Request, body: PromptInput):
    return request.app.state.answer.prompts.save(body)


@router.post("/prompts/{pid}/activate")
def activate_prompt(request: Request, pid: str, body: PromptActivation):
    return request.app.state.answer.prompts.activate(pid, body.expected_active_id)


@router.post("/prompts/{pid}/restore")
def restore_prompt(request: Request, pid: str, body: PromptActivation):
    return request.app.state.answer.prompts.activate(pid, body.expected_active_id, restore=True)
