type SkinTestProgressProps = {
  current: number;
  onBack: () => void;
  total: number;
};

function SkinTestProgress({ current, onBack, total }: SkinTestProgressProps) {
  const progress = total > 0 ? Math.round((current / total) * 100) : 0;

  return (
    <div className="skin-test-progress">
      <button
        aria-label={current === 1 ? "피부 타입 테스트 닫기" : "이전 문항으로 이동"}
        className="skin-test-back-button"
        onClick={onBack}
        type="button"
      >
        <span aria-hidden="true">‹</span>
      </button>
      <div
        className="skin-test-progress__track"
        aria-label={`피부 타입 테스트 진행률 ${current} / ${total}`}
        role="progressbar"
        aria-valuemax={total}
        aria-valuemin={1}
        aria-valuenow={current}
      >
        <div className="skin-test-progress__bar" style={{ width: `${progress}%` }} />
      </div>
      <span className="skin-test-progress__count">
        {current} / {total}
      </span>
    </div>
  );
}

export default SkinTestProgress;
