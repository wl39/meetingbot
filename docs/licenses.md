# 모델과 코드 라이선스

프로젝트 코드는 [MIT License](../LICENSE)를 따릅니다. 모델 파일과 외부 패키지에는 각자의 라이선스가 적용됩니다. 현재 준비 스크립트는 모델을 데이터 폴더의 로컬 캐시에 내려받으며, 저장소에 모델 가중치를 포함하지 않습니다. 재배포 시 각 upstream의 LICENSE/NOTICE 원문과 모델 카드의 표시 의무를 함께 확인해야 합니다.

| 구성 요소 | 구분 | upstream 표기 |
|---|---|---|
| MLX Whisper | 코드 | MIT, Apple 저작권 표시 |
| Faster Whisper / CTranslate2 | 코드 | MIT |
| OpenAI Whisper | 모델/코드 | MIT |
| pyannote.audio | 코드 | MIT |
| Community-1 | 모델 | CC BY 4.0, Hugging Face 접근 조건 별도 |
| Silero VAD | 코드/모델 | MIT |
| FFmpeg | 실행 프로그램 | 빌드 옵션에 따라 LGPL/GPL 구성 달라짐 |

확인 경로: [MLX Whisper](https://github.com/ml-explore/mlx-examples/tree/main/whisper), [Faster Whisper](https://github.com/SYSTRAN/faster-whisper), [CTranslate2](https://github.com/OpenNMT/CTranslate2), [Whisper](https://github.com/openai/whisper), [pyannote.audio](https://github.com/pyannote/pyannote-audio), [Community-1](https://huggingface.co/pyannote/speaker-diarization-community-1), [Silero VAD](https://github.com/snakers4/silero-vad), [FFmpeg legal](https://ffmpeg.org/legal.html).

소스 저장소에는 FFmpeg 바이너리가 없습니다. Docker 이미지는 Debian의 FFmpeg 패키지를 설치하므로 프로젝트의 MIT 라이선스와 별개로 해당 패키지의 고지와 재배포 조건이 적용됩니다. 패키지 고지는 이미지의 `/usr/share/doc/ffmpeg/copyright`에서 확인할 수 있습니다. 이 문서는 전체 전이 의존성의 라이선스 목록을 대신하지 않습니다.
