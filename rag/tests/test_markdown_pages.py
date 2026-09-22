import hashlib
import json
import sqlite3
from html.parser import HTMLParser

from test_rag import create, index, search

from meetingbot_rag.markdown_views import (
    PAGE_BYTES,
    RESPONSE_HTML_BYTES,
    SOURCE_BYTES,
    build_index,
    read_page,
)


def prepare(tmp_path, source, chunks=None, name="source.md"):
    database, output = tmp_path / "registry.sqlite", tmp_path / "view.sqlite"
    chunks = chunks or [{"chunk_id": "hit", "text": "검색", "location": {"start_line": 1, "end_line": 1}}]
    with sqlite3.connect(database) as db:
        db.executescript(
            "CREATE TABLE documents(id TEXT,relative_path TEXT); CREATE TABLE document_versions(id TEXT,document_id TEXT,parsed TEXT,content_hash TEXT,chunks TEXT);"
        )
        db.execute("INSERT INTO documents VALUES(?,?)", ("doc", name))
        db.execute(
            "INSERT INTO document_versions VALUES(?,?,?,?,?)",
            (
                "version",
                "doc",
                json.dumps({"kind": "text", "text": source}),
                hashlib.sha256(source.encode()).hexdigest(),
                json.dumps(chunks),
            ),
        )
    build_index(database, "version", output)
    return output


def evidence(start=1, end=None, text="", chunk="hit"):
    return {
        "evidence_id": f"revision.{chunk}",
        "location": {"start_line": start, "end_line": end or start},
        "text": text,
    }


class Balanced(HTMLParser):
    def __init__(self, text):
        super().__init__()
        self.stack = []
        self.feed(text)
        assert self.stack == []

    def handle_starttag(self, tag, attrs):
        if tag not in {"br", "hr", "input"}:
            self.stack.append(tag)

    def handle_endtag(self, tag):
        assert self.stack.pop() == tag


def test_doubling_uses_known_full_document_boundaries(tmp_path):
    source = "# 제목\n\n```js\n" + "\n".join(f"const a{i}=1;" for i in range(20)) + "\n```"
    chunks = [{"chunk_id": str(i), "location": {"start_line": i + 1, "end_line": i + 1}} for i in range(24)]
    path = prepare(tmp_path, source, chunks)
    result = read_page(path, evidence(12, chunk="11"))
    assert result["expansion_steps"] == [1, 2, 4, 8, 16]
    assert "const a0" in result["html"] and "const a19" in result["html"]
    assert "<pre" in result["html"]
    assert result["start_line"] == 3 and result["end_line"] == 24
    Balanced(result["html"])


def test_table_nested_list_references_footnotes_and_anchors(tmp_path):
    source = "# 제목\n\n| A | B |\n| - | - |\n| [링크][ref] | **값** |\n\n## 같은 제목\n\n## 같은 제목\n\n1. 항목\n   - 중첩\n\n각주[^가]\n\n[ref]: guide.md#section\n\n[^가]: 각주 원문"
    path = prepare(tmp_path, source)
    table = read_page(path, evidence(5))
    assert "<thead" in table["html"] and "<strong>값</strong>" in table["html"]
    assert 'href="guide.md#section"' in table["html"]
    anchor = read_page(path, evidence(), mode="document", anchor="같은-제목-1")
    assert anchor["anchor_found"] and 'data-document-anchor="같은-제목-1"' in anchor["html"]
    assert "각주 원문" in anchor["html"]
    assert read_page(path, evidence(), anchor="absent")["anchor_found"] is False


def test_huge_table_pages_repeat_headers_and_keep_hit(tmp_path):
    source = "| 항목 | 값 |\n| - | - |\n" + "\n".join(f"| 행{i} | 값{i} |" for i in range(3000))
    path = prepare(tmp_path, source)
    result = read_page(path, evidence(2503, text="행2500"))
    assert "행2500" in result["html"]
    assert "<thead" in result["html"]
    assert result["continued"] and len(result["html"].encode()) <= RESPONSE_HTML_BYTES
    with sqlite3.connect(path) as db:
        for rendered, size in db.execute("SELECT html,bytes FROM pages"):
            assert size <= PAGE_BYTES and "<thead" in rendered
            Balanced(rendered)


def test_huge_numbered_list_keeps_original_numbers(tmp_path):
    path = prepare(tmp_path, "\n".join(f"{i}. 항목{i}" for i in range(3, 2003)))
    result = read_page(path, evidence(1800, text="항목1802"))
    assert '<li value="1802"' in result["html"] or 'value="1802"' in result["html"]
    assert "항목1802" in result["html"]
    Balanced(result["html"])


def test_multimegabyte_single_line_is_bounded_and_source_pages_lossless(tmp_path):
    text = "한글😀 **강조** " * 240000  # Over 5 MB; a single atomic paragraph.
    path = prepare(tmp_path, text)
    assert len(text.encode()) > 5_000_000
    result = read_page(path, evidence())
    assert len(json.dumps(result, ensure_ascii=False).encode()) < 128 * 1024
    assert result["total_pages"] > 100
    Balanced(result["html"])
    # Source pages don't read/materialize the complete source blob in Python.
    offset, parts = 0, []
    while offset is not None:
        page = read_page(path, evidence(), mode="source", source_offset=offset)
        assert len(page["text"].encode()) <= SOURCE_BYTES
        parts.append(page["text"])
        offset = page["next_offset"]
    assert "".join(parts) == text


