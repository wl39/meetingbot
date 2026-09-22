"""Server-owned subscriptions require a credential separate from user login keys."""

import io
import os
import stat
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

from meetingbot_access import AccessStore

from app.modules.meeting.router import RagBridge
from app.modules.stt.settings import Settings


def test_service_secret_is_shared_persistent_private_and_independent_of_user_keys(tmp_path):
    token = tmp_path / "local-token"
    token.write_text("installation-key-not-a-service-secret")
    database = tmp_path / "shared-access.sqlite3"
    store = AccessStore(token, database)
    with ThreadPoolExecutor(max_workers=8) as pool:
        values = list(
            pool.map(lambda _: AccessStore(token, database).service_secret("meeting-subscription"), range(16))
        )
    secret = values[0]
    assert len(set(values)) == 1 and len(secret) >= 40
    assert secret != token.read_text()
    if os.name != "nt":  # Windows permissions are inherited ACLs, not POSIX mode bits.
        assert stat.S_IMODE(database.stat().st_mode) == 0o600
    user = store.issue_key("Synthetic user", "superadmin")
    assert secret != user["key"]
    assert store.key(secret) is None
    assert secret not in str(store.keys())
    # A separately configured RAG token and a process restart share the same DB,
    # and rotating a user installation key does not rotate the worker credential.
    rag_token = tmp_path / "rag-admin-token"
    rag_token.write_text("another-installation-key")
    assert AccessStore(rag_token, database).service_secret("meeting-subscription") == secret
    token.write_text("rotated-installation-key")
    assert AccessStore(token, database).service_secret("meeting-subscription") == secret


def test_only_subscription_requests_carry_persistent_bridge_authentication(tmp_path):
    token = tmp_path / "rag-admin-token"
    token.write_text("synthetic-rag-user-credential")
    settings = Settings(
        _env_file=None,
        data_dir=tmp_path / "stt",
        rag_token_file=token,
        access_db=tmp_path / "shared-access.sqlite3",
    )
    requests = []

    class Response(io.BytesIO):
        status = 200

    def capture(request, timeout):
        requests.append(request)
        return Response(b'{"accepted":true}')

    service = RagBridge(settings)
    service.opener = SimpleNamespace(open=capture)
    service.request("/workspaces", caller_headers={"Authorization": "Bearer synthetic-visitor"})
    assert requests[-1].get_header("X-meeting-bridge-secret") is None
    assert requests[-1].get_header("X-meeting-subscription") is None
    service.request("/workspaces/test/meeting/jobs", {}, subscription=True)
    first = requests[-1].get_header("X-meeting-bridge-secret")
    assert first and first != token.read_text()
    assert requests[-1].get_header("X-meeting-subscription") == "1"
    assert first == AccessStore(token, settings.access_db).service_secret("meeting-subscription")
    restarted = RagBridge(settings)
    restarted.opener = SimpleNamespace(open=capture)
    restarted.request("/workspaces/test/meeting/jobs", {}, subscription=True)
    assert requests[-1].get_header("X-meeting-bridge-secret") == first
