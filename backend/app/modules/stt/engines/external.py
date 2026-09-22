"""Keep browser-installed engine dependencies outside the running API environment."""
import atexit
import base64
import json
import os
import queue
import subprocess
import threading
from pathlib import Path

import numpy as np

from .base import ASRResult, Word


class ExternalASR:
    def __init__(self, executable, engine, path):
        runner = Path(__file__).with_name("runner.py")
        self.process = subprocess.Popen(
            [executable, str(runner), engine, path], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL, text=True, encoding="utf-8",
            env={**os.environ, "HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1"},
        )
        atexit.register(self.close)
        self._read()

    def _read(self):
        output = queue.Queue(maxsize=1)
        threading.Thread(target=lambda: output.put(self.process.stdout.readline()), daemon=True).start()
        try:
            line = output.get(timeout=1800)
        except queue.Empty:
            self.close()
            raise RuntimeError("ENGINE_PROCESS_TIMEOUT") from None
        if not line:
            self.close()
            raise RuntimeError("ENGINE_PROCESS_FAILED")
        result = json.loads(line)
        if "error" in result:
            raise RuntimeError(result["error"])
        return result

    def transcribe(self, audio, options):
        encoded = base64.b64encode(np.asarray(audio, dtype="<f4").tobytes()).decode("ascii")
        self.process.stdin.write(json.dumps({"audio": encoded, "options": options}) + "\n")
        self.process.stdin.flush()
        result = self._read()
        return ASRResult([Word(**w) for w in result["words"]], result["language"], result["diagnostics"])

    def close(self):
        if self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=5)
