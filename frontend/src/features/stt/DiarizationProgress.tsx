export function DiarizationProgress() {
  return (
    <div className="diarization-progress" role="status">
      <div className="diarization-progress-heading">
        <strong>누가 말했는지 정리하고 있습니다</strong>
      </div>
      <progress aria-label="발언자 정리 중" />
      <p>먼저 완성된 대본을 아래에서 확인할 수 있습니다.</p>
    </div>
  );
}
