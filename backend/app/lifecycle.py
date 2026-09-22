"""Own the STT repository, workers, and background tasks for one application."""

import asyncio
import time
from contextlib import asynccontextmanager

from meetingbot_access import AccessStore

from app.modules.meeting.router import RagBridge
from app.modules.meeting.subscriptions import SubscriptionDelivery
from app.modules.stt.file_service import FileService
from app.modules.stt.repository import Repository
from app.modules.system.manager import RuntimeManager


def create_lifespan(settings, worker_factory):
    @asynccontextmanager
    async def lifespan(app):
        # Only this service's generated temporary files are eligible for startup cleanup.
        for path in (settings.data_dir / "tmp").glob("session_*.input"):
            path.unlink(missing_ok=True)
        for path in (settings.data_dir / "tmp").glob("session_*.f32"):
            if not path.with_suffix(".diar.json").exists():
                path.unlink(missing_ok=True)
        app.state.audit.emit("service.starting", demo=settings.demo_mode, keyless=settings.keyless_login)
        repo = Repository(settings.data_dir / "stt.sqlite3", audit=app.state.audit)
        workers = worker_factory(settings)
        app.state.service = FileService(settings, repo, workers)
        app.state.runtime = RuntimeManager(app.state.service, worker_factory)
        app.state.token = settings.local_token()
        app.state.access = AccessStore(settings.data_dir / "local-token", settings.access_db, audit=app.state.audit)
        app.state.rag_bridge = RagBridge(settings)
        app.state.meeting_delivery = SubscriptionDelivery(repo, app.state.rag_bridge, app.state.access)

        async def expire_demo_records():
            while True:
                if settings.demo_mode:
                    service = app.state.service
                    for item in repo.list():
                        if item["id"] != service.active and item["created_at"] < time.time() - 86400:
                            repo.delete(item["id"])
                            for folder in ("tmp", "audio"):
                                for path in (settings.data_dir / folder).glob(item["id"] + ".*"):
                                    path.unlink(missing_ok=True)
                await asyncio.sleep(600)

        async def prepare():
            try:
                await workers.prepare()
            except BaseException as exc:
                app.state.audit.emit("workers.failed", error_type=type(exc).__name__)
                raise
            app.state.audit.emit("workers.ready")
            app.state.service.resume_pending()
            try:
                from app.modules.stt.engines.silero_vad import SileroVAD

                await asyncio.to_thread(SileroVAD, settings.engine == "fake")
                workers.health["vad"] = {"ready": True, "runtime": "onnx"}
            except Exception as exc:
                workers.health["vad"] = {"ready": False, "error": type(exc).__name__}

        task = asyncio.create_task(prepare())
        expiry = asyncio.create_task(expire_demo_records())
        meeting_delivery = asyncio.create_task(app.state.meeting_delivery.run())
        app.state.runtime.startup_task = task
        yield
        expiry.cancel()
        meeting_delivery.cancel()
        await asyncio.gather(expiry, meeting_delivery, return_exceptions=True)
        await app.state.runtime.close()
        await task
        await asyncio.gather(*app.state.service.tasks, return_exceptions=True)
        app.state.service.workers.close()
        repo.db.close()
        app.state.audit.emit("service.stopped")
        app.state.audit.close()

    return lifespan
