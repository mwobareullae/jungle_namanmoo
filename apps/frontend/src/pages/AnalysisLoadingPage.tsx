import { useElapsedSeconds } from "../hooks/useElapsedSeconds";
import type { RecommendationRequest } from "../types/recommendation";

const loadingSteps = ["피부 타입 확인", "고민 키워드 해석", "효능 후보 정리", "성분 근거 매칭"];

type AnalysisLoadingPageProps = {
  request: RecommendationRequest;
  isLoading: boolean;
  errorMessage: string | null;
  onRetry: () => void;
  onEdit: () => void;
};

function AnalysisLoadingPage({
  request,
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
      <p className="eyebrow loading-eyebrow">Analyzing</p>
      <h1 className="loading-title">성분 근거를 맞춰보고 있어요</h1>
      <p className="loading-query">“{request.concern_text}”</p>

      <div className="steps">
        {loadingSteps.map((step, index) => {
          const state =
            index < activeStepIndex ? "done" : index === activeStepIndex ? "active" : "";
          return (
            <div className={`step ${state}`} key={step}>
              <span className="dot" aria-hidden="true" />
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
