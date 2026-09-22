"""Startup and shutdown ownership for models and background services."""

import asyncio
import logging
import time
from contextlib import asynccontextmanager, suppress

from meetingbot_access import AccessStore

from .answers import AnswerService
from .managed_proxy import ManagedProxy
from .meeting import MeetingService
from .meeting_jobs import MeetingJobs
from .process_lock import acquire_process_lock
from .query_history import QueryHistory
from .question_jobs import QuestionJobs
from .services import Core


def create_lifespan(s, model):
    @asynccontextmanager
    async def lifespan(app):
        lock = acquire_process_lock(s.data_dir / "service.lock")
        app.state.audit.emit("service.starting", demo=s.demo_mode, keyless=s.keyless_login)
        app.state.core = Core(s, model, audit=app.state.audit)
        app.state.access = AccessStore(s.auth_token_file, s.access_db, audit=app.state.audit)
        app.state.query_history = QueryHistory(app.state.core, app.state.access)
        app.state.answer = AnswerService(app.state.core)
        app.state.question_jobs = QuestionJobs(app.state.core, app.state.answer, app.state.query_history,
                                               app.state.access)
        app.state.meeting = MeetingService(app.state.core, app.state.answer)
        app.state.meeting_jobs = MeetingJobs(app.state.core, app.state.answer, app.state.meeting, app.state.access)
        app.state.meeting_jobs.start()
        app.state.proxy = ManagedProxy(app.state.answer)
        async def prepare_model():
            await asyncio.to_thread(model.load)
            if not app.state.question_jobs.stop.is_set():
                app.state.question_jobs.start()
        prepare = asyncio.create_task(prepare_model())
        app.state.embedding_prepare = prepare
        async def seed_demo():
            await prepare
            if not s.demo_mode:
                return
            try:
                spaces = app.state.core.workspaces.list()
                if not spaces:
                    spaces = [app.state.core.workspaces.create(
                        name="공개 데모 · 회의 운영 가이드", description="샘플 문서입니다. 운영 로그 보관 기간이나 회의 준비 절차를 검색해 보세요.",
                        root_id="demo", relative_path="")]
                for workspace in spaces:
                    if not workspace["active_revision_id"] and (workspace.get("source") or {}).get("root_id") == "demo":
                        app.state.core.ingestion.create(workspace["id"])
            except Exception as exc:
                logging.getLogger(__name__).error("Demo sample setup failed: %s", getattr(exc, "code", type(exc).__name__))
        seed = asyncio.create_task(seed_demo())
        app.state.embedding_install = None
        sweep = asyncio.create_task(app.state.core.uploads.sweep())
        async def expire_demo_questions():
            while True:
                if s.demo_mode:
                    app.state.core.db.execute(
                        "DELETE FROM query_runs WHERE created_at<? "
                        "AND json_extract(result,'$.status') NOT IN ('queued','processing')", (time.time() - 86400,)
                    )
                await asyncio.sleep(600)
        history_expiry = asyncio.create_task(expire_demo_questions())
        yield
        app.state.question_jobs.stop.set()
        history_expiry.cancel()
        await asyncio.gather(history_expiry, return_exceptions=True)
        sweep.cancel()
        with suppress(asyncio.CancelledError):
            await sweep
        await prepare
        await seed
        if app.state.embedding_install is not None:
            await app.state.embedding_install
        await asyncio.to_thread(app.state.meeting_jobs.close)
        await asyncio.to_thread(app.state.question_jobs.close)
        await asyncio.to_thread(app.state.core.close)
        lock.close()
        app.state.audit.emit("service.stopped")
        app.state.audit.close()

    return lifespan
