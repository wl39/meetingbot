"""Optional contract check against an isolated CLIProxyAPI with synthetic accounts."""

import json
import os
import socket
import subprocess
import time
from pathlib import Path

import httpx
import pytest


@pytest.mark.skipif(not os.environ.get("CLIPROXY_TEST_BINARY"), reason="Requires an installed CLIProxyAPI binary")
def test_isolated_proxy_account_switch_persistence_and_delete(client, tmp_path, monkeypatch):
    binary = Path(os.environ["CLIPROXY_TEST_BINARY"])
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    auth = tmp_path / "auth"
    auth.mkdir()
    for name in ("first", "second"):
        (auth / f"{name}.json").write_text(json.dumps({
            "type": "codex", "email": f"{name}@example.test", "access_token": "synthetic-not-a-token",
            "refresh_token": "", "expired": "2099-01-01T00:00:00Z", "last_refresh": "2099-01-01T00:00:00Z",
        }))
    key = "isolated-test-management-key"
    (tmp_path / "credentials.json").write_text(json.dumps({"management_key": key}))
    config = tmp_path / "config.json"
    config.write_text(json.dumps({
        "host": "127.0.0.1", "port": port, "auth-dir": str(auth), "api-keys": ["synthetic-key"],
        "remote-management": {"secret-key": key, "allow-remote": False, "disable-control-panel": True,
                              "disable-auto-update-panel": True},
        "commercial-mode": True, "plugins": {"enabled": False},
    }))
    c, _, _ = client
    bridge = c.app.state.proxy
    bridge.path = tmp_path

    def request(method, path, **kwargs):
        with httpx.Client(trust_env=False, timeout=5) as transport:
            response = transport.request(method, f"http://127.0.0.1:{port}/v0/management/{path}",
                                         headers={"Authorization": f"Bearer {key}"}, **kwargs)
            response.raise_for_status()
            return response.json()

    monkeypatch.setattr(bridge, "request", request)

    def start():
        process = subprocess.Popen([str(binary), "-config", str(config), "-local-model"],
                                   cwd=tmp_path, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            for _ in range(100):
                assert process.poll() is None, "Isolated proxy exited"
                try:
                    if len(request("GET", "auth-files").get("files", [])) == 2:
                        return process
                except httpx.HTTPError:
                    pass
                time.sleep(0.1)
            pytest.fail("Isolated proxy did not become ready")
        except BaseException:
            process.terminate()
            process.wait(timeout=10)
            raise

    process = start()
    try:
        initial = bridge.status()
        assert len(initial["accounts"]) == 2 and initial["enabled_count"] == 2
        selected_id = initial["accounts"][1]["id"]
        result = c.post("/api/rag/llm/codex/accounts/select", json={
            "account_id": selected_id, "expected_revision": initial["revision"]})
        assert result.status_code == 200, result.text
        assert result.json()["selected_account_id"] == selected_id
        process.terminate()
        process.wait(timeout=10)
        process = start()
        persisted = bridge.status()
        assert persisted["selected_account_id"] == selected_id and persisted["enabled_count"] == 1
        result = c.post("/api/rag/llm/codex/accounts/delete", json={
            "account_id": selected_id, "expected_revision": persisted["revision"]})
        assert result.status_code == 200, result.text
        assert len(result.json()["accounts"]) == 1 and result.json()["enabled_count"] == 0
        assert len(list(auth.glob("*.json"))) == 1
        assert "@example.test" not in result.text
    finally:
        if process.poll() is None:
            process.terminate()
            process.wait(timeout=10)
