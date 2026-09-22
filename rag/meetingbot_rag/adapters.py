import base64
import json
import re
import subprocess
import sys
import threading
import time
import unicodedata
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from .db import uid
from .sources import RagError


class ParserAdapter:
    def __init__(self, settings):
        self.s = settings

    def parse(self, data, suffix, allow_review=False):
        config = {
            k: getattr(self.s, k)
            for k in (
                "encodings",
                "max_rows",
                "max_columns",
                "max_cells",
                "max_sheets",
                "xlsx_uncompressed_bytes",
                "include_hidden",
            )
        }
        config["allow_review"] = allow_review
        payload = {"data": base64.b64encode(data).decode(), "suffix": suffix, "settings": config}
        try:
            process = subprocess.run(
                [sys.executable, "-m", "meetingbot_rag.parsers"],
                input=json.dumps(payload),
                capture_output=True,
                text=True,
                timeout=self.s.parse_seconds,
                cwd=Path(__file__).resolve().parents[1],
            )
            response = json.loads(process.stdout)
        except subprocess.TimeoutExpired:
            raise RagError("PARSING_TIMEOUT", "파일 파싱 시간 제한을 초과했습니다.") from None
        except Exception:
            raise RagError("PARSE_FAILED", "문서를 읽지 못했습니다.") from None
        if "error_code" in response:
            raise RagError(response["error_code"], "문서 형식 또는 표 구조를 확인하세요.")
        return response["result"]


class LocalEmbedding:
    def __init__(self, settings):
        self.s = settings
        self.lock = threading.RLock()
        self.state = "NOT_READY"
        self.error = None
        self.model = None
        self.dimension = 384
        self.limit = 512
        self.encoded_passages = 0
        self.device = "cpu"

    def load(self, download=False):
        with self.lock:
            if self.model is not None:
                return
            self.state = "DOWNLOADING" if download else "LOADING"
            try:
                import torch
                from sentence_transformers import SentenceTransformer

                torch.set_num_threads(2)
                self.device = self.s.embedding_device
                if self.device == "auto":
                    self.device = "mps" if torch.backends.mps.is_available() else "cpu"
                self.model = SentenceTransformer(
                    self.s.embedding_model,
                    revision=self.s.embedding_revision,
                    cache_folder=str(self.s.model_cache_dir or self.s.data_dir / "models"),
                    device=self.device,
                    local_files_only=not download,
                    trust_remote_code=False,
                )
                self.limit = min(self.model.max_seq_length, self.model.tokenizer.model_max_length)
                self.dimension = self.model.get_embedding_dimension()
                if self.dimension != 384:
                    raise ValueError("MODEL_DIMENSION_CHANGED")
                self.state, self.error = "READY", None
            except Exception:
                self.model = None
                self.state, self.error = (
                    "NOT_READY",
                    "MODEL_DOWNLOAD_REQUIRED" if not download else "MODEL_LOAD_FAILED",
                )
                if download:
                    raise

    def tokens(self, text):
        if self.model is None:
            raise RagError("MODEL_NOT_READY", "서버에서 모델을 준비하세요.", 503)
        return len(self.model.tokenizer.encode(text, add_special_tokens=True, truncation=False))

    def encode(self, texts, query=False):
        with self.lock:
            if self.model is None:
                raise RagError("MODEL_NOT_READY", "임베딩 모델을 준비하고 있습니다.", 503)
            inputs = [("query: " if query else "passage: ") + text for text in texts]
            if any(self.tokens(text) > self.limit for text in inputs):
                raise RagError(
                    "QUERY_TOO_LONG" if query else "CHUNK_TOO_LONG", "모델의 입력 토큰 한도를 초과했습니다."
                )
            try:
                vectors = self.model.encode(
                    inputs, batch_size=8, normalize_embeddings=True, show_progress_bar=False
                )
            except RuntimeError:
                if self.device != "mps":
                    raise
                self.model.to("cpu")
                self.device = "cpu"
                vectors = self.model.encode(
                    inputs, batch_size=8, normalize_embeddings=True, show_progress_bar=False
                )
            if not query:
                self.encoded_passages += len(texts)
            return vectors.tolist()

    def health(self):
        return {
            "state": self.state,
            "error_code": self.error,
            "model": self.s.embedding_model,
            "revision": self.s.embedding_revision,
            "device": self.device,
            "dimension": self.dimension,
            "max_tokens": self.limit,
            "normalized": True,
            "encoded_passages": self.encoded_passages,
        }


