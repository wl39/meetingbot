# 의존성·모델 고지

프로젝트 코드는 [MIT License](../../LICENSE)를 따른다. 외부 패키지와 모델의 라이선스는 별도로 유지되며, 이 문서는 해당 고지 위치를 안내한다.

직접 의존성과 upstream 고지 위치:

| 구성 | 라이선스/고지 | 출처 |
|---|---|---|
| FastAPI / Pydantic / uvicorn | MIT / MIT / BSD-3-Clause | https://github.com/fastapi/fastapi ; https://github.com/pydantic/pydantic ; https://github.com/encode/uvicorn |
| Qdrant Python client | Apache-2.0 | https://github.com/qdrant/qdrant-client |
| Sentence Transformers | Apache-2.0 | https://github.com/huggingface/sentence-transformers |
| multilingual-e5-small 모델 | MIT (모델 카드 기준) | https://huggingface.co/intfloat/multilingual-e5-small |
| PyTorch | BSD-style 및 제3자 고지 | https://github.com/pytorch/pytorch/blob/main/LICENSE |
| openpyxl | MIT | https://foss.heptapod.net/openpyxl/openpyxl |
| LangChain OpenAI integration | MIT | https://github.com/langchain-ai/langchain |
| React / Vite / Playwright | MIT / MIT / Apache-2.0 | 각 패키지 LICENSE와 lockfile 참조 |

정확한 설치 버전은 `rag/uv.lock`과 `frontend/package-lock.json`에 고정된다. 모델은 공개 다운로드 가능하며 설치 시 고정 revision의 파일을 내려받는다. 모델 가중치는 저장소에 포함하지 않는다. 사용자에게 개발자의 개인 계정이나 중앙 서버를 필수로 요구하지 않는다. 제3자 패키지와 모델을 재배포할 때 해당 LICENSE와 NOTICE를 포함해야 한다.

공식 API 확인에 사용한 자료:
- [SentenceTransformer API](https://sbert.net/docs/package_reference/sentence_transformer/SentenceTransformer.html)
- [Qdrant client local mode](https://github.com/qdrant/qdrant-client)
- [LangChain ChatOpenAI integration](https://docs.langchain.com/oss/python/integrations/chat/openai)
- [Tailscale Serve](https://tailscale.com/docs/reference/tailscale-cli/serve)

CLIProxyAPI v7.2.155는 MIT 라이선스다. 공식 배포본의 LICENSE를 `~/Library/Application Support/MeetingbotCLIProxy/LICENSE`에 함께 설치한다. 바이너리는 저장소에 포함하지 않으며 고정된 공식 릴리스와 SHA256으로 설치한다.
