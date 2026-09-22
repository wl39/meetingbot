FROM node:22-bookworm-slim AS frontend
WORKDIR /build
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM python:3.12-slim-bookworm
LABEL org.opencontainers.image.title="Meetingbot" \
      org.opencontainers.image.source="https://github.com/wl39/meetingbot" \
      org.opencontainers.image.licenses="MIT"
ENV PYTHONUNBUFFERED=1 UV_LINK_MODE=copy MEETINGBOT_CONTAINER=1 STT_DATA_DIR=/data/stt RAG_DATA_DIR=/data/rag
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg libgomp1 \
    && rm -rf /var/lib/apt/lists/* \
    && pip install --no-cache-dir 'uv>=0.8,<1'
WORKDIR /app
COPY LICENSE ./LICENSE
COPY backend/pyproject.toml backend/uv.lock ./backend/
COPY rag/pyproject.toml rag/uv.lock ./rag/
COPY shared/access ./shared/access
RUN uv sync --project backend --frozen --extra speech --no-dev --no-cache \
    && uv sync --project rag --frozen --no-dev --no-cache
COPY backend/app ./backend/app
COPY rag/meetingbot_rag ./rag/meetingbot_rag
COPY prompts ./prompts
COPY scripts/launch.py scripts/prepare_models.py ./scripts/
COPY --from=frontend /build/dist ./frontend/dist
RUN useradd --create-home --uid 1000 meetingbot && mkdir /data && chown meetingbot:meetingbot /data
USER meetingbot
EXPOSE 8765
CMD ["/app/backend/.venv/bin/python", "/app/scripts/launch.py", "--container", "--no-browser"]
