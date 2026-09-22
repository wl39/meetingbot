import asyncio
import importlib.util
import os
import platform
import shutil
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

from fastapi import HTTPException

from .catalog import (
    ENGINES,
    MODELS,
    default_engine,
    engine_installed,
    engine_python,
    installed_models,
    model_installed,
    python_in,
    read_json,
    supported,
    write_json,
)


def now():
    return datetime.now(timezone.utc).isoformat()


class RuntimeManager:
    def __init__(self, service, worker_factory):
        self.service = service
        self.worker_factory = worker_factory
        self.directory = service.settings.data_dir
        self.job_file = self.directory / "system-jobs.json"
        self.jobs = read_json(self.job_file, [])[-30:]
        self.task = None
        self.startup_task = None
        for job in self.jobs:
            if job["status"] in {"running", "queued"}:
                job.update(status="failed", error="INTERRUPTED", message="앱 종료로 중단되었습니다. 다시 시도해 주세요.",
                           finished_at=now(), progress=None)
        self._logged_jobs = {}
        self.persist()

    def persist(self):
        write_json(self.job_file, self.jobs)
        for job in self.jobs:
            state = (job["status"], job.get("stage"), job.get("error"))
            if self._logged_jobs.get(job["id"]) != state:
                self.service.repo.record("system.job_updated", job_id=job["id"], state=job["status"],
                                         stage=job.get("stage"), action=job.get("action"))
                self._logged_jobs[job["id"]] = state

    @property
    def busy(self):
        return self.task is not None and not self.task.done()

    def status(self):
        settings = self.service.settings
        engine = settings.asr_backend if settings.asr_backend != "auto" else default_engine()
        installed = installed_models(self.directory)
        return {
            "platform": {"os": platform.system(), "machine": platform.machine(), "python": platform.python_version()},
            "selection": {"engine": engine, "model": settings.default_model},
            "engines": [
                {"id": key, "name": spec["name"], "supported": supported(key),
                 "installed": engine_installed(self.directory, key),
                 "reason": None if supported(key) else "이 운영체제 또는 CPU에서는 지원되지 않습니다."}
                for key, spec in ENGINES.items()
            ],
            "models": [
                {"id": key, "engine": key.split(":")[0], "model": key.split(":")[1],
                 "name": "Whisper " + key.split(":")[1], "download_gb": spec["download_gb"],
                 "supported": supported(key.split(":")[0]),
                 "installed": model_installed(self.directory, *key.split(":")),
                 "revision": installed.get(key, {}).get("revision")}
                for key, spec in MODELS.items()
            ],
            "workers": self.service.workers.health,
            "active_session": self.service.active,
            "busy": self.busy,
            "jobs": list(reversed(self.jobs)),
            "updates": {"supported": False, "current_version": "0.1.0", "channel": None,
                        "reason": "검증된 배포 채널과 복구 가능한 앱 업데이트가 준비되면 이곳에서 제공합니다. 음성 엔진과 모델은 지금 설치하고 적용할 수 있습니다."},
            "storage": {"free_bytes": shutil.disk_usage(self.directory).free},
            "audio_tools": {name: shutil.which(name) is not None or Path("/opt/homebrew/bin", name).is_file()
                            for name in ("ffmpeg", "ffprobe")},
        }

    def submit(self, action, engine, model):
        if self.busy:
            raise HTTPException(409, "MANAGEMENT_BUSY")
        if not supported(engine):
            raise HTTPException(422, "ENGINE_UNSUPPORTED")
        if action == "selection":
            if self.startup_task is not None and not self.startup_task.done():
                raise HTTPException(409, "WORKERS_LOADING")
            if self.service.active:
                raise HTTPException(409, "TRANSCRIPTION_ACTIVE")
            if not model_installed(self.directory, engine, model) or not engine_installed(self.directory, engine):
                raise HTTPException(409, "MODEL_NOT_INSTALLED")
            # Claim before yielding to prevent a new HTTP/WS transcription racing the worker swap.
            self.service.management_busy = True
        job = {"id": "system_" + uuid.uuid4().hex, "action": action, "engine": engine, "model": model,
               "status": "queued", "stage": "queued", "message": "작업을 준비하고 있습니다.",
               "progress": None, "created_at": now(), "finished_at": None, "error": None}
        self.jobs = (self.jobs + [job])[-30:]
        self.persist()
        self.task = asyncio.create_task(self.execute(job))
        return job.copy()

    def stage(self, job, stage, message, progress=None):
        job.update(status="running", stage=stage, message=message, progress=progress)
        self.persist()

    async def execute(self, job):
        try:
            if job["action"] == "install":
                await self.install(job)
            else:
                await self.select(job)
            job.update(status="completed", stage="completed", progress=100,
                       message="설치가 완료되었습니다. 사용하기를 눌러 적용하세요." if job["action"] == "install"
                       else "새 음성 설정을 적용했습니다.")
        except asyncio.CancelledError:
            job.update(status="failed", error="INTERRUPTED", message="앱 종료로 작업이 중단되었습니다.")
            raise
        except Exception as exc:
            # Errors and logs can include local paths/tokens; expose a stable code only.
            code = str(exc) if str(exc) in {"ENGINE_INSTALL_FAILED", "MODEL_DOWNLOAD_FAILED", "UV_NOT_FOUND",
                                          "MODEL_LOAD_FAILED", "NOT_ENOUGH_DISK"} else type(exc).__name__
            job.update(status="failed", error=code, progress=None,
                       message="완료하지 못했습니다. 네트워크와 남은 공간을 확인한 뒤 다시 시도해 주세요.")
        finally:
            self.service.management_busy = False
            job["finished_at"] = now()
            self.persist()

    async def command(self, args, code, timeout=7200):
        environment = {**os.environ, "PYANNOTE_METRICS_ENABLED": "0", "HF_HUB_DISABLE_TELEMETRY": "1",
                       "HF_HUB_DISABLE_PROGRESS_BARS": "1", "UV_NO_PROGRESS": "1"}
        environment.pop("HF_HUB_OFFLINE", None)
        environment.pop("TRANSFORMERS_OFFLINE", None)
        process = await asyncio.create_subprocess_exec(
            *map(str, args), stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL,
            env=environment,
        )
        try:
            result = await asyncio.wait_for(process.wait(), timeout)
        except BaseException:
            if process.returncode is None:
                process.terminate()
                try:
                    await asyncio.wait_for(process.wait(), 5)
                except asyncio.TimeoutError:
                    process.kill()
                    await process.wait()
            raise
        if result:
            raise RuntimeError(code)

    def uv(self):
        executable = shutil.which("uv")
        if not executable and importlib.util.find_spec("uv"):
            import uv

            executable = uv.find_uv_bin()
        if not executable and Path("/opt/homebrew/bin/uv").is_file():
            executable = "/opt/homebrew/bin/uv"
        bootstrap = Path(__file__).resolve().parents[4] / ".bootstrap" / (
            "Scripts/uv.exe" if os.name == "nt" else "bin/uv"
        )
        if not executable and bootstrap.is_file():
            executable = str(bootstrap)
        if not executable:
            raise RuntimeError("UV_NOT_FOUND")
        return executable

    async def install(self, job):
        engine, model = job["engine"], job["model"]
        spec = MODELS[engine + ":" + model]
        if shutil.disk_usage(self.directory).free < (spec["download_gb"] + 2) * 1024 ** 3:
            raise RuntimeError("NOT_ENOUGH_DISK")
        executable = engine_python(self.directory, engine)
        if not executable:
            self.stage(job, "engine", "음성 엔진을 독립된 환경에 설치하고 있습니다.")
            directory = self.directory / "engines" / engine
            directory.parent.mkdir(parents=True, exist_ok=True)
            executable = python_in(directory)
            uv = self.uv()
            if not executable.is_file():
                await self.command([uv, "venv", "--python", sys.executable, str(directory)], "ENGINE_INSTALL_FAILED", 180)
            await self.command(
                [uv, "pip", "install", "--python", executable, "--index-url", "https://pypi.org/simple",
                 ENGINES[engine]["package"], "huggingface-hub>=0.34,<2", "numpy>=2,<3"],
                "ENGINE_INSTALL_FAILED",
            )
            await self.command([executable, "-c", "import " + ENGINES[engine]["module"]], "ENGINE_INSTALL_FAILED", 180)
            write_json(directory / "installed.json", {"engine": engine, "installed_at": now()})
        self.stage(job, "download", "음성 모델을 내려받고 있습니다. 다운로드 크기와 네트워크에 따라 시간이 걸릴 수 있습니다.")
        result = self.directory / "tmp" / (job["id"] + ".json")
        try:
            await self.command(
                [executable, Path(__file__).with_name("download.py"), spec["repo"],
                 self.directory / "models" / "hub", result], "MODEL_DOWNLOAD_FAILED",
            )
            entry = read_json(result, {})
            if entry.get("repo") != spec["repo"] or not entry.get("revision") or not Path(entry.get("path", "")).is_dir():
                raise RuntimeError("MODEL_DOWNLOAD_FAILED")
            manifest_file = self.directory / "models" / "manifest.json"
            manifest = read_json(manifest_file, {})
            manifest[engine + ":" + model] = entry
            write_json(manifest_file, manifest)
        finally:
            result.unlink(missing_ok=True)

    async def select(self, job):
        self.stage(job, "loading", "새 모델을 불러오고 있습니다. 준비가 끝나면 다음 전사부터 적용됩니다.")
        settings = self.service.settings.model_copy(update={"asr_backend": job["engine"], "default_model": job["model"]})
        candidate = self.worker_factory(settings)
        try:
            await candidate.prepare()
            health = candidate.health.get("asr", {})
            if not health.get("ready") or (settings.engine != "fake" and not health.get("models", {}).get(job["model"], {}).get("ready")):
                raise RuntimeError("MODEL_LOAD_FAILED")
            candidate.health["vad"] = self.service.workers.health.get("vad", {"ready": False})
            write_json(self.directory / "system-selection.json", {"engine": job["engine"], "model": job["model"]})
        except BaseException:
            candidate.close()
            raise
        previous = self.service.workers
        self.service.settings.asr_backend = job["engine"]
        self.service.settings.default_model = job["model"]
        self.service.workers = candidate
        self.service.environment.cache_clear()
        previous.close()

    async def close(self):
        if self.busy:
            self.task.cancel()
            await asyncio.gather(self.task, return_exceptions=True)
