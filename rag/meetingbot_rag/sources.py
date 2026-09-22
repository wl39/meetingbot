import hashlib
import os
import stat
import time
from contextlib import contextmanager
from pathlib import Path, PurePosixPath

import yaml


class RagError(Exception):
    def __init__(self, code, message="요청을 처리할 수 없습니다.", status=400):
        self.code, self.message, self.status = code, message, status
        super().__init__(code)


SUPPORTED = {".md", ".txt", ".csv", ".tsv", ".xlsx"}
UPLOAD_ROOT = "__uploads__"
WINDOWS_DEVICES = {"CON", "PRN", "AUX", "NUL", "CONIN$", "CONOUT$"} | {
    f"{prefix}{number}" for prefix in ("COM", "LPT") for number in "123456789¹²³"
}


def invalid_windows_name(name):
    """Reject Win32 aliases/devices before a client name becomes a filesystem path."""
    return (
        not name
        or name[-1] in " ."
        or any(char in '<>:"/\\|?*' or ord(char) < 32 for char in name)
        or name.split(".", 1)[0].rstrip(" ").upper() in WINDOWS_DEVICES
    )


def is_link_or_reparse(entry):
    # Junctions and other Windows reparse points are not necessarily symbolic links.
    return entry.is_symlink() or bool(
        getattr(entry.stat(follow_symlinks=False), "st_file_attributes", 0) & 0x0400
    )


EXCLUDED = {
    "node_modules",
    "venv",
    "__pycache__",
    "dist",
    "build",
    "target",
    "models",
    "credentials",
    "secrets",
    "id_rsa",
    "id_ed25519",
    "package-lock.json",
    "uv.lock",
    "admin-token",
    "local-token",
}