def test_outline_is_paged_and_plain_text_not_interpreted(tmp_path):
    path = prepare(tmp_path, "\n\n".join(f"# 제목{i}" for i in range(200)))
    first = read_page(path, evidence(), mode="document")
    second = read_page(path, evidence(), mode="document", outline_offset=80)
    assert len(first["headings"]) == len(second["headings"]) == 80
    assert first["outline_total"] == 200
    assert second["headings"][0]["title"] == "제목80"


def test_txt_preserves_literal_markdown_and_crlf_source_offsets(tmp_path):
    path = prepare(tmp_path, "# 제목\r\n\r\n**원문**😀\r\n", name="source.txt")
    page = read_page(path, evidence(), mode="document")
    assert "<pre" in page["html"] and "<strong>" not in page["html"]
    assert "**원문**" in page["html"]
    source = read_page(path, evidence(3), mode="source")
    assert source["text"] == "**원문**😀\n" and source["start_line"] == 3
    # Caller-provided byte offsets cannot split a Korean codepoint.
    assert read_page(path, evidence(), mode="source", source_offset=3)["text"].startswith("제목")


def test_out_of_range_definitions_do_not_require_original_text_on_client(tmp_path):
    source = "[링크][ref]\n\n" + "별도 내용\n\n" * 1000 + "[ref]: https://example.com/original"
    path = prepare(tmp_path, source)
    page = read_page(path, evidence(1))
    assert 'href="https://example.com/original"' in page["html"]
    assert "별도 내용" not in page["html"]
    assert "source" not in page and "snapshot" not in page


def test_huge_code_line_exact_hit_and_every_page_is_balanced(tmp_path):
    text = "````js\n" + "x = 1; " * 20000 + "UNIQUE_SEARCH_TARGET" + " y = 2;" * 20000 + "\n````"
    path = prepare(tmp_path, text)
    page = read_page(path, evidence(2, text="UNIQUE_SEARCH_TARGET"))
    assert "UNIQUE_SEARCH_TARGET" in page["html"]
    assert "<pre" in page["html"] and "<code" in page["html"]
    with sqlite3.connect(path) as db:
        for (rendered,) in db.execute("SELECT html FROM pages"):
            Balanced(rendered)


def test_oversized_table_cell_never_shifts_columns(tmp_path):
    path = prepare(tmp_path, "| A | B |\n| - | - |\n| " + "큰셀" * 10000 + " | SECOND_COLUMN |")
    result = read_page(path, evidence(3, text="SECOND_COLUMN"))
    assert "<td></td><td>SECOND_COLUMN</td>" in result["html"]
    Balanced(result["html"])


def test_unsafe_html_images_and_links_are_not_sent(tmp_path):
    path = prepare(
        tmp_path,
        '# 문서\n\n<script>alert(1)</script>\n\n[위험](javascript:alert(1))\n\n![외부](https://example.com/image)\n\n<a onclick="evil()">x</a>',
    )
    page = read_page(path, evidence(), mode="document")
    assert "<script" not in page["html"] and "<img" not in page["html"] and "onclick=" not in page["html"]
    assert 'href="javascript:' not in page["html"]


def test_cached_api_never_selects_full_snapshot_and_scope_is_preserved(client):
    c, root, core = client
    folder = root / "pages"
    folder.mkdir()
    (folder / "doc.md").write_text("# 정책\n\n| 항목 | 기간 |\n| - | - |\n| 보관 | 73일 |")
    wid = create(c, "pages")
    first = index(c, wid)
    assert first["state"] == "READY"
    hit = search(c, wid)["evidence"][0]
    queries = []
    core.db.conn.set_trace_callback(queries.append)
    url = f"/api/rag/workspaces/{wid}/evidence/{hit['evidence_id']}"
    response = c.get(url, params={"revision_id": first["revision_id"], "view": "preview"})
    core.db.conn.set_trace_callback(None)
    assert response.status_code == 200
    assert "snapshot" not in response.json() and "document" in response.json()
    assert not any("SELECT parsed" in q or "SELECT * FROM document_versions" in q for q in queries)
    metadata = c.get(
        f"/api/rag/workspaces/{wid}/documents", params={"relative_path": "doc.md", "metadata_only": True}
    ).json()
    assert "snapshot" not in metadata
    assert (
        c.get(url, params={"revision_id": first["revision_id"], "view": "preview", "page": -1}).status_code
        == 422
    )
    other = create(c, "pages", "다른 공간")
    assert index(c, other)["state"] == "READY"
    assert (
        c.get(
            url.replace(wid, other), params={"revision_id": first["revision_id"], "view": "preview"}
        ).status_code
        == 409
    )
    (folder / "doc.md").unlink()
    folder.rmdir()
    assert c.get(url, params={"revision_id": first["revision_id"], "view": "preview"}).status_code != 200
