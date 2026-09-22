"""JSON-lines test bridge to the actual server renderer; synthetic documents only."""
import json
import sqlite3
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "rag"))
from meetingbot_rag.markdown_views import build_index, read_page  # noqa: E402

with tempfile.TemporaryDirectory(prefix="meetingbot-markdown-fixture-") as directory:
    root = Path(directory)
    database = root / "registry.sqlite"
    with sqlite3.connect(database) as db:
        db.executescript("CREATE TABLE documents(id TEXT,relative_path TEXT); CREATE TABLE document_versions(id TEXT,document_id TEXT,parsed TEXT,content_hash TEXT,chunks TEXT);")
    for line in sys.stdin:
        request = json.loads(line)
        try:
            name = request["name"]
            if not name.isalnum():
                raise ValueError("Invalid fixture name")
            output = root / f"{name}.sqlite"
            if request["action"] == "add":
                text = request["text"]
                chunks = [{"chunk_id": str(i), "location": {"start_line": i, "end_line": i}} for i in range(1, len(text.split("\n")) + 1)]
                with sqlite3.connect(database) as db:
                    db.execute("INSERT INTO documents VALUES(?,?)", (name, name + ".md"))
                    db.execute("INSERT INTO document_versions VALUES(?,?,?,?,?)", (name, name, json.dumps({"text": text}), "synthetic", json.dumps(chunks)))
                build_index(database, name, output)
                result = True
            else:
                result = read_page(output, request["evidence"], **request["options"])
            print(json.dumps({"id": request["id"], "result": result}), flush=True)
        except Exception as error:
            print(json.dumps({"id": request["id"], "error": str(error)}), flush=True)
