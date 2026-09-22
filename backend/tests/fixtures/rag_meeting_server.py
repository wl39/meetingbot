"""Synthetic RAG process for the bridge integration test; never calls a provider."""

import hashlib
import json
import re
import sys
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import uvicorn

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "rag"))

from meetingbot_rag.app import create_app  # noqa: E402
from meetingbot_rag.settings import Settings  # noqa: E402

POLICY = "운영서버 로그 기록의 보관 기간은 90일입니다."


class FakeModel:
    state, dimension, limit, device = "READY", 384, 512, "fake"

    def load(self):
        pass

    def tokens(self, text):
        return len(text) // 2 + 2

    def encode(self, texts, query=False):
        vectors = []
        for text in texts:
            vector = np.zeros(self.dimension)
            for word in re.findall(r"\w+", text):
                for i in range(max(1, len(word) - 1)):
                    token = word[i:i + 2]
                    vector[int(hashlib.md5(token.encode()).hexdigest(), 16) % self.dimension] += 1
            vectors.append((vector / max(np.linalg.norm(vector), 1)).tolist())
        return vectors

    def health(self):
        return {"state": "READY", "model": "TEST_ONLY", "device": "fake", "revision": "fake", "dimension": 384}


class FakeLLM:
    def invoke(self, messages):
        payload = json.loads(messages[1][1])
        if "evidence" in payload:
            eid = payload["evidence"][0]["evidence_id"]
            value = {"status": "popup", "assessment": "contradicted", "scope_match": True,
                     "kind": "warning", "title": "로그 보관 기간 정정", "message": POLICY,
                     "confidence": 0.94, "citations": [eid],
                     "support_quotes": [{"evidence_id": eid, "quote": POLICY}]}
        else:
            text = payload["utterance"]["text"]
            score = 1 if text == "어" else (2 if text in {"안녕하세요", "개인 프로젝트 이야기예요"} else 4)
            value = {"score": score, "classification_state": "resolved",
                     "scope": "in_scope" if score == 4 else "out_of_scope",
                     "speech_act": {1: "filler", 2: "social", 4: "factual_claim"}[score],
                     "addressed_to_ai": False, "intent": "fact_check" if score == 4 else "none",
                     "keywords": ["로그", "보관 기간"] if score == 4 else [],
                     "query": "운영서버 로그 보관 기간" if score == 4 else "",
                     "claim": text if score == 4 else "", "reason_code": "SYNTHETIC_FIXTURE",
                     "action_supported": True}
        return SimpleNamespace(content=json.dumps(value, ensure_ascii=False))


def main():
    config = json.loads(Path(sys.argv[1]).read_text())
    port = config.pop("port")
    app = create_app(Settings(_env_file=None, **config), FakeModel())
    original = app.router.lifespan_context

    @asynccontextmanager
    async def lifespan(application):
        async with original(application):
            application.state.answer.factory.create = lambda _: FakeLLM()
            yield

    app.router.lifespan_context = lifespan
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")


if __name__ == "__main__":
    main()