def chunk_document(parsed, relative_path, model, settings):
    result = []
    deadline = time.monotonic() + settings.parse_seconds
    if parsed["kind"] == "table":
        segments = parsed["segments"]
    else:
        segments, titles, lines, start, fence = [], [], [], 1, False
        for n, line in enumerate(parsed["text"].splitlines(), 1):
            heading = (
                re.match(r"^(#{1,6})\s+(.+)", line) if relative_path.endswith(".md") and not fence else None
            )
            if heading:
                if lines:
                    segments.append(
                        {
                            "text": "\n".join(lines),
                            "title_path": titles[:],
                            "location": {"type": "text", "start_line": start, "end_line": n - 1},
                        }
                    )
                depth = len(heading[1])
                titles = titles[: depth - 1] + [heading[2]]
                lines, start = [], n
            if not lines:
                start = n
            lines.append(line)
            if line.lstrip().startswith(("```", "~~~")):
                fence = not fence
        if lines:
            segments.append(
                {
                    "text": "\n".join(lines),
                    "title_path": titles[:],
                    "location": {"type": "text", "start_line": start, "end_line": start + len(lines) - 1},
                }
            )
    for segment in segments:
        if not segment["text"].strip():
            continue
        prefix = relative_path + "\n" + " / ".join(segment["title_path"]) + "\n"
        if model.tokens("passage: " + prefix) > model.limit - 32:
            raise RagError("TITLE_TOO_LONG", "파일명 또는 제목의 토큰 한도를 초과했습니다.")
        budget = min(settings.chunk_tokens, model.limit - model.tokens("passage: " + prefix) - 4)
        # Split by original character offsets; preserve exact line and fragment locations.
        body, offset = segment["text"], 0
        while offset < len(body):
            if time.monotonic() > deadline or len(result) >= settings.max_chunks:
                raise RagError("CHUNK_LIMIT", "문서 청킹의 시간 또는 개수 제한을 초과했습니다.")
            low, high = offset + 1, min(len(body), offset + max(2048, budget * 16))
            end = offset
            while low <= high:
                middle = (low + high) // 2
                if model.tokens(body[offset:middle]) <= budget:
                    end, low = middle, middle + 1
                else:
                    high = middle - 1
            if end == offset:
                raise RagError("CHUNK_TOO_LONG")
            if end < len(body):
                # Prefer paragraph/line/sentence boundaries when enough content fits.
                matches = list(re.finditer(r"\n\n|\n|[.!?。]\s", body[offset:end]))
                valid = [m.end() for m in matches if m.end() > (end - offset) // 2]
                if valid:
                    end = offset + valid[-1]
            text = body[offset:end]
            location = dict(segment["location"])
            location.update(char_start=offset, char_end=end)
            if location["type"] == "text":
                base = segment["location"]["start_line"]
                location["start_line"] = base + body[:offset].count("\n")
                location["end_line"] = base + body[:end].rstrip("\n").count("\n")
            search_text = unicodedata.normalize("NFC", prefix + text)
            if model.tokens("passage: " + search_text) > model.limit:
                raise RagError("CHUNK_TOO_LONG")
            chunk = {
                "chunk_id": uid(),
                "text": text,
                "search_text": search_text,
                "title_path": segment["title_path"],
                "location": location,
            }
            if "table" in segment:
                chunk["table"] = segment["table"]
            result.append(chunk)
            if end >= len(body):
                break
            overlap_start = end
            # Modest overlap within the same section only.
            while (
                overlap_start > offset + 1
                and model.tokens(body[overlap_start - 1 : end]) <= settings.overlap_tokens
            ):
                overlap_start -= 1
            offset = max(offset + 1, overlap_start)
    return result


class VectorAdapter:
    """One executor owns every local Qdrant client; never touches the ASGI loop."""

    def __init__(self, settings):
        self.s = settings
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="rag-qdrant-owner")
        self.clients = {}

    def call(self, operation, workspace_id, *args):
        return self.executor.submit(self._call, operation, workspace_id, *args).result()

    def _call(self, operation, workspace_id, *args):
        from qdrant_client import QdrantClient, models

        if operation == "close":
            for client in self.clients.values():
                client.close()
            self.clients.clear()
            return
        if workspace_id not in self.clients:
            path = self.s.data_dir / "workspaces" / workspace_id / "vectors"
            path.mkdir(parents=True, exist_ok=True)
            self.clients[workspace_id] = QdrantClient(path=str(path))
        client = self.clients[workspace_id]
        if operation == "delete_workspace":
            client.close()
            del self.clients[workspace_id]
            return
        revision_id = args[0]
        if operation == "create":
            client.create_collection(
                revision_id, vectors_config=models.VectorParams(size=args[1], distance=models.Distance.COSINE)
            )
        elif operation == "upsert":
            chunks = args[1]
            client.upsert(
                revision_id, points=[models.PointStruct(id=c["chunk_id"], vector=c["vector"]) for c in chunks]
            )
        elif operation == "count":
            return client.count(revision_id, exact=True).count
        elif operation == "search":
            return [
                (p.id.replace("-", ""), p.score)
                for p in client.query_points(
                    revision_id, query=args[1], limit=self.s.candidates, with_payload=False
                ).points
            ]
        elif operation == "drop":
            if client.collection_exists(revision_id):
                client.delete_collection(revision_id)

    def close(self):
        self.call("close", "")
        self.executor.shutdown()
