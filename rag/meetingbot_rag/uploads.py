"""Authenticated folder transfers: manifest, bounded file streams, atomic publication."""

import asyncio
import hashlib
import json
import os
import re
import shutil
import time
import unicodedata

from pydantic import BaseModel, Field
from starlette.requests import ClientDisconnect

from .db import dumps, uid
from .sources import SUPPORTED, UPLOAD_ROOT, RagError, invalid_windows_name, is_link_or_reparse


class UploadFileInput(BaseModel):
    path: str = Field(min_length=1, max_length=1024)
    size: int = Field(ge=0)


class UploadInput(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    folder_name: str = Field(min_length=1, max_length=255)
    description: str = Field(default="", max_length=1000)
    files: list[UploadFileInput] = Field(min_length=1, max_length=2000)


def public_source(root_id):
    if root_id == UPLOAD_ROOT:
        raise RagError("UPLOAD_SOURCE_PRIVATE", "업로드 메뉴에서 새 자료를 등록하세요.", 403)


class UploadService:
    def __init__(self, core):
        self.c, self.s, self.db = core, core.s, core.db
        # Serial transfers bound memory/disk use; ordinary search and indexing remain independent.
        self.lock = asyncio.Lock()
        self.staging = self.s.data_dir / "upload-staging"
        self.published = self.s.data_dir / "uploaded"
        for path in (self.staging, self.published):
            path.mkdir(mode=0o700, exist_ok=True)
            if is_link_or_reparse(path):
                raise RuntimeError("Upload storage must not be a symbolic link or reparse point")
            path.chmod(0o700)
        for row in self.db.all("SELECT id FROM upload_sessions WHERE state='UPLOADING'"):
            staged, published = self.staging / row["id"], self.published / row["id"]
            if published.exists():
                shutil.rmtree(published)  # Staged originals survive a crash before DB commit.
            if staged.exists():
                for part in staged.glob("*.part"):
                    part.unlink()
        for row in self.db.all("SELECT id FROM upload_sessions WHERE state='COMMITTED'"):
            shutil.rmtree(self.staging / row["id"], ignore_errors=True)
        self.cleanup()

    def limits(self):
        return {
            "extensions": sorted(SUPPORTED),
            "max_files": min(2000, self.s.max_files),
            "max_file_bytes": self.s.max_file_bytes,
            "max_total_bytes": self.s.max_total_bytes,
            "max_depth": self.s.max_depth - 1,
            "session_hours": self.s.upload_session_hours,
            "storage_limit_bytes": self.s.upload_storage_bytes,
        }

    def cleanup(self):
        for row in self.db.all(
            "SELECT id FROM upload_sessions WHERE state='UPLOADING' AND expires_at<?", (time.time(),)
        ):
            self.remove_files(row["id"])
            self.db.execute("DELETE FROM upload_sessions WHERE id=?", (row["id"],))

    async def sweep(self):
        while True:
            await asyncio.sleep(60)
            async with self.lock:
                self.cleanup()

    def remove_files(self, sid):
        if not re.fullmatch(r"[a-f0-9]{32}", sid):
            raise RagError("NOT_FOUND", status=404)
        for base in (self.staging, self.published):
            path = base / sid
            if path.exists():
                shutil.rmtree(path)

    def get(self, sid):
        row = self.db.one("SELECT * FROM upload_sessions WHERE id=?", (sid,))
        if not row:
            raise RagError(
                "UPLOAD_NOT_FOUND", "업로드가 만료되었거나 취소되었습니다. 폴더를 다시 선택하세요.", 404
            )
        if row["state"] == "UPLOADING" and row["expires_at"] <= time.time():
            raise RagError("UPLOAD_EXPIRED", "업로드가 만료되었습니다. 폴더를 다시 선택하세요.", 410)
        row["files"] = json.loads(row["files"])
        return row

    def path(self, value):
        parts = value.split("/")
        if any(invalid_windows_name(p) or p in {".", ".."} or len(p.encode()) > 255 for p in parts):
            raise RagError("PATH_DENIED", "올바른 상대 파일 경로가 아닙니다.", 403)
        # Reserve one level for the server-generated batch directory.
        self.c.sources.parts("batch/" + value)
        return parts

    async def create(self, body, owner=None):
        async with self.lock:
            self.cleanup()
            if not body.name.strip() or len(body.folder_name.split("/")) != 1:
                raise RagError("INVALID_REQUEST", "워크스페이스와 폴더 이름을 확인하세요.")
            self.path(body.folder_name)
            if len(body.files) > self.s.max_files:
                raise RagError("SCAN_LIMIT", "파일 개수 제한을 초과했습니다.", 413)
            files, seen, directories, total = [], set(), set(), 0
            for f in body.files:
                parts = self.path(f.path)
                canonical = unicodedata.normalize("NFC", f.path).casefold()
                parents = ["/".join(canonical.split("/")[:i]) for i in range(1, len(parts))]
                if canonical in seen or canonical in directories or any(p in seen for p in parents):
                    raise RagError("DUPLICATE_PATH", "대소문자·유니코드가 겹치는 파일 이름을 바꿔 주세요.")
                seen.add(canonical)
                directories.update(parents)
                if "." + parts[-1].rsplit(".", 1)[-1].lower() not in SUPPORTED:
                    raise RagError("UNSUPPORTED_FORMAT", "지원하지 않는 파일 형식입니다.")
                if f.size > self.s.max_file_bytes:
                    raise RagError("FILE_SIZE_LIMIT", "파일 크기 제한을 초과했습니다.", 413)
                total += f.size
                files.append({"id": uid(), "path": f.path, "size": f.size, "received": False})
            if len(files) + len(directories) > self.s.max_files:
                raise RagError("SCAN_LIMIT", "파일과 하위 폴더 개수 제한을 초과했습니다.", 413)
            if total > self.s.max_total_bytes:
                raise RagError("TOTAL_SIZE_LIMIT", "폴더 전체 크기 제한을 초과했습니다.", 413)
            active = self.db.one("SELECT count(*) n FROM upload_sessions WHERE state='UPLOADING'")["n"]
            if active >= 3:
                raise RagError("UPLOAD_BUSY", "진행 중인 업로드를 완료하거나 취소한 뒤 다시 시도하세요.", 429)
            used = self.db.one("SELECT COALESCE(sum(total_bytes),0) n FROM upload_sessions")["n"]
            if used + total > self.s.upload_storage_bytes:
                raise RagError(
                    "UPLOAD_STORAGE_FULL", "업로드 저장 한도에 도달했습니다. 기존 자료를 정리하세요.", 413
                )
            if shutil.disk_usage(self.staging).free < total * 2 + 64 * 1024 * 1024:
                raise RagError("UPLOAD_DISK_FULL", "서버 저장 공간이 부족합니다.", 507)
            sid = uid()
            (self.staging / sid).mkdir(mode=0o700)
            try:
                self.db.execute(
                    "INSERT INTO upload_sessions "
                    "(id,name,folder_name,description,files,total_bytes,state,expires_at,workspace_id,owner) "
                    "VALUES(?,?,?,?,?,?,?,?,NULL,?)",
                    (
                        sid,
                        body.name.strip(),
                        body.folder_name,
                        body.description,
                        dumps(files),
                        total,
                        "UPLOADING",
                        time.time() + self.s.upload_session_hours * 3600,
                        owner,
                    ),
                )
            except BaseException:
                self.remove_files(sid)
                raise
            return self.get(sid)

    async def receive(self, sid, fid, request):
        async with self.lock:
            row = self.get(sid)
            if row["state"] != "UPLOADING":
                raise RagError("UPLOAD_FINISHED", "이미 완료한 업로드입니다.", 409)
            file = next((f for f in row["files"] if f["id"] == fid), None)
            if not file:
                raise RagError("NOT_FOUND", status=404)
            if file["received"]:
                return {"received": True, "id": fid}  # Safe retry after a lost response.
            declared = request.headers.get("content-length")
            if declared is not None and (not declared.isdigit() or int(declared) != file["size"]):
                raise RagError(
                    "UPLOAD_SIZE_MISMATCH", "파일 크기가 변경되었습니다. 폴더를 다시 선택하세요.", 400
                )
            base = self.staging / sid
            partial = base / (fid + ".part")
            size, digest = 0, hashlib.sha256()
            try:
                async with asyncio.timeout(120):
                    with partial.open("xb") as output:
                        partial.chmod(0o600)
                        async for block in request.stream():
                            size += len(block)
                            if size > file["size"] or size > self.s.max_file_bytes:
                                raise RagError(
                                    "FILE_SIZE_LIMIT", "전송된 파일이 허용 크기를 초과했습니다.", 413
                                )
                            output.write(block)
                            digest.update(block)
                        if size != file["size"]:
                            raise RagError(
                                "UPLOAD_SIZE_MISMATCH", "파일 전송이 끝나지 않았습니다. 재시도하세요."
                            )
                        output.flush()
                        os.fsync(output.fileno())
                # Client names never become write paths until every file has been received.
                partial.replace(base / fid)
                file.update(received=True, sha256=digest.hexdigest())
                self.db.execute("UPDATE upload_sessions SET files=? WHERE id=?", (dumps(row["files"]), sid))
            except (TimeoutError, ClientDisconnect):
                raise RagError(
                    "UPLOAD_INTERRUPTED", "파일 전송이 중단되었습니다. 재시도하세요.", 408
                ) from None
            except OSError:
                raise RagError("UPLOAD_WRITE_FAILED", "서버에 파일을 저장하지 못했습니다.", 507) from None
            finally:
                partial.unlink(missing_ok=True)
            return {"received": True, "id": fid}

    async def cancel(self, sid):
        async with self.lock:
            row = self.db.one("SELECT state FROM upload_sessions WHERE id=?", (sid,))
            if row and row["state"] == "COMMITTED":
                raise RagError("UPLOAD_FINISHED", "완료한 자료는 워크스페이스에서 삭제하세요.", 409)
            self.remove_files(sid)
            self.db.execute("DELETE FROM upload_sessions WHERE id=?", (sid,))
            return {"cancelled": True}

    async def commit(self, sid):
        async with self.lock:
            row = self.get(sid)
            if row["state"] == "UPLOADING":
                if not all(f["received"] for f in row["files"]):
                    raise RagError("UPLOAD_INCOMPLETE", "모든 파일 전송이 완료된 뒤 다시 시도하세요.", 409)
                base = self.staging / sid
                tree = base / "tree"
                if tree.exists():
                    shutil.rmtree(tree)
                tree.mkdir(mode=0o700)
                try:
                    for f in row["files"]:
                        source = base / f["id"]
                        data = source.read_bytes()  # Each file is capped at max_file_bytes.
                        if len(data) != f["size"] or hashlib.sha256(data).hexdigest() != f["sha256"]:
                            raise RagError(
                                "UPLOAD_INTEGRITY_FAILED",
                                "전송된 파일을 확인할 수 없습니다. 다시 업로드하세요.",
                                409,
                            )
                        target = tree.joinpath(*self.path(f["path"]))
                        target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
                        with target.open("xb") as output:
                            output.write(data)
                        target.chmod(0o600)
                    destination = self.published / sid
                    tree.rename(destination)
                    try:
                        wid = uid()
                        with self.db.transaction():
                            self.db.execute(
                                "INSERT INTO workspaces(id,name,description,created_at) VALUES(?,?,?,?)",
                                (wid, row["name"], row["description"], time.time()),
                            )
                            self.db.execute(
                                "INSERT INTO knowledge_bases(id,workspace_id) VALUES(?,?)", (uid(), wid)
                            )
                            self.db.execute(
                                "INSERT INTO sources VALUES(?,?,?,?,?)",
                                (
                                    uid(),
                                    wid,
                                    UPLOAD_ROOT,
                                    sid,
                                    self.c.sources.identity(UPLOAD_ROOT),
                                ),
                            )
                            self.db.execute(
                                "UPDATE upload_sessions SET state='COMMITTED',workspace_id=? WHERE id=?",
                                (wid, sid),
                            )
                    except BaseException:
                        shutil.rmtree(destination)
                        raise
                    shutil.rmtree(base)
                    row["workspace_id"] = wid
                except OSError:
                    raise RagError(
                        "UPLOAD_WRITE_FAILED", "서버에 자료를 저장하지 못했습니다. 재시도하세요.", 507
                    ) from None
            wid = row["workspace_id"]
            try:
                job = self.c.ingestion.create(wid, idempotency_key="upload:" + sid)
                index_error = None
            except RagError as error:
                job, index_error = None, error.message
            return {"workspace": self.c.workspaces.get(wid), "job": job, "index_error": index_error}
