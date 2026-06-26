import { useElapsedSeconds } from "../hooks/useElapsedSeconds";
import type { RecommendationRequest } from "../types/recommendation";

const loadingSteps = ["피부타입 분석", "피부 고민 파악", "성분 매칭", "근거 검증"];

type AnalysisLoadingPageProps = {
  request: RecommendationRequest;
  isLoading: boolean;
  errorMessage: string | null;
  onRetry: () => void;
  onEdit: () => void;
};

function AnalysisLoadingPage({
  isLoading,
  errorMessage,
  onRetry,
  onEdit
}: AnalysisLoadingPageProps) {
  const elapsedSeconds = useElapsedSeconds(isLoading);
  const activeStepIndex = Math.min(Math.floor(elapsedSeconds / 1.2), loadingSteps.length - 1);

  return (
    <section className="loading-page" aria-live="polite">
      <div className="ring" aria-hidden="true" />
      <p className="loading-status">AI가 분석하고 있어요</p>

      <div className="steps">
        {loadingSteps.map((step, index) => {
          const state =
            index < activeStepIndex ? "done" : index === activeStepIndex ? "active" : "";
          return (
            <div className={`step ${state}`} key={step}>
              <span className="step-marker" aria-hidden="true">
                {state === "done" ? "✓" : null}
              </span>
              <span>{step}</span>
            </div>
          );
        })}
      </div>

      {elapsedSeconds >= 15 && !errorMessage ? (
        <p className="delay-notice">
          15초 이상 지연되고 있어요. 잠시 후에도 멈춰 있으면 다시 시도해주세요.
        </p>
      ) : null}

      {errorMessage ? (
        <div className="retry-panel">
          <p>{errorMessage}</p>
          <div className="inline-actions">
            <button className="primary-button" type="button" onClick={onRetry}>
              재시도
            </button>
            <button className="secondary-button" type="button" onClick={onEdit}>
              입력 수정
            </button>
          </div>
        </div>
      ) : null}
    </section>
  );
}

export default AnalysisLoadingPage;