class SourceBrowserService:
    def __init__(self, settings):
        self.s = settings

    def roots(self):
        try:
            data = self.s.source_roots_file.read_bytes()
            config = yaml.safe_load(data) or {}
            roots = config.get("roots", [])
            if len({r["id"] for r in roots}) != len(roots):
                raise ValueError()
            for root in roots:
                if not Path(root["path"]).is_absolute():
                    raise ValueError()
            return roots, hashlib.sha256(data).hexdigest()
        except FileNotFoundError:
            return [], "empty"
        except Exception:
            raise RagError("ROOT_CONFIG_INVALID", "서버의 허용 폴더 설정을 확인하세요.", 503) from None

    def root(self, root_id):
        if root_id == UPLOAD_ROOT:
            return {"id": UPLOAD_ROOT, "label": "업로드한 자료", "path": str(self.s.data_dir / "uploaded")}
        roots, _ = self.roots()
        for root in roots:
            if root["id"] == root_id:
                return root
        raise RagError("SOURCE_ACCESS_REVOKED", "허용된 서버 폴더가 아닙니다.", 403)

    def identity(self, root_id):
        if root_id == UPLOAD_ROOT:
            return hashlib.sha256(b"managed-upload-v1").hexdigest()
        root = self.root(root_id)
        return hashlib.sha256(os.path.abspath(root["path"]).encode()).hexdigest()

    def validate_source(self, source):
        if source["policy"] != self.identity(source["root_id"]):
            raise RagError(
                "SOURCE_ACCESS_REVOKED", "허용 루트가 변경되었습니다. 새 워크스페이스로 연결하세요.", 403
            )
        self.validate(source["root_id"], source["relative_path"])

    def parts(self, rel):
        if not isinstance(rel, str) or len(rel) > 2048 or any(c in rel for c in ("%", "\\", "\0", ":")):
            raise RagError("PATH_DENIED", "허용되지 않는 상대 경로입니다.", 403)
        path = PurePosixPath(rel)
        if path.is_absolute() or ".." in path.parts or any(ord(c) < 32 for c in rel):
            raise RagError("PATH_DENIED", "허용되지 않는 상대 경로입니다.", 403)
        if len(path.parts) > self.s.max_depth:
            raise RagError("DEPTH_LIMIT", "폴더 깊이 제한을 초과했습니다.")
        for part in path.parts:
            if self.exclusion(part):
                raise RagError("PATH_DENIED", "정책상 제외된 경로입니다.", 403)
        return path.parts

    def exclusion(self, name):
        low = name.lower()
        if (
            (os.name == "nt" and invalid_windows_name(name))
            or low.startswith((".", "~", "~$"))
            or low in EXCLUDED
            or low.endswith((".pem", ".key", ".p12", ".pfx", ".tmp", ".swp", ".bak"))
            or low.startswith(("credentials.", "secrets.", "token.", "auth."))
        ):
            return "POLICY_EXCLUDED"
        return None

    def protected(self, path, managed=False):
        # Lexical absolute paths; descriptors below enforce no symlink traversal.
        path = Path(os.path.abspath(path))
        if managed and path.is_relative_to(self.s.data_dir / "uploaded"):
            return
        protected = [
            self.s.data_dir,
            self.s.auth_token_file,
            self.s.source_roots_file,
            Path.home() / ".cache",
            Path.home() / ".ssh",
            Path.home() / ".codex",
        ]
        if any(path == p or path.is_relative_to(p) for p in protected if p):
            raise RagError("PATH_DENIED", "앱 데이터 또는 인증 경로는 자료로 사용할 수 없습니다.", 403)

    @contextmanager
    def opened(self, root_id, rel="", file=False):
        root = self.root(root_id)
        root_path = Path(root["path"])
        parts = list(root_path.parts[1:]) + list(self.parts(rel))
        self.protected(root_path / rel, managed=root_id == UPLOAD_ROOT)
        if os.name == "nt":
            from .windows_sources import opened_windows

            try:
                with opened_windows(root_path, self.parts(rel), file=file) as handle:
                    yield handle
            except OSError:
                raise RagError(
                    "SOURCE_UNAVAILABLE",
                    "폴더 또는 파일에 접근할 수 없습니다. 권한과 연결을 확인하세요.",
                    409,
                ) from None
            return
        fd = os.open("/", os.O_RDONLY | os.O_DIRECTORY)
        try:
            for index, part in enumerate(parts):
                final_file = file and index == len(parts) - 1
                flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK
                if not final_file:
                    flags |= os.O_DIRECTORY
                next_fd = os.open(part, flags, dir_fd=fd)
                os.close(fd)
                fd = next_fd
            mode = os.fstat(fd).st_mode
            if (file and not stat.S_ISREG(mode)) or (not file and not stat.S_ISDIR(mode)):
                raise RagError("SPECIAL_FILE", "일반 파일 또는 폴더만 사용할 수 있습니다.")
            yield fd
        except OSError:
            raise RagError(
                "SOURCE_UNAVAILABLE", "폴더 또는 파일에 접근할 수 없습니다. 권한과 연결을 확인하세요.", 409
            ) from None
        finally:
            os.close(fd)

    def validate(self, root_id, rel):
        with self.opened(root_id, rel):
            pass

    def entries(self, root_id, rel="", cursor=0, name_filter="", limit=100):
        start = time.monotonic()
        result = []
        visited = 0
        with self.opened(root_id, rel) as fd, os.scandir(fd) as entries:
            for entry in entries:
                visited += 1
                if time.monotonic() - start > 3 or visited > 20000:
                    raise RagError("BROWSE_LIMIT", "폴더가 너무 큽니다. 더 작은 폴더를 사용하세요.")
                if visited <= cursor:
                    continue
                if name_filter.casefold() not in entry.name.casefold():
                    continue
                reason = self.exclusion(entry.name)
                kind = "directory" if entry.is_dir(follow_symlinks=False) else "file"
                if is_link_or_reparse(entry):
                    reason = "SYMLINK_EXCLUDED"
                elif not entry.is_dir(follow_symlinks=False) and not entry.is_file(follow_symlinks=False):
                    reason = "SPECIAL_FILE"
                elif kind == "file" and Path(entry.name).suffix.lower() not in SUPPORTED:
                    reason = reason or "UNSUPPORTED_FORMAT"
                try:
                    self.protected(Path(self.root(root_id)["path"]) / rel / entry.name)
                except RagError:
                    reason = "POLICY_EXCLUDED"
                result.append({"name": entry.name, "kind": kind, "reason": reason})
                if len(result) >= limit:
                    return {"entries": result, "next_cursor": visited, "relative_path": rel}
        return {"entries": result, "next_cursor": None, "relative_path": rel}

    def read(self, root_id, rel):
        for attempt in range(2):
            with self.opened(root_id, rel, file=True) as fd:
                before = os.fstat(fd)
                if before.st_nlink != 1:
                    raise RagError("HARDLINK_EXCLUDED", "하드 링크 파일은 제외합니다.")
                if before.st_size > self.s.max_file_bytes:
                    raise RagError("FILE_SIZE_LIMIT", "파일 크기 제한을 초과했습니다.")
                chunks, size = [], 0
                while True:
                    block = os.read(fd, min(1024 * 1024, self.s.max_file_bytes + 1 - size))
                    if not block:
                        break
                    chunks.append(block)
                    size += len(block)
                    if size > self.s.max_file_bytes:
                        raise RagError("FILE_SIZE_LIMIT", "파일 크기 제한을 초과했습니다.")
                after = os.fstat(fd)
                if (before.st_size, before.st_mtime_ns, before.st_ctime_ns) == (
                    after.st_size,
                    after.st_mtime_ns,
                    after.st_ctime_ns,
                ):
                    return b"".join(chunks)
        raise RagError("UNSTABLE_INPUT", "읽는 동안 파일이 변경되었습니다. 잠시 후 재시도하세요.")

    def scan(self, root_id, relative_path, check=lambda: None, progress=lambda x: None):
        rel = relative_path
        self.validate(root_id, rel)
        started = time.monotonic()
        found, total, visited = [], 0, 0

        def visit(folder, prefix, depth):
            nonlocal total, visited
            check()
            if depth > self.s.max_depth:
                raise RagError("DEPTH_LIMIT", "하위 폴더 깊이 제한을 초과했습니다.")
            with self.opened(root_id, folder) as fd, os.scandir(fd) as entries:
                for entry in entries:
                    check()
                    visited += 1
                    if time.monotonic() - started > self.s.scan_seconds or visited > self.s.max_files:
                        raise RagError("SCAN_LIMIT", "스캔 한도를 초과했습니다. 폴더를 나누어 주세요.")
                    path = str(PurePosixPath(prefix) / entry.name)
                    source_path = str(PurePosixPath(folder) / entry.name)
                    reason = self.exclusion(entry.name)
                    try:
                        self.protected(
                            Path(self.root(root_id)["path"]) / source_path, managed=root_id == UPLOAD_ROOT
                        )
                    except RagError:
                        reason = "POLICY_EXCLUDED"
                    if is_link_or_reparse(entry):
                        reason = "SYMLINK_EXCLUDED"
                    if reason:
                        found.append({"relative_path": path, "state": "EXCLUDED", "reason": reason})
                    elif entry.is_dir(follow_symlinks=False):
                        visit(source_path, path, depth + 1)
                    elif not entry.is_file(follow_symlinks=False):
                        found.append({"relative_path": path, "state": "EXCLUDED", "reason": "SPECIAL_FILE"})
                    elif Path(path).suffix.lower() not in SUPPORTED:
                        found.append(
                            {"relative_path": path, "state": "EXCLUDED", "reason": "UNSUPPORTED_FORMAT"}
                        )
                    else:
                        size = entry.stat(follow_symlinks=False).st_size
                        total += size
                        if total > self.s.max_total_bytes:
                            raise RagError("TOTAL_SIZE_LIMIT", "전체 처리량 제한을 초과했습니다.")
                        found.append(
                            {
                                "relative_path": path,
                                "bytes": size,
                                "state": "FAILED" if size > self.s.max_file_bytes else "INCLUDED",
                                "reason": "FILE_SIZE_LIMIT" if size > self.s.max_file_bytes else None,
                            }
                        )
                    if len(found) % 25 == 0:
                        progress({"stage": "SCANNING", "scanned": len(found)})

        visit(rel, "", 0)
        return {
            "files": found,
            "total_bytes": total,
            "scanned": len(found),
            "scan_ms": round((time.monotonic() - started) * 1000),
        }
