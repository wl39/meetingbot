"""Small, throttled progress messages; model tensors never cross this channel."""

import json
import time
from pathlib import Path


class DiarizationProgress:
    def __init__(self, callback, device, fallback=False):
        self.callback = callback
        self.device = {"cpu": 0, "mps": 1, "cuda": 2}[device]
        self.fallback = fallback
        self.started = time.time()
        self.last = 0.0
        self.stage = 0

    def emit(self, stage, completed=0, total=0, force=False):
        now = time.time()
        if not self.callback:
            return
        if not force and stage == self.stage and now - self.last < 0.5:
            return
        self.stage, self.last = stage, now
        total = max(0, int(total))
        completed = min(total, max(0, int(completed))) if total else 0
        self.callback({
            "diar_stage": stage,
            "diar_completed": completed,
            "diar_total": total,
            "diar_stage_percent": round(100 * completed / total, 1) if total else 0,
            "diar_started_at": self.started,
            "diar_updated_at": now,
            "diar_device": self.device,
            "diar_cpu_fallback": int(self.fallback),
        })

    def start(self):
        self.emit(1, force=True)

    def hook(self, name, artifact, *, completed=None, total=None, **kwargs):
        if name == "segmentation":
            if total is not None:
                self.emit(1, completed or 0, total, force=completed is not None and completed >= total)
            else:
                self.emit(2, force=True)
        elif name == "speaker_counting":
            self.emit(2, force=True)
        elif name == "embeddings":
            if total is not None:
                self.emit(2, completed or 0, total, force=completed is not None and completed >= total)
            else:
                self.emit(3, force=True)
        elif name == "discrete_diarization":
            self.emit(4, force=True)

    def finish(self):
        self.emit(5, 1, 1, force=True)


def write_progress(path, metrics):
    path = Path(path)
    temporary = path.with_suffix(".tmp")
    try:
        temporary.write_text(json.dumps(metrics))
        temporary.replace(path)
    except (FileNotFoundError, PermissionError):
        # The task may have removed its directory, or a Windows progress reader
        # may briefly prevent replacement. Progress must not fail inference.
        pass
