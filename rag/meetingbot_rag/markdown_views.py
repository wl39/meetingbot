"""Disk-backed, server-rendered document pages. No whole-document reads on warm requests.

The complete grammar is parsed once per immutable document version, in a bounded
worker process. Requests expand chunk windows 1,2,4,... against those known block
boundaries. Oversized blocks are paginated as balanced HTML, never cut Markdown.
"""

import hashlib
import html
import json
import re
import sqlite3
import sys
import unicodedata
from dataclasses import dataclass, field
from html.parser import HTMLParser

import bleach
from markdown_it import MarkdownIt
from mdit_py_plugins.footnote import footnote_plugin
from mdit_py_plugins.tasklists import tasklists_plugin

from .db import open_database

VIEW_VERSION = 1
PAGE_BYTES = 24 * 1024
RESPONSE_HTML_BYTES = 48 * 1024
SOURCE_BYTES = 16 * 1024
OUTLINE_LIMIT = 80
VOID = {"br", "hr", "input"}
TAGS = {
    "p",
    "div",
    "span",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "ul",
    "ol",
    "li",
    "blockquote",
    "pre",
    "code",
    "strong",
    "em",
    "s",
    "a",
    "sup",
    "section",
    "table",
    "thead",
    "tbody",
    "tr",
    "th",
    "td",
    *VOID,
}
ATTRS = {
    "href",
    "title",
    "class",
    "id",
    "start",
    "value",
    "type",
    "checked",
    "disabled",
    "data-source-start",
    "data-source-end",
    "data-document-anchor",
    "data-document-id",
}


def safe_attribute(tag, name, value):
    if name not in ATTRS or len(value.encode()) > 2048:
        return False
    if name == "href":
        return not value.startswith(("/", "\\")) and not re.search(r"[\x00-\x20]", value)
    if name == "type":
        return value == "checkbox"
    return True


@dataclass
class Node:
    tag: str = ""
    attrs: dict = field(default_factory=dict)
    children: list = field(default_factory=list)
    text: str = ""
    start: int = 1
    end: int = 1

    def opening(self):
        if not self.tag:
            return ""
        return (
            "<"
            + self.tag
            + "".join(f' {k}="{html.escape(str(v), quote=True)}"' for k, v in self.attrs.items())
            + ">"
        )

    def closing(self):
        return "" if not self.tag or self.tag in VOID else f"</{self.tag}>"

    def render(self):
        return (
            self.opening()
            + html.escape(self.text)
            + "".join(child.render() for child in self.children)
            + self.closing()
        )

    def plain(self):
        return self.text + "".join(child.plain() for child in self.children)


class Tree(HTMLParser):
    def __init__(self, source, start, end):
        super().__init__(convert_charrefs=True)
        self.root = Node(start=start, end=end)
        self.stack = [self.root]
        self.feed(source)
        self.close()

    def handle_starttag(self, tag, attrs):
        parent = self.stack[-1]
        attrs = dict(attrs)
        node = Node(
            tag,
            attrs,
            start=int(attrs.get("data-source-start", parent.start)),
            end=int(attrs.get("data-source-end", parent.end)),
        )
        # Page-local DOM identifiers cannot clobber global browser properties.
        if "id" in node.attrs:
            node.attrs["data-document-id"] = node.attrs.pop("id")
        if tag == "li" and parent.tag == "ol":
            node.attrs["value"] = int(parent.attrs.get("start", 1)) + sum(
                c.tag == "li" for c in parent.children
            )
        if tag == "input":
            node.attrs.update(type="checkbox", disabled="")
        parent.children.append(node)
        if tag not in VOID:
            self.stack.append(node)

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag not in VOID:
            self.handle_endtag(tag)

    def handle_endtag(self, tag):
        if len(self.stack) > 1 and self.stack[-1].tag == tag:
            self.stack.pop()

    def handle_data(self, data):
        parent = self.stack[-1]
        if not data.strip() and parent.tag in {"", "table", "thead", "tbody", "tr", "ol", "ul", "section"}:
            return
        parent.children.append(Node(text=data, start=parent.start, end=parent.end))


