import type { FormEvent } from "react";
import type { RecommendationRequest, Sensitivity, SkinType } from "../types/recommendation";

const skinTypes: SkinType[] = ["건성", "지성", "복합성", "수부지", "중성"];
const sensitivities: Sensitivity[] = ["낮음", "보통", "높음"];

type ConcernInputPageProps = {
  value: RecommendationRequest;
  isSubmitting: boolean;
  errorMessage: string | null;
  onChange: (nextValue: RecommendationRequest) => void;
  onSubmit: () => void;
};

function ConcernInputPage({
  value,
  isSubmitting,
  errorMessage,
  onChange,
  onSubmit
}: ConcernInputPageProps) {
  const trimmedConcern = value.concern_text.trim();
  const isDisabled = isSubmitting || trimmedConcern.length === 0;

  const handleSubmit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!isDisabled) {
      onSubmit();
    }
  };

  return (
    <section className="search-hero" aria-labelledby="hero-title">
      <p className="eyebrow">Evidence-led skincare</p>
      <h1 id="hero-title" className="serif hero-title">
        피부 고민을 쓰면 <br />
        성분 근거로 고릅니다
      </h1>
      <p className="hero-copy">
        피부 타입과 민감도를 함께 보고, MVP 점수 정책에 맞춰 성분 효능 근거 중심으로 추천합니다.
      </p>

      <form className="concern-form" onSubmit={handleSubmit}>
        <fieldset className="choice-group">
          <legend className="field-label">피부 타입</legend>
          <div className="segmented-control">
            {skinTypes.map((skinType) => (
              <button
                className={value.skin_type === skinType ? "segment selected" : "segment"}
                key={skinType}
                type="button"
                onClick={() => onChange({ ...value, skin_type: skinType })}
              >
                {skinType}
              </button>
            ))}
          </div>
        </fieldset>

        <fieldset className="choice-group">
          <legend className="field-label">민감도</legend>
          <div className="segmented-control compact">
            {sensitivities.map((sensitivity) => (
              <button
                className={value.sensitivity === sensitivity ? "segment selected" : "segment"}
                key={sensitivity}
                type="button"
                onClick={() => onChange({ ...value, sensitivity })}
              >
                {sensitivity}
              </button>
            ))}
          </div>
        </fieldset>

        <div className="field-stack">
          <label className="field-label" htmlFor="concern">
            피부 고민
          </label>
          <textarea
            id="concern"
            className="concern-textarea"
            maxLength={100}
            placeholder="수부지인데 모공 넓고 좁쌀 여드름이 있어요"
            value={value.concern_text}
            onChange={(event) => onChange({ ...value, concern_text: event.target.value })}
          />
          <div className="form-meta">
            <span>
              {trimmedConcern.length === 0
                ? "공백만 입력하면 추천을 시작할 수 없어요."
                : "입력값은 분석 중에도 보존됩니다."}
            </span>
            <span>{value.concern_text.length}/100</span>
          </div>
        </div>

        {errorMessage ? <p className="form-error">{errorMessage}</p> : null}

        <button className="primary-button wide" type="submit" disabled={isDisabled}>
          {isSubmitting ? "분석 준비 중" : "추천 시작"}
        </button>
      </form>
    </section>
  );
}

export default ConcernInputPage;
