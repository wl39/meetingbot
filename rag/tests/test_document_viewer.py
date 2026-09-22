import unicodedata

from test_rag import create, index


def test_document_viewer_scope_normalization_and_historical_snapshot(client):
    c, root, core = client
    folder = root / "viewer"
    folder.mkdir()
    name = unicodedata.normalize("NFD", "정책.md")
    (folder / name).write_text("# 정책\n\n기록 보관 기간은 73일입니다.")
    wid = create(c, "viewer")
    first = index(c, wid)
    assert first["state"] == "READY"
    response = c.get(f"/api/rag/workspaces/{wid}/documents", params={"relative_path": "정책.md"})
    assert response.status_code == 200
    assert "73일" in response.json()["snapshot"]["text"]
    assert response.json()["evidence"]["relative_path"] == name
    for path in ["../정책.md", "/etc/passwd", "not-indexed.md"]:
        assert c.get(f"/api/rag/workspaces/{wid}/documents", params={"relative_path": path}).status_code == 404
    (folder / name).write_text("# 정책\n\n기록 보관 기간은 90일입니다.")
    assert index(c, wid)["state"] == "READY"
    old = c.get(f"/api/rag/workspaces/{wid}/documents", params={"relative_path": "정책.md", "revision_id": first["revision_id"]})
    assert "73일" in old.json()["snapshot"]["text"]
    other = create(c, "viewer", "별도 공간")
    assert index(c, other)["state"] == "READY"
    assert c.get(f"/api/rag/workspaces/{other}/documents", params={"relative_path": "정책.md", "revision_id": first["revision_id"]}).status_code == 409
    (folder / name).unlink()
    folder.rmdir()
    assert c.get(f"/api/rag/workspaces/{wid}/documents", params={"relative_path": "정책.md"}).status_code != 200
