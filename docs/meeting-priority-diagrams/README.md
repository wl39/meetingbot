# Priority / Sub Queue 설계도

[설계 문서](../meeting-priority-design.md)의 Mermaid 블록을 추출한 원본과 렌더링 결과다. 설계가 바뀌면 원본을 다시 추출한 뒤 이미지도 갱신해야 한다.

| 그림 | SVG | PNG 미리보기 | Mermaid 원본 |
|---|---|---|---|
| 전체 구조 | [architecture.svg](architecture.svg) | [architecture.png](architecture.png) | [architecture.mmd](architecture.mmd) |
| 스케줄러 보호·회복 모드 | [scheduling-modes.svg](scheduling-modes.svg) | [scheduling-modes.png](scheduling-modes.png) | [scheduling-modes.mmd](scheduling-modes.mmd) |
| 작업 수명주기 | [job-lifecycle.svg](job-lifecycle.svg) | [job-lifecycle.png](job-lifecycle.png) | [job-lifecycle.mmd](job-lifecycle.mmd) |
| 사용자 Use Case | [use-cases.svg](use-cases.svg) | [use-cases.png](use-cases.png) | [use-cases.mmd](use-cases.mmd) |
| PQ 우선 처리 시나리오 | [sequence.svg](sequence.svg) | [sequence.png](sequence.png) | [sequence.mmd](sequence.mmd) |

Mermaid 12.0.0의 `mermaid.parse()`와 `mermaid.render()`로 5개 모두 문법 검증 및 렌더링을 완료했다. 기존 `playwright-core`와 로컬 Google Chrome을 사용했고 Mermaid 설치는 작업용 임시 디렉터리에서 진행했다. 애플리케이션 의존성 파일은 수정하지 않았다.

PNG는 렌더링 크기의 1.5배 해상도이며, SVG는 확대해서 볼 수 있다. 전체 구조와 사용자 Use Case를 포함해 다섯 그림의 한글 표시·선 연결·잘림·겹침을 시각 확인했다. 렌더링 버전과 SVG 크기는 [validation.json](validation.json)에 기록했다. 이는 도식 검증이며 실제 큐 구현이나 성능 시험 결과가 아니다.
