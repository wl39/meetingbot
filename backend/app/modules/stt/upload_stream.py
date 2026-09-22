"""Seekable, bounded upload storage and a loopback-only range reader for FFmpeg.

M4A metadata may follow the audio. Clients send metadata blocks first; FFmpeg
can then seek through the source while unavailable audio blocks wait for upload.
"""

import asyncio
import json
import math
import os
import re
import secrets
import threading
import time
from pathlib import Path

import numpy as np

from .audio import AudioDecodeError, binary


class StreamingUpload:
    chunk_bytes = 1024 * 1024
    idle_seconds = 120

    def __init__(self, path: Path, size: int):
        self.path, self.size = path, size
        self.count = math.ceil(size / self.chunk_bytes)
        self.io_lock = threading.Lock()
        self.fd = os.open(path, os.O_RDWR | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0), 0o600)
        try:
            os.ftruncate(self.fd, size)
        except BaseException:
            os.close(self.fd)
            path.unlink(missing_ok=True)
            raise
        self.received = set()
        self.changed = asyncio.Condition()
        self.complete = False
        self.closed = False
        self.last_activity = time.monotonic()
        self.server = None
        self.process = None
        self.readers = set()
        self.reader_tasks = set()
        self.probed = False
        self.diagnostics = {}
        self.secret = secrets.token_urlsafe(32)

    def read_at(self, size, offset):
        # Windows has no pread/pwrite. Serialize seek+I/O and close so parallel
        # FFmpeg range readers and uploads never share a mutable file position.
        with self.io_lock:
            if self.fd is None:
                raise OSError("UPLOAD_CLOSED")
            pread = getattr(os, "pread", None)
            if pread is not None:
                return pread(self.fd, size, offset)
            os.lseek(self.fd, offset, os.SEEK_SET)
            return os.read(self.fd, size)

    def write_at(self, body, offset):
        with self.io_lock:
            if self.fd is None:
                raise OSError("UPLOAD_CLOSED")
            pwrite = getattr(os, "pwrite", None)
            if pwrite is None:
                os.lseek(self.fd, offset, os.SEEK_SET)
            written = 0
            while written < len(body):
                count = (pwrite(self.fd, body[written:], offset + written) if pwrite is not None
                         else os.write(self.fd, body[written:]))
                if count <= 0:
                    raise OSError("SHORT_SOURCE_WRITE")
                written += count

    def check(self):
        if self.closed:
            raise AudioDecodeError("UPLOAD_CANCELLED")
        if not self.complete and time.monotonic() - self.last_activity > self.idle_seconds:
            raise AudioDecodeError("UPLOAD_INTERRUPTED")

    async def put(self, index, body):
        self.check()
        expected = min(self.chunk_bytes, self.size - index * self.chunk_bytes)
        if index < 0 or index >= self.count or len(body) != expected:
            raise ValueError("INVALID_UPLOAD_CHUNK")
        async with self.changed:
            self.check()
            if index in self.received:
                raise ValueError("DUPLICATE_UPLOAD_CHUNK")
            offset = index * self.chunk_bytes
            await asyncio.to_thread(self.write_at, body, offset)
            self.received.add(index)
            self.last_activity = time.monotonic()
            self.changed.notify_all()

    async def finish(self):
        async with self.changed:
            self.check()
            if len(self.received) != self.count:
                raise ValueError("UPLOAD_INCOMPLETE")
            self.complete = True
            self.changed.notify_all()

    async def wait_for_block(self, index):
        async with self.changed:
            while index not in self.received:
                self.check()
                try:
                    await asyncio.wait_for(self.changed.wait(), 1)
                except TimeoutError:
                    pass

    async def read_http(self, reader, writer):
        self.readers.add(writer)
        task = asyncio.current_task()
        self.reader_tasks.add(task)
        try:
            header = await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), 10)
            lines = header.decode("ascii").split("\r\n")
            method, path, _ = lines[0].split()
            if method not in {"GET", "HEAD"} or path != "/" + self.secret:
                writer.write(b"HTTP/1.1 404 Not Found\r\nContent-Length: 0\r\nConnection: close\r\n\r\n")
                await writer.drain()
                return
            headers = dict(line.lower().split(":", 1) for line in lines[1:] if ":" in line)
            value = headers.get("range", "").strip()
            start, end = 0, self.size - 1
            if value:
                match = re.fullmatch(r"bytes=(\d+)-(\d*)", value)
                if not match:
                    raise ValueError("INVALID_RANGE")
                start = int(match[1])
                end = min(int(match[2]) if match[2] else end, end)
                if not 0 <= start <= end < self.size:
                    raise ValueError("INVALID_RANGE")
            status = "206 Partial Content" if value else "200 OK"
            response = f"HTTP/1.1 {status}\r\nContent-Type: application/octet-stream\r\nAccept-Ranges: bytes\r\nContent-Length: {end - start + 1}\r\nConnection: close\r\n"
            if value:
                response += f"Content-Range: bytes {start}-{end}/{self.size}\r\n"
            writer.write((response + "\r\n").encode())
            await writer.drain()
            if method == "HEAD":
                return
            while start <= end:
                self.check()
                index = start // self.chunk_bytes
                await self.wait_for_block(index)
                size = min(end - start + 1, (index + 1) * self.chunk_bytes - start)
                data = await asyncio.to_thread(self.read_at, size, start)
                if len(data) != size:
                    raise ValueError("SHORT_SOURCE_READ")
                writer.write(data)
                await writer.drain()
                start += size
        except (OSError, ValueError, TimeoutError, asyncio.IncompleteReadError, asyncio.LimitOverrunError):
            pass
        finally:
            self.readers.discard(writer)
            self.reader_tasks.discard(task)
            writer.close()

    async def command(self, args, output=None):
        self.process = await asyncio.create_subprocess_exec(
            *args, stdout=output or asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        try:
            stdout, _ = await self.process.communicate()
            if self.process.returncode:
                self.check()
                raise AudioDecodeError("AUDIO_DECODE_FAILED")
            return stdout
        finally:
            if self.process.returncode is None:
                self.process.kill()
                await self.process.wait()
            self.process = None

    async def decode(self, pcm_path, max_seconds):
        self.server = await asyncio.start_server(self.read_http, "127.0.0.1", 0, limit=8192)
        port = self.server.sockets[0].getsockname()[1]
        url = f"http://127.0.0.1:{port}/{self.secret}"
        # Only the generated loopback URL is accepted. Container allowlisting
        # excludes playlists; MOV external data references stay disabled.
        args = [
            "-v",
            "error",
            "-avioflags",
            "direct",
            "-seekable",
            "1",
            "-initial_request_size",
            "32768",
            "-request_size",
            "65536",
            "-rw_timeout",
            "120000000",
            "-protocol_whitelist",
            "http,tcp",
            "-format_whitelist",
            "wav,mp3,mov,flac",
        ]
        info = json.loads(
            await self.command(
                [binary("ffprobe"), *args, "-show_format", "-show_streams", "-of", "json", url]
            )
        )
        streams = [s for s in info.get("streams", []) if s.get("codec_type") == "audio"]
        if not streams:
            raise AudioDecodeError("NO_AUDIO_STREAM")
        self.diagnostics = {
            "source_channels": streams[0]["channels"],
            "downmixed": streams[0]["channels"] != 1,
            "sample_rate": 16000,
        }
        for value in (info.get("format", {}).get("duration"), streams[0].get("duration")):
            try:
                duration = float(value)
            except (ValueError, TypeError):
                continue
            if np.isfinite(duration) and duration > 0:
                if duration > max_seconds:
                    raise AudioDecodeError(
                        "AUDIO_TOO_LONG", duration_seconds=duration, max_seconds=max_seconds
                    )
                self.diagnostics["duration_seconds"] = duration
                break
        self.probed = True
        with pcm_path.open("wb") as output:
            await self.command(
                [
                    binary("ffmpeg"),
                    "-nostdin",
                    *args,
                    "-i",
                    url,
                    "-map",
                    "0:a:0",
                    "-t",
                    str(max_seconds + 1),
                    "-ac",
                    "1",
                    "-ar",
                    "16000",
                    "-flush_packets",
                    "1",
                    "-f",
                    "f32le",
                    "pipe:1",
                ],
                output,
            )
        samples = pcm_path.stat().st_size // 4
        if not samples:
            raise AudioDecodeError("INVALID_DECODED_AUDIO")
        if samples > max_seconds * 16000:
            raise AudioDecodeError(
                "AUDIO_TOO_LONG", duration_seconds=samples / 16000, max_seconds=max_seconds
            )
        self.diagnostics["duration_seconds"] = samples / 16000
        while not self.complete:
            self.check()
            await asyncio.sleep(0.1)
        return self.diagnostics

    async def close(self):
        async with self.changed:
            self.closed = True
            self.changed.notify_all()
        if self.process and self.process.returncode is None:
            try:
                self.process.terminate()
            except ProcessLookupError:
                pass
        if self.server:
            self.server.close()
            await self.server.wait_closed()
        for writer in list(self.readers):
            writer.close()
        await asyncio.gather(*list(self.reader_tasks), return_exceptions=True)
        # FileService cancels the decoder before disposing its source file.

    def dispose(self):
        with self.io_lock:
            if self.fd is not None:
                os.close(self.fd)
                self.fd = None
        self.path.unlink(missing_ok=True)
