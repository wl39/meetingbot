"""Narrow local Codex OAuth bridge; management credentials never reach the browser."""

import hashlib
import hmac
import json
import secrets
import threading
from urllib.parse import parse_qs, urlsplit

import httpx
from pydantic import BaseModel, Field

from .llm_settings import LLMSettingsUpdate
from .sources import RagError


class CodexCallback(BaseModel):
    redirect_url: str = Field(min_length=1, max_length=8000)


class CodexAccountAction(BaseModel):
    account_id: str = Field(pattern=r"^[a-f0-9]{64}$")
    expected_revision: str = Field(pattern=r"^[a-f0-9]{64}$")


def masked_email(value):
    if not isinstance(value, str) or value.count("@") != 1:
        return None
    local, domain = value.strip().split("@")
    if not local or not domain:
        return None
    # Avoid overlapping the visible prefix and suffix for unusually short domains.
    suffix = domain[max(2, len(domain) - 2):]
    return f"{local[:4]}***@{domain[:2]}***{suffix}"


class ManagedProxy:
    def __init__(self, answer):
        self.answer = answer
        self.path = answer.c.s.managed_proxy_dir
        self.lock = threading.Lock()

    def credentials(self):
        if not self.path or not (self.path / "credentials.json").is_file():
            raise RagError(
                "MANAGED_PROXY_NOT_INSTALLED", "이 서버에 관리형 CLIProxyAPI가 설치되지 않았습니다.", 503
            )
        return json.loads((self.path / "credentials.json").read_text(encoding="utf-8"))

    def request(self, method, path, **kwargs):
        keys = self.credentials()
        try:
            with httpx.Client(timeout=15, trust_env=False, follow_redirects=False) as client:
                response = client.request(
                    method,
                    "http://127.0.0.1:8317/v0/management/" + path,
                    headers={"Authorization": "Bearer " + keys["management_key"]},
                    **kwargs,
                )
                response.raise_for_status()
                return response.json()
        except Exception:
            raise RagError(
                "CODEX_CONNECTION_FAILED",
                "CLIProxyAPI 연결을 확인하세요. 로그인 세션이 만료됐다면 다시 시작하세요.",
                502,
            ) from None

    def pending(self):
        if self.path and (self.path / "pending-login.json").is_file():
            return json.loads((self.path / "pending-login.json").read_text(encoding="utf-8"))
        return None

    def account_files(self):
        return [item for item in self.request("GET", "auth-files").get("files", [])
                if item.get("type") == "codex"]

    def fingerprint(self, value):
        return hmac.new(self.credentials()["management_key"].encode(),
                        value.encode(), hashlib.sha256).hexdigest()

    def account_id(self, item):
        name = item.get("name") or item.get("id")
        return self.fingerprint("account:" + name) if isinstance(name, str) else None

    def revision(self, files):
        return self.fingerprint("revision:" + json.dumps(sorted(
            (self.account_id(item) or "", self.is_disabled(item)) for item in files
        )))

    @staticmethod
    def is_disabled(item):
        return bool(item.get("disabled") or item.get("status") == "disabled")

    @staticmethod
    def manageable(item):
        name = item.get("name")
        return (isinstance(name, str) and name.endswith(".json")
                and "/" not in name and "\\" not in name
                and item.get("source") == "file" and not item.get("runtime_only"))

    def status(self):
        if not self.path:
            return {"installed": False, "connected": False, "accounts": []}
        try:
            files = self.account_files()
            # Only expose display metadata, never raw auth records or error messages.
            accounts = []
            for item in files:
                status = item.get("status")
                if self.is_disabled(item):
                    status = "disabled"
                elif status == "error":
                    status = "error"
                elif item.get("unavailable"):
                    status = "unavailable"
                elif status != "active":
                    status = "unknown"
                accounts.append({
                    "id": self.account_id(item),
                    "email": masked_email(item.get("email")),
                    "status": status,
                    "enabled": not self.is_disabled(item),
                    "manageable": self.manageable(item),
                })
            count = sum(account["status"] == "active" for account in accounts)
            enabled = [account for account in accounts if account["enabled"]]
            pending = self.pending()
            state = None
            if pending:
                try:
                    state = self.request("GET", "get-auth-status", params={"state": pending["state"]}).get(
                        "status"
                    )
                except RagError:
                    state = "error"
            return {
                "installed": True,
                "connected": count > 0,
                "account_count": count,
                "accounts": accounts,
                "revision": self.revision(files),
                "enabled_count": len(enabled),
                "selected_account_id": enabled[0]["id"] if len(enabled) == 1 else None,
                "login_status": state,
                "endpoint": "http://127.0.0.1:8317/v1",
            }
        except RagError as error:
            return {"installed": True, "connected": False, "accounts": [], "error_code": error.code}

    def account_target(self, body):
        pending = self.pending()
        if pending and self.request("GET", "get-auth-status", params={"state": pending["state"]}).get("status") == "wait":
            raise RagError("CODEX_LOGIN_PENDING", "진행 중인 로그인을 완료한 뒤 계정을 변경하세요.", 409)
        files = self.account_files()
        if not secrets.compare_digest(self.revision(files), body.expected_revision):
            raise RagError("CODEX_ACCOUNTS_CHANGED", "계정 목록이 변경됐습니다. 상태 확인 후 다시 시도하세요.", 409)
        target = next((item for item in files if self.account_id(item) == body.account_id), None)
        if not target:
            raise RagError("CODEX_ACCOUNT_NOT_FOUND", "이 계정은 더 이상 등록되어 있지 않습니다.", 404)
        if not self.manageable(target):
            raise RagError("CODEX_ACCOUNT_UNMANAGED", "이 계정은 이 화면에서 변경할 수 없습니다.", 409)
        return files, target

    def set_disabled(self, item, disabled):
        self.request("PATCH", "auth-files/status", json={"name": item["name"], "disabled": disabled})

    def select_account(self, body):
        with self.lock:
            files, target = self.account_target(body)
            others = [item for item in files if item is not target and not self.is_disabled(item)]
            if any(not self.manageable(item) for item in others):
                raise RagError("CODEX_ACCOUNT_UNMANAGED", "다른 활성 계정을 이 화면에서 변경할 수 없습니다.", 409)
            changed = []
            try:
                # Disable others first so new requests do not use the previous account.
                for item in others + ([target] if self.is_disabled(target) else []):
                    changed.append(item)  # Include a request whose response may be lost.
                    self.set_disabled(item, item is not target)
                enabled = [self.account_id(item) for item in self.account_files() if not self.is_disabled(item)]
                if enabled != [body.account_id]:
                    raise RagError("CODEX_ACCOUNT_SELECT_FAILED", "계정 선택 결과를 확인하지 못했습니다.", 502)
            except RagError:
                restored = True
                for item in reversed(changed):
                    try:
                        self.set_disabled(item, self.is_disabled(item))
                    except RagError:
                        restored = False
                message = ("계정 변경에 실패했습니다. 상태 확인 후 다시 시도하세요." if restored else
                           "계정 변경 중 일부 상태가 변경됐을 수 있습니다. 상태 확인 후 사용할 계정을 다시 선택하세요.")
                raise RagError("CODEX_ACCOUNT_SELECT_FAILED", message, 502) from None
        return self.status()

    def delete_account(self, body):
        with self.lock:
            _, target = self.account_target(body)
            self.request("DELETE", "auth-files", params={"name": target["name"]})
            if any(self.account_id(item) == body.account_id for item in self.account_files()):
                raise RagError("CODEX_ACCOUNT_DELETE_FAILED", "계정 삭제 결과를 확인하지 못했습니다. 상태 확인을 눌러 주세요.", 502)
        return self.status()

    def start(self):
        with self.lock:
            pending = self.pending()
            if pending:
                try:
                    status = self.request("GET", "get-auth-status", params={"state": pending["state"]})
                    if status.get("status") == "wait":
                        return {"url": pending["url"], "status": "wait"}
                except RagError:
                    pass
            data = self.request("GET", "codex-auth-url", params={"is_webui": "true"})
            parsed = urlsplit(data.get("url", ""))
            if parsed.scheme != "https" or parsed.hostname != "auth.openai.com" or not data.get("state"):
                raise RagError("INVALID_AUTH_URL", "올바른 Codex 인증 주소를 받지 못했습니다.", 502)
            target = self.path / "pending-login.json"
            target.write_text(json.dumps(data), encoding="utf-8")
            target.chmod(0o600)
            return {"url": data["url"], "status": "wait"}

    def callback(self, body):
        with self.lock:
            pending = self.pending()
            parsed = urlsplit(body.redirect_url.strip())
            query = parse_qs(parsed.query)
            state = query.get("state", [""])[0]
            code = query.get("code", [""])[0]
            if (
                not pending
                or not secrets.compare_digest(state, pending["state"])
                or parsed.scheme != "http"
                or parsed.netloc != "localhost:1455"
                or parsed.path != "/auth/callback"
                or not code
                or parsed.fragment
            ):
                raise RagError(
                    "INVALID_AUTH_CALLBACK",
                    "현재 로그인에서 받은 localhost:1455/auth/callback 주소를 입력하세요.",
                )
            self.request("POST", "oauth-callback", json={"provider": "codex", "state": state, "code": code})
            return {"status": "submitted"}

    def use(self, expected_version):
        keys = self.credentials()
        config, _ = self.answer.settings.snapshot()
        return self.answer.settings.save(
            LLMSettingsUpdate(
                expected_version=expected_version,
                base_url="http://127.0.0.1:8317/v1",
                api_key=keys["api_key"],
                default_model=config.default_model if config.base_url == "http://127.0.0.1:8317/v1" else "",
            )
        )