def fragments(node, limit=PAGE_BYTES):
    """Split oversized DOM nodes while repeating every enclosing tag.

    Table headers and original ordered-list numbers survive page boundaries.
    Even a multi-megabyte single paragraph/code line remains bounded and valid.
    """
    rendered = node.render()
    if len(rendered.encode()) <= limit:
        yield rendered, node.start, node.end, node.plain()
        return
    del rendered
    prefix, suffix = node.opening(), node.closing()
    budget = limit - len((prefix + suffix).encode())
    if budget < 1024:
        raise ValueError("VIEW_NESTING_LIMIT")
    if not node.children:
        # Each codepoint consumes <= 6 escaped UTF-8 bytes. Never split an entity.
        width = max(1, budget // 6)
        current_line = node.start
        for offset in range(0, len(node.text), width):
            text = node.text[offset : offset + width]
            first = min(node.end, current_line)
            last = min(node.end, first + text.count("\n"))
            current_line += text.count("\n")
            yield prefix + html.escape(text) + suffix, first, last, text
        return
    children = node.children
    if node.tag == "tr" and all(child.tag in {"td", "th"} for child in children):
        # Keep the original column positions when even one cell exceeds a page.
        empty = [child.opening() + child.closing() for child in children]
        for index, child in enumerate(children):
            before, after = "".join(empty[:index]), "".join(empty[index + 1 :])
            for rendered, first, last, plain in fragments(child, budget - len((before + after).encode())):
                yield prefix + before + rendered + after + suffix, first, last, plain
        return
    if node.tag == "table":
        header = next((child for child in children if child.tag == "thead"), None)
        if header and len(header.render().encode()) < budget // 2:
            prefix += header.render()
            budget -= len(header.render().encode())
            children = [child for child in children if child is not header]
    pending, plain, start, end, size = [], [], None, None, 0
    for child in children:
        for rendered, first, last, value in fragments(child, budget):
            cost = len(rendered.encode())
            if pending and cost + size > budget:
                yield prefix + "".join(pending) + suffix, start, end, "".join(plain)
                pending, plain, start, end, size = [], [], None, None, 0
            pending.append(rendered)
            plain.append(value)
            start = first if start is None else min(start, first)
            end = last if end is None else max(end, last)
            size += cost
    if pending:
        yield prefix + "".join(pending) + suffix, start, end, "".join(plain)


def parser():
    md = MarkdownIt("gfm-like", {"html": True, "maxNesting": 32}).use(footnote_plugin).use(tasklists_plugin)
    md.renderer.rules["html_block"] = lambda *_: ""
    # Preserve tasklist plugin's safe generated checkbox, not arbitrary user HTML.
    md.renderer.rules["html_inline"] = lambda tokens, idx, *_: (
        tokens[idx].content
        if tokens[idx].content.startswith('<input class="task-list-item-checkbox"')
        else ""
    )
    md.renderer.rules["image"] = lambda tokens, idx, *_: (
        '<span class="rag-markdown-image">[이미지: ' + html.escape(tokens[idx].content) + "]</span>"
    )
    original_fence = md.renderer.rules["fence"]

    def fence(tokens, idx, options, env):
        token = tokens[idx]
        return original_fence(tokens, idx, options, env).replace(
            "<pre>", f'<pre data-source-start="{token.map[0] + 1}" data-source-end="{token.map[1]}">', 1
        )

    md.renderer.rules["fence"] = fence
    return md


def build_index(database, version_id, output):
    """Worker-only cold build. The registry source is loaded exactly once here."""
    with open_database(database, readonly=True) as registry:
        row = registry.execute(
            "SELECT v.parsed,v.content_hash,v.chunks,d.relative_path FROM document_versions v JOIN documents d ON v.document_id=d.id WHERE v.id=?",
            (version_id,),
        ).fetchone()
    parsed, content_hash, chunks_json = json.loads(row[0]), row[1], row[2]
    text = parsed["text"].replace("\r\n", "\n").replace("\r", "\n")
    md, env = parser(), {}
    if row[3].lower().endswith(".txt"):
        from markdown_it.token import Token

        token = Token("code_block", "code", 0)
        token.content, token.map = text, [0, text.count("\n") + 1]
        tokens = [token]
    else:
        tokens = md.parse(text, env)
    headings, used = [], set()
    for index, token in enumerate(tokens):
        alignment = token.attrGet("style")
        if alignment in {"text-align:left", "text-align:center", "text-align:right"}:
            token.attrSet("class", "md-align-" + alignment.split(":")[1])
        if token.map and token.nesting >= 0 and token.tag:
            token.attrSet("data-source-start", str(token.map[0] + 1))
            token.attrSet("data-source-end", str(token.map[1]))
        if token.type == "heading_open":
            title = "".join(
                t.content
                for t in (tokens[index + 1].children or [])
                if t.type in {"text", "code_inline", "image"}
            )
            base = re.sub(r"[^\w\s-]", "", unicodedata.normalize("NFC", title).lower()).replace(" ", "-")
            if len(base.encode()) > 512:
                base = "section-" + hashlib.sha256(base.encode()).hexdigest()[:24]
            slug, number = base, 0
            while slug in used:
                number += 1
                slug = f"{base}-{number}"
            used.add(slug)
            token.attrSet("data-document-anchor", slug)
            headings.append((slug, title[:300], int(token.tag[1]), token.map[0] + 1))
    cleaner = bleach.Cleaner(tags=TAGS, attributes=safe_attribute, protocols={"http", "https"}, strip=True)
    with open_database(output) as db:
        db.executescript("""
          CREATE TABLE meta(version INTEGER,content_hash TEXT,total_lines INTEGER,source BLOB);
          CREATE TABLE lines(line INTEGER PRIMARY KEY,offset INTEGER);
          CREATE INDEX line_offsets ON lines(offset);
          CREATE TABLE blocks(id INTEGER PRIMARY KEY,start_line INTEGER,end_line INTEGER,first_page INTEGER,last_page INTEGER);
          CREATE INDEX block_lines ON blocks(start_line,end_line);
          CREATE TABLE pages(id INTEGER PRIMARY KEY,block_id INTEGER,start_line INTEGER,end_line INTEGER,html TEXT,plain TEXT,bytes INTEGER);
          CREATE INDEX page_lines ON pages(start_line,end_line);
          CREATE TABLE chunks(id INTEGER PRIMARY KEY,chunk_id TEXT,start_line INTEGER,end_line INTEGER);
          CREATE INDEX chunk_key ON chunks(chunk_id);
          CREATE TABLE headings(id INTEGER PRIMARY KEY,anchor TEXT,title TEXT,level INTEGER,line INTEGER,page INTEGER);
          CREATE TABLE anchors(anchor TEXT PRIMARY KEY,page INTEGER);
        """)
        encoded = text.encode()
        db.execute(
            "INSERT INTO meta VALUES(?,?,?,?)", (VIEW_VERSION, content_hash, text.count("\n") + 1, encoded)
        )
        offset = 0
        for number, line in enumerate(text.split("\n"), 1):
            db.execute("INSERT INTO lines VALUES(?,?)", (number, offset))
            offset += len(line.encode()) + 1
        db.executemany(
            "INSERT INTO chunks VALUES(?,?,?,?)",
            [
                (
                    i,
                    chunk["chunk_id"],
                    chunk["location"].get("start_line", 1),
                    chunk["location"].get("end_line", 1),
                )
                for i, chunk in enumerate(json.loads(chunks_json))
            ],
        )
        block_start, depth, block_id, page_id = 0, 0, 0, 0
        for index, token in enumerate(tokens):
            depth += token.nesting
            if depth != 0:
                continue
            group = tokens[block_start : index + 1]
            block_start = index + 1
            maps = [t.map for t in group if t.map]
            if not maps:
                continue
            start, end = min(m[0] for m in maps) + 1, max(m[1] for m in maps)
            rendered = cleaner.clean(md.renderer.render(group, md.options, env))
            tree = Tree(rendered, start, end)
            first_page = page_id
            for rendered, first, last, plain in fragments(tree.root):
                if not rendered.strip():
                    continue
                cost = len(rendered.encode())
                if cost > PAGE_BYTES:
                    raise ValueError("VIEW_PAGE_LIMIT")
                db.execute(
                    "INSERT INTO pages VALUES(?,?,?,?,?,?,?)",
                    (page_id, block_id, first, last, rendered, plain, cost),
                )
                for anchor in re.findall(r'data-document-(?:anchor|id)="([^"]*)"', rendered):
                    db.execute("INSERT OR IGNORE INTO anchors VALUES(?,?)", (html.unescape(anchor), page_id))
                page_id += 1
            if page_id > first_page:
                db.execute(
                    "INSERT INTO blocks VALUES(?,?,?,?,?)", (block_id, start, end, first_page, page_id - 1)
                )
                block_id += 1
        for number, (slug, title, level, line) in enumerate(headings):
            found = db.execute("SELECT page FROM anchors WHERE anchor=?", (slug,)).fetchone()
            if found:
                db.execute(
                    "INSERT INTO headings VALUES(?,?,?,?,?,?)", (number, slug, title, level, line, found[0])
                )


def read_page(
    path, evidence, *, mode="preview", page=None, anchor=None, outline_offset=0, source_offset=None
):
    """Only small indexed rows / bounded BLOB slices are materialized in Python."""
    with open_database(path, readonly=True) as db:
        explicit_page = page is not None
        db.row_factory = sqlite3.Row
        meta = db.execute("SELECT total_lines,length(source) source_bytes FROM meta").fetchone()
        total = db.execute("SELECT count(*) FROM pages").fetchone()[0]
        location = evidence["location"]
        hit_start, hit_end = location.get("start_line", 1), location.get("end_line", 1)
        radius, anchor_found, expansion_steps = 0, True, []
        if mode == "source":
            if source_offset is None:
                row = db.execute(
                    "SELECT offset FROM lines WHERE line<=? ORDER BY line DESC LIMIT 1", (hit_start,)
                ).fetchone()
                source_offset = row[0] if row else 0
            source_offset = min(source_offset, meta["source_bytes"])
            # SQLite incremental BLOB I/O, not substr(source), which can first
            # materialize the entire value inside SQLite despite a short result.
            with db.blobopen("meta", "source", 1, readonly=True) as blob:
                if source_offset < len(blob):
                    blob.seek(source_offset)
                    while source_offset and (blob.read(1)[0] & 0xC0) == 0x80:
                        source_offset -= 1
                        blob.seek(source_offset)
                blob.seek(source_offset)
                raw = blob.read(SOURCE_BYTES)
            value = raw.decode("utf-8", errors="ignore")
            consumed = len(value.encode())
            line = db.execute(
                "SELECT line,offset FROM lines WHERE offset<=? ORDER BY offset DESC LIMIT 1", (source_offset,)
            ).fetchone()
            return {
                "kind": "source_page",
                "text": value,
                "start_line": line[0] if line else 1,
                "mid_line": bool(line and source_offset > line[1]),
                "offset": source_offset,
                "next_offset": source_offset + consumed
                if source_offset + consumed < meta["source_bytes"]
                else None,
                "total_bytes": meta["source_bytes"],
                "total_lines": meta["total_lines"],
            }
        if anchor:
            target = unicodedata.normalize("NFC", anchor)
            row = db.execute("SELECT page FROM anchors WHERE anchor=?", (target,)).fetchone()
            anchor_found = bool(row)
            if row:
                page = row[0]
        chunk = db.execute(
            "SELECT id FROM chunks WHERE chunk_id=?", (evidence["evidence_id"].split(".")[-1],)
        ).fetchone()
        block = db.execute(
            "SELECT * FROM blocks WHERE end_line>=? AND start_line<=? ORDER BY start_line LIMIT 1",
            (hit_start, hit_end),
        ).fetchone()
        if page is None and block and mode == "preview" and chunk:
            radius = 1
            while True:
                expansion_steps.append(radius)
                window = db.execute(
                    "SELECT min(start_line),max(end_line) FROM chunks WHERE id BETWEEN ? AND ?",
                    (chunk[0] - radius, chunk[0] + radius),
                ).fetchone()
                boundaries = db.execute(
                    "SELECT min(start_line),max(end_line),min(first_page),max(last_page) FROM blocks WHERE end_line>=? AND start_line<=?",
                    (hit_start, hit_end),
                ).fetchone()
                # Smallest complete blocks containing the hit, not all neighboring text.
                if window[0] <= boundaries[0] and window[1] >= boundaries[1]:
                    break
                needed = db.execute(
                    "SELECT sum(bytes) FROM pages WHERE id BETWEEN ? AND ?", (boundaries[2], boundaries[3])
                ).fetchone()[0]
                if radius >= 128 or needed > RESPONSE_HTML_BYTES:
                    break
                radius *= 2
            page = block["first_page"]
        if page is None:
            page = block["first_page"] if block else 0
        page = max(0, min(page, max(0, total - 1)))
        # For a huge list/table, choose the subpage containing the actual hit line.
        if not explicit_page and block and block["last_page"] > block["first_page"] and not anchor:
            candidate = db.execute(
                "SELECT id FROM pages WHERE block_id=? AND start_line<=? AND end_line>=? ORDER BY id LIMIT 1",
                (block["id"], hit_start, hit_start),
            ).fetchone()
            if candidate:
                page = candidate[0]
            # Same-line oversized paragraphs/code: exact visible-text match if possible.
            needle = evidence["text"].strip()[:160]
            candidate = (
                db.execute(
                    "SELECT id FROM pages WHERE block_id=? AND instr(plain,?)>0 LIMIT 1",
                    (block["id"], needle),
                ).fetchone()
                if needle
                else None
            )
            if candidate:
                page = candidate[0]
        rows, size = [], 0
        for row in db.execute(
            "SELECT id,start_line,end_line,html,bytes,block_id FROM pages WHERE id>=? ORDER BY id LIMIT 40",
            (page,),
        ):
            if size + row["bytes"] > RESPONSE_HTML_BYTES:
                break
            if rows and mode == "preview" and row["start_line"] > hit_end:
                break
            rows.append(dict(row))
            size += row["bytes"]
        headings = (
            [
                dict(row)
                for row in db.execute(
                    "SELECT anchor,substr(title,1,100) title,level,line,page FROM headings ORDER BY id LIMIT ? OFFSET ?",
                    (OUTLINE_LIMIT, outline_offset),
                )
            ]
            if mode == "document"
            else []
        )
        count = db.execute("SELECT count(*) FROM headings").fetchone()[0] if mode == "document" else 0
        first, last = rows[0]["id"] if rows else 0, rows[-1]["id"] if rows else -1
        previous, previous_size = None, 0
        for item in db.execute("SELECT id,bytes FROM pages WHERE id<? ORDER BY id DESC LIMIT 40", (first,)):
            if previous_size + item[1] > RESPONSE_HTML_BYTES:
                break
            previous, previous_size = item[0], previous_size + item[1]
        result = {
            "kind": "rendered_page",
            "html": "".join(row["html"] for row in rows),
            "start_line": min((row["start_line"] for row in rows), default=1),
            "end_line": max((row["end_line"] for row in rows), default=1),
            "page": first,
            "last_page": last,
            "total_pages": total,
            "previous_page": previous,
            "next_page": last + 1 if last + 1 < total else None,
            "headings": headings,
            "outline_offset": outline_offset,
            "outline_total": count,
            "anchor_found": anchor_found,
            "radius_chunks": radius,
            "expansion_steps": expansion_steps,
            "html_bytes": size,
            "source_bytes": meta["source_bytes"],
            "total_lines": meta["total_lines"],
            "continued": bool(block and block["last_page"] > block["first_page"]),
            "engine": "server",
        }
        # Include JSON escaping and metadata, not merely HTML, in the wire budget.
        while len(json.dumps(result, ensure_ascii=False).encode()) > 120 * 1024 and result["headings"]:
            result["headings"].pop()
        return result


if __name__ == "__main__":
    build_index(*sys.argv[1:4])
