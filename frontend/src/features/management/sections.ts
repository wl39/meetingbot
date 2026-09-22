import {
  AudioLines,
  Download,
  Layers3,
  Settings2,
  Sparkles,
} from "lucide-react";

export const sections = [
  {
    path: "/settings/access",
    label: "접속 및 권한",
    description: "방문자·관리자 접속 키",
    Icon: Settings2,
  },
  {
    path: "/settings",
    label: "관리 홈",
    description: "설치 상태와 화면 설정",
    Icon: Settings2,
  },
  {
    path: "/settings/speech",
    label: "음성 인식",
    description: "STT 엔진과 모델",
    Icon: AudioLines,
  },
  {
    path: "/settings/rag",
    label: "자료 검색",
    description: "청킹과 검색 범위",
    Icon: Layers3,
  },
  {
    path: "/settings/ai",
    label: "AI 모델",
    description: "모델 연결과 답변 설정",
    Icon: Sparkles,
  },
  {
    path: "/settings/updates",
    label: "설치 및 업데이트",
    description: "운영 환경과 설치 기록",
    Icon: Download,
  },
] as const;
