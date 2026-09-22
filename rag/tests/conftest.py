import hashlib
import json
import re
import time

import numpy as np
import pytest
from fastapi.testclient import TestClient

from meetingbot_rag.app import create_app
from meetingbot_rag.settings import Settings

KEY = "test-credential-never-used-in-production-123456789"


def wait_question(client, response, headers=None):
    assert response.status_code == 202, response.text
    rid = response.json()["request_id"]
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        found = client.get(f"/api/rag/history/{rid}", headers=headers)
        assert found.status_code == 200, found.text
        result = found.json()["result"]
        if result["status"] not in {"queued", "processing"}:
            return result
        time.sleep(0.025)
    raise AssertionError(f"Question {rid} did not finish")


def ask(client, path, **kwargs):
    return wait_question(client, client.post(path, **kwargs), kwargs.get("headers"))


class FakeModel:
    state = "READY"
    dimension = 384
    limit = 512
    encoded_passages = 0
    device = "fake"

    def load(self):
        pass

    def tokens(self, text):
        return len(text) // 2 + 2

    def encode(self, texts, query=False):
        from meetingbot_rag.sources import RagError

        if any(self.tokens(x) > self.limit for x in texts):
            raise RagError("QUERY_TOO_LONG" if query else "CHUNK_TOO_LONG")
        out = []
        for text in texts:
            vec = np.zeros(self.dimension)
            for word in re.findall(r"\w+", text):
                for i in range(max(1, len(word) - 1)):
                    token = word[i : i + 2]
                    vec[int(hashlib.md5(token.encode()).hexdigest(), 16) % self.dimension] += 1
            norm = np.linalg.norm(vec)
            out.append((vec / max(norm, 1)).tolist())
        if not query:
            self.encoded_passages += len(texts)
        return out

    def health(self):
        return {
            "state": "READY",
            "model": "TEST_ONLY",
            "device": "fake",
            "revision": "fake",
            "dimension": 384,
        }


@pytest.fixture
def env(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    roots = tmp_path / "roots.yaml"
    roots.write_text(json.dumps({"roots": [{"id": "docs", "label": "자료", "path": str(source)}]}))
    token = tmp_path / "token"
    token.write_text(KEY)
    token.chmod(0o600)
    s = Settings(_env_file=None, data_dir=tmp_path / "data", source_roots_file=roots, auth_token_file=token)
    return s, source


@pytest.fixture
def client(env):
    s, source = env
    app = create_app(s, FakeModel())
    with TestClient(app, headers={"Authorization": "Bearer " + KEY}) as client:
        yield client, source, app.state.core
