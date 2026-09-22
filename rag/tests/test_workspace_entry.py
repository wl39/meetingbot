import pytest
from conftest import FakeModel
from fastapi.testclient import TestClient
from pydantic import ValidationError

from meetingbot_rag.app import create_app
from meetingbot_rag.settings import Settings


@pytest.mark.parametrize("path", ["/rag", "/rag/settings"])
def test_legacy_entry_opens_unified_workspace(env, path):
    settings, _ = env
    settings.workspace_url = "https://workspace.example"
    with TestClient(create_app(settings, FakeModel())) as client:
        response = client.get(path, follow_redirects=False)
        assert response.status_code == 307
        assert response.headers["location"] == "https://workspace.example" + path
        assert client.get("/api/rag/workspaces").status_code == 401


@pytest.mark.parametrize("url", ["javascript:alert(1)", "https://user:secret@example.com", "https://example.com/path", "http://example.com", "https://example.com#token=abc"])
def test_workspace_destination_must_be_a_safe_configured_origin(url):
    with pytest.raises(ValidationError):
        Settings(_env_file=None, workspace_url=url)
