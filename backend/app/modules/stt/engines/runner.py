"""Line-based private worker protocol. The runner has no HTTP or download capability."""
import base64
import contextlib
import json
import sys
from dataclasses import asdict
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[4]))


def main():
    with contextlib.redirect_stdout(sys.stderr):
        if sys.argv[1] == "mlx":
            from app.modules.stt.engines.mlx_whisper_engine import MLXWhisperEngine as Engine
        elif sys.argv[1] == "faster-whisper":
            from app.modules.stt.engines.faster_whisper_engine import FasterWhisperEngine as Engine
        else:
            raise ValueError("UNKNOWN_ENGINE")
        engine = Engine(sys.argv[2])
    print(json.dumps({"ready": True}), flush=True)
    for line in sys.stdin:
        try:
            request = json.loads(line)
            audio = np.frombuffer(base64.b64decode(request["audio"]), dtype="<f4").copy()
            with contextlib.redirect_stdout(sys.stderr):
                result = engine.transcribe(audio, request["options"])
            print(json.dumps(asdict(result)), flush=True)
        except Exception as exc:
            print(json.dumps({"error": type(exc).__name__}), flush=True)


if __name__ == "__main__":
    main()
