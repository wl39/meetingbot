# Contributing

Preserve existing user changes and STT behavior. RAG code belongs in `rag/meetingbot_rag` and `frontend/src/features/rag`; keep speech dependencies out of the RAG environment.

Run `uv sync --project rag --frozen`, `uv run --project rag pytest rag/tests -q`, `npm --prefix frontend test`, and `npm --prefix frontend run build`. Run STT regression tests with `backend/.venv/bin/python -m pytest backend/tests -q` from the repository root. See `docs/rag/test-results.md` for integration tests using synthetic documents.

Do not commit runtime data, real documents, credentials, embeddings or model caches. Include migration/backup steps with schema changes and preserve immutable active revisions until a replacement has been validated. Project code is released under the [MIT License](LICENSE). Contributions to project code use the same license; retain applicable third-party notices.

See [source structure and module boundaries](docs/code-structure.md) before adding features. Keep page composition separate from asynchronous hooks and domain views. Reuse `frontend/src/components/ui` for cross-feature UI, while keeping model/chunk/transcript-specific components inside their feature. Shared UI must not import feature APIs or workspace state. Keep API routing separate from domain services and retain the established `create_app` entry points.

When moving or removing Python modules, deploy through the shared `scripts/support/deployment.py` source-tree replacement helper so obsolete modules are not left behind. Run `uv run --project backend pytest scripts/tests -q` for deployment rollback and demo checks. Runtime state and model caches must stay outside the code replacement boundary.
