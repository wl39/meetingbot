"""Repeatable synthetic 5 MiB server-page benchmark. No model or service writes."""
import gc
import hashlib
import json
import resource
import sqlite3
import statistics
import subprocess
import sys
import tempfile
import time
import tracemalloc
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "rag"))
from meetingbot_rag.markdown_views import build_index, read_page  # noqa: E402

if len(sys.argv) > 1 and sys.argv[1] == "--worker":
    started = time.perf_counter()
    build_index(*sys.argv[2:5])
    rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    print(json.dumps({"seconds": time.perf_counter() - started, "peak_rss_bytes": rss if sys.platform == "darwin" else rss * 1024}))
    raise SystemExit

with tempfile.TemporaryDirectory(prefix="meetingbot-markdown-benchmark-") as temporary:
    root = Path(temporary)
    database, output = root / "registry.sqlite", root / "view.sqlite"
    sections, size, number = [], 0, 0
    body = "운영 기준과 회의 기록의 보관 절차를 설명하는 검증 문장입니다. " * 45
    while size < 5 * 1024 * 1024:
        section = f"## 절차 {number}\n\n{body}\n\n"
        sections.append(section)
        size += len(section.encode())
        number += 1
    text = "".join(sections)
    chunks = [{"chunk_id": str(i), "text": "검증 문장", "location": {"start_line": 4 * i + 3, "end_line": 4 * i + 3}} for i in range(number)]
    with sqlite3.connect(database) as db:
        db.executescript("CREATE TABLE documents(id TEXT,relative_path TEXT); CREATE TABLE document_versions(id TEXT,document_id TEXT,parsed TEXT,content_hash TEXT,chunks TEXT);")
        db.execute("INSERT INTO documents VALUES('doc','benchmark.md')")
        db.execute("INSERT INTO document_versions VALUES(?,?,?,?,?)", ("version", "doc", json.dumps({"text": text}, ensure_ascii=False), hashlib.sha256(text.encode()).hexdigest(), json.dumps(chunks)))
    built = subprocess.run([sys.executable, __file__, "--worker", str(database), "version", str(output)], text=True, capture_output=True, check=True, timeout=60)
    cold = json.loads(built.stdout)
    selected = chunks[number // 2]
    hit = {"evidence_id": "revision." + selected["chunk_id"], "text": selected["text"], "location": selected["location"]}
    del text, sections, chunks
    gc.collect()
    times, sizes = [], []
    tracemalloc.start()
    for _ in range(30):
        start = time.perf_counter()
        result = read_page(output, hit)
        encoded = json.dumps({"workspace_id": "synthetic", "revision_id": "synthetic", "document": result}, ensure_ascii=False).encode()
        times.append((time.perf_counter() - start) * 1000)
        sizes.append(len(encoded))
        assert len(encoded) < 128 * 1024
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    report = {
        "synthetic": True, "source_bytes": size, "index_bytes": output.stat().st_size,
        "cold_build_seconds": round(cold["seconds"], 3), "cold_worker_peak_rss_mib": round(cold["peak_rss_bytes"] / 1024**2, 2),
        "warm_requests": len(times), "warm_median_ms_with_tracemalloc": round(statistics.median(times), 3),
        "warm_p95_ms_with_tracemalloc": round(sorted(times)[int(len(times) * .95) - 1], 3),
        "warm_extra_python_peak_kib": round(peak / 1024, 2), "response_bytes": max(sizes), "html_bytes": result["html_bytes"],
        "payload_reduction_percent_vs_full_source": round(100 * (1 - max(sizes) / size), 2),
        "notes": "Local disk server-render test; not an internet latency SLA. One-time cold index cost is separate from warm page reads. No LLM calls.",
    }
    dest = ROOT / ".runtime/markdown-integrity-qa/server-benchmark.json"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(report, ensure_ascii=False, indent=2))
    print(json.dumps(report, ensure_ascii=False, indent=2))
