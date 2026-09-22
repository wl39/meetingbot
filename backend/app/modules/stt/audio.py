import json
import shutil
import struct
import subprocess
import wave
from pathlib import Path

import numpy as np
import soxr


def binary(name):
    return shutil.which(name) or str(Path("/opt/homebrew/bin") / name)


def close_mapped_audio(audio):
    """Release PCM file handles before unlinking them, including on Windows."""
    if isinstance(audio, np.memmap):
        audio._mmap.close()


class AudioDecodeError(ValueError):
    def __init__(self, code, **details):
        super().__init__(code)
        self.code = code
        self.details = details


def run_audio_tool(args, timeout, output=None):
    try:
        return subprocess.run(
            args, stdout=output or subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout, check=True
        )
    except FileNotFoundError as exc:
        raise AudioDecodeError("AUDIO_TOOL_MISSING") from exc
    except subprocess.TimeoutExpired as exc:
        raise AudioDecodeError("AUDIO_DECODE_TIMEOUT") from exc
    except subprocess.CalledProcessError as exc:
        # Do not expose stderr: it can contain paths or media metadata.
        raise AudioDecodeError(
            "AUDIO_PROBE_FAILED" if "ffprobe" in args[0] else "AUDIO_DECODE_FAILED"
        ) from exc


def decode(path: Path, max_seconds: int, output_path: Path | None = None):
    probe = run_audio_tool(
        [
            binary("ffprobe"),
            "-v",
            "error",
            "-protocol_whitelist",
            "file,pipe",
            "-format_whitelist",
            "wav,mp3,mov,flac",
            "-show_format",
            "-show_streams",
            "-of",
            "json",
            str(path),
        ],
        timeout=15,
    )
    info = json.loads(probe.stdout)
    streams = [s for s in info["streams"] if s["codec_type"] == "audio"]
    if not streams:
        raise AudioDecodeError("NO_AUDIO_STREAM")
    # Some valid recordings have no duration (or "N/A") in their container.
    # In that case use the bounded decoded sample count as the authority.
    duration = None
    for value in (info.get("format", {}).get("duration"), streams[0].get("duration")):
        try:
            candidate = float(value)
        except (TypeError, ValueError):
            continue
        if np.isfinite(candidate) and candidate > 0:
            duration = candidate
            break
    if duration is not None and duration > max_seconds:
        raise AudioDecodeError("AUDIO_TOO_LONG", duration_seconds=duration, max_seconds=max_seconds)
    command = [
        binary("ffmpeg"),
        "-nostdin",
        "-v",
        "error",
        "-protocol_whitelist",
        "file,pipe",
        "-format_whitelist",
        "wav,mp3,mov,flac",
        "-i",
        str(path),
        "-map",
        "0:a:0",
        "-t",
        str(max_seconds + 1),
        "-ac",
        "1",
        "-ar",
        "16000",
        "-f",
        "f32le",
        "pipe:1",
    ]
    timeout = max(90, max_seconds // 5)
    if output_path is None:
        result = run_audio_tool(command, timeout=timeout)
        audio = np.frombuffer(result.stdout, dtype="<f4").copy()
    else:
        try:
            with output_path.open("wb") as output:
                run_audio_tool(command, timeout=timeout, output=output)
            if not output_path.stat().st_size:
                raise AudioDecodeError("INVALID_DECODED_AUDIO")
            audio = np.memmap(output_path, dtype="<f4", mode="r")
        except BaseException:
            output_path.unlink(missing_ok=True)
            raise
    try:
        if len(audio) > max_seconds * 16000:
            raise AudioDecodeError("AUDIO_TOO_LONG", duration_seconds=len(audio) / 16000, max_seconds=max_seconds)
        if not len(audio) or any(
            not np.isfinite(audio[i : i + 16000 * 60]).all() for i in range(0, len(audio), 16000 * 60)
        ):
            raise AudioDecodeError("INVALID_DECODED_AUDIO")
    except BaseException:
        # Exception tracebacks keep local arrays alive after this function exits.
        close_mapped_audio(audio)
        if output_path is not None:
            output_path.unlink(missing_ok=True)
        raise
    return audio, {
        "duration_seconds": len(audio) / 16000,
        "source_channels": streams[0]["channels"],
        "downmixed": streams[0]["channels"] != 1,
        "sample_rate": 16000,
    }


def save_wav(path, audio):
    with wave.open(str(path), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(16000)
        for i in range(0, len(audio), 16000 * 60):
            output.writeframes((np.clip(audio[i : i + 16000 * 60], -1, 1) * 32767).astype("<i2").tobytes())


class PCMStream:
    """Wire: little endian uint32 sequence, uint64 start sample, uint32 count, then f32 mono.

    Session, stream ID and sample rate are fixed by the authenticated WS handshake.
    """

    def __init__(self, rate, max_seconds):
        self.rate = rate
        self.max_samples = rate * max_seconds
        self.next_sequence = 0
        self.next_sample = 0
        self.resampler = soxr.ResampleStream(rate, 16000, 1, dtype="float32", quality="HQ")

    def push(self, payload):
        if len(payload) < 16:
            raise ValueError("SHORT_AUDIO_FRAME")
        sequence, start, count = struct.unpack_from("<IQI", payload)
        if count == 0 or count > self.rate or len(payload) != 16 + count * 4:
            raise ValueError("INVALID_AUDIO_FRAME")
        if sequence < self.next_sequence or start < self.next_sample:
            raise ValueError("OUT_OF_ORDER_AUDIO")
        if start + count > self.max_samples:
            raise ValueError("SESSION_LIMIT")
        gap = start - self.next_sample
        if gap > self.rate * 5:
            raise ValueError("AUDIO_GAP_TOO_LARGE")
        audio = np.frombuffer(payload, dtype="<f4", offset=16).copy()
        if not np.isfinite(audio).all() or np.any(np.abs(audio) > 1.001):
            raise ValueError("INVALID_PCM_VALUES")
        warning = None
        if gap or sequence != self.next_sequence:
            warning = {
                "type": "audio.gap",
                "start_sample": self.next_sample,
                "missing_samples": gap,
                "expected_sequence": self.next_sequence,
                "received_sequence": sequence,
                "sample_rate": self.rate,
            }
        if gap:
            audio = np.concatenate((np.zeros(gap, dtype=np.float32), audio))
        self.next_sample = start + count
        self.next_sequence = sequence + 1
        return self.resampler.resample_chunk(audio), warning

    def flush(self):
        return self.resampler.resample_chunk(np.empty(0, dtype=np.float32), last=True)
