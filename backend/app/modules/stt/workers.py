import asyncio
import json
import multiprocessing
import os
import time
from concurrent.futures import ProcessPoolExecutor
from functools import partial
from pathlib import Path
from tempfile import TemporaryDirectory

import numpy as np

from app.modules.system.catalog import worker_manifest

from .audio import close_mapped_audio

_ENGINES = {}


def initialize(kind, mode, manifest, diar_config=None):
    os.environ["PYANNOTE_METRICS_ENABLED"] = "0"
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "1"
    os.environ["TOKENIZERS_PARALLELISM"] = "false"
    os.environ.setdefault("PYTORCH_ENABLE_MPS_FALLBACK", "1")
    _ENGINES.update(kind=kind, mode=mode, manifest=manifest, diar_config=diar_config or {})


def prepare():
    kind, mode, manifest = (_ENGINES[k] for k in ("kind", "mode", "manifest"))
    start = time.perf_counter()
    ready = {}
    if mode == "fake":
        from .engines.fake import FakeASR, FakeDiarizer

        _ENGINES["small"] = FakeASR() if kind == "asr" else FakeDiarizer()
        return {"ready": True, "mode": "fake", "models": {"small": {"ready": True}}, "load_seconds": 0}
    keys = ["small", "large-v3-turbo"] if kind == "asr" else ["diarization"]
    for key in keys:
        if key not in manifest:
            continue
        try:
            if kind == "asr":
                entry = manifest[key]
                if entry.get("runtime_python"):
                    from .engines.external import ExternalASR

                    engine = ExternalASR(entry["runtime_python"], entry["engine"], entry["path"])
                elif entry.get("engine", "mlx") == "faster-whisper":
                    from .engines.faster_whisper_engine import FasterWhisperEngine

                    engine = FasterWhisperEngine(entry["path"])
                else:
                    from .engines.mlx_whisper_engine import MLXWhisperEngine

                    engine = MLXWhisperEngine(entry["path"])
            else:
                from .engines.pyannote_engine import PyannoteEngine

                engine = PyannoteEngine(manifest[key]["path"], **_ENGINES["diar_config"])
            _ENGINES[key] = engine
            ready[key] = {"ready": True, "revision": manifest[key]["revision"]}
            if kind == "diar":
                ready[key].update(device=engine.device, cpu_threads=engine.cpu_threads)
        except Exception as exc:
            ready[key] = {"ready": False, "error": type(exc).__name__}
    return {
        "ready": any(v["ready"] for v in ready.values()),
        "models": ready,
        "mode": mode,
        "load_seconds": time.perf_counter() - start,
    }


def infer(audio, options, progress_path=None):
    mapped = None
    if isinstance(audio, dict) and "pcm_path" in audio:
        # Map shared disk audio inside the worker instead of pickling hours of PCM.
        audio = mapped = np.memmap(audio["pcm_path"], dtype="<f4", mode="c")
    try:
        key = options["model"] if _ENGINES["kind"] == "asr" else "diarization"
        if _ENGINES["mode"] == "fake":
            key = "small"
        engine = _ENGINES.get(key)
        if engine is None:
            raise RuntimeError("MODEL_NOT_READY")
        start = time.perf_counter()
        if _ENGINES["kind"] == "asr":
            result = engine.transcribe(audio, options)
        elif progress_path and _ENGINES["mode"] != "fake":
            from .progress import write_progress

            result = engine.diarize(audio, options, progress=partial(write_progress, progress_path))
        else:
            result = engine.diarize(audio, options)
        result.diagnostics["inference_seconds"] = time.perf_counter() - start
        return result
    finally:
        close_mapped_audio(mapped)


class Workers:
    def __init__(self, settings):
        self.manifest = worker_manifest(settings)
        self.progress_dir = settings.data_dir / "tmp"
        diar_config = {
            "device": settings.diarization_device,
            "cpu_threads": settings.diarization_cpu_threads,
            "batch_size": settings.diarization_batch_size,
        }
        self.pools = {
            kind: ProcessPoolExecutor(
                max_workers=1,
                mp_context=multiprocessing.get_context("spawn"),
                initializer=initialize,
                initargs=(kind, settings.engine, self.manifest, diar_config),
            )
            for kind in ("asr", "diar")
        }
        self.health = {kind: {"ready": False, "state": "loading"} for kind in self.pools}

    async def prepare(self):
        async def one(kind):
            try:
                self.health[kind] = await asyncio.get_running_loop().run_in_executor(
                    self.pools[kind], prepare
                )
            except Exception as exc:
                self.health[kind] = {"ready": False, "error": type(exc).__name__}

        await asyncio.gather(*(one(k) for k in self.pools))

    async def run(self, kind, audio, options, on_progress=None):
        if kind == "diar" and isinstance(audio, np.memmap):
            audio = {"pcm_path": str(audio.filename)}
        loop = asyncio.get_running_loop()
        if not on_progress:
            return await loop.run_in_executor(self.pools[kind], infer, audio, options)
        with TemporaryDirectory(prefix="diar-progress-", dir=self.progress_dir) as directory:
            path = Path(directory) / "progress.json"
            previous = None

            def deliver():
                nonlocal previous
                try:
                    raw = path.read_text()
                except FileNotFoundError:
                    return
                if raw != previous:
                    on_progress(json.loads(raw))
                    previous = raw

            future = loop.run_in_executor(self.pools[kind], infer, audio, options, str(path))
            while not future.done():
                await asyncio.wait({future}, timeout=0.5)
                deliver()
            deliver()
            result = await future
            model = self.health[kind].get("models", {}).get("diarization")
            if model is not None and "device" in result.diagnostics:
                model["device"] = result.diagnostics["device"]
            return result

    def close(self):
        for pool in self.pools.values():
            pool.shutdown(wait=False, cancel_futures=True)
