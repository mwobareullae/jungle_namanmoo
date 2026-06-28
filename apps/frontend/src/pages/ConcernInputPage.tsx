import { useEffect, useMemo, useRef, useState, type FormEvent } from "react";
import type { RecommendationRequest, Sensitivity, SkinType } from "../types/recommendation";

const skinTypes: SkinType[] = ["건성", "지성", "복합성", "수부지", "중성"];
const sensitivities: Sensitivity[] = ["낮음", "보통", "높음"];
const concernTextMaxLength = 100;
const suggestionLengthLimit = 18;
const suggestionDelayMs = 2000;
const concernLimitToastMs = 2400;

const sensitivityLabel: Record<Sensitivity, string> = {
  낮음: "자극은 크게 없지만",
  보통: "가끔 예민해지는데",
  높음: "쉽게 붉어지고 따가워서"
};

const skinConcernHint: Record<SkinType, string> = {
  건성: "세안 후 당김과 속건조가 오래가요",
  지성: "오후가 되면 유분이 올라오고 모공이 도드라져 보여요",
  복합성: "T존은 번들거리고 볼은 건조해서 균형 잡기가 어려워요",
  수부지: "겉은 번들거리는데 속은 당기고 좁쌀이 올라와요",
  중성: "컨디션에 따라 칙칙함과 가벼운 건조가 번갈아 보여요"
};

const buildConcernPlaceholder = (skinType: SkinType, sensitivity: Sensitivity) =>
  `${skinType}이고 ${sensitivityLabel[sensitivity]} ${skinConcernHint[skinType]}.`;

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
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const suggestionTimerRef = useRef<number | null>(null);
  const limitToastTimerRef = useRef<number | null>(null);
  const [showConcernSuggestions, setShowConcernSuggestions] = useState(false);
  const [showConcernLimitToast, setShowConcernLimitToast] = useState(false);
  const [isConcernLimitShaking, setIsConcernLimitShaking] = useState(false);
  const trimmedConcern = value.concern_text.trim();
  const isDisabled = isSubmitting || trimmedConcern.length === 0;
  const concernPlaceholder = useMemo(
    () => buildConcernPlaceholder(value.skin_type, value.sensitivity),
    [value.sensitivity, value.skin_type]
  );
  const concernSuggestions = useMemo(
    () => [
      `${value.skin_type}이고 민감도는 ${value.sensitivity}인데 속건조와 붉은기가 같이 고민이에요.`,
      `${value.skin_type} 피부인데 오후에 유분이 올라오고 모공이 더 넓어 보여요.`,
      `${value.skin_type}이고 민감도 ${value.sensitivity}라 자극 적은 진정 보습 제품을 찾고 있어요.`
    ],
    [value.sensitivity, value.skin_type]
  );

  const clearSuggestionTimer = () => {
    if (suggestionTimerRef.current === null) {
      return;
    }

    window.clearTimeout(suggestionTimerRef.current);
    suggestionTimerRef.current = null;
  };

  const clearLimitToastTimer = () => {
    if (limitToastTimerRef.current === null) {
      return;
    }

    window.clearTimeout(limitToastTimerRef.current);
    limitToastTimerRef.current = null;
  };

  const queueConcernSuggestions = (nextConcernText: string) => {
    clearSuggestionTimer();

    if (nextConcernText.trim().length > suggestionLengthLimit) {
      setShowConcernSuggestions(false);
      return;
    }

    suggestionTimerRef.current = window.setTimeout(() => {
      setShowConcernSuggestions(true);
    }, suggestionDelayMs);
  };

  const notifyConcernLimit = () => {
    setIsConcernLimitShaking(true);
    setShowConcernLimitToast(true);
    clearLimitToastTimer();

    limitToastTimerRef.current = window.setTimeout(() => {
      setShowConcernLimitToast(false);
      limitToastTimerRef.current = null;
    }, concernLimitToastMs);
  };

  useEffect(
    () => () => {
      clearSuggestionTimer();
      clearLimitToastTimer();
    },
    []
  );

  const handleSubmit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!isDisabled) {
      onSubmit();
    }
  };

  const handleConcernChange = (nextConcernText: string) => {
    setShowConcernSuggestions(false);
    queueConcernSuggestions(nextConcernText);

    if (
      nextConcernText.length >= concernTextMaxLength &&
      value.concern_text.length < concernTextMaxLength
    ) {
      notifyConcernLimit();
    }

    onChange({ ...value, concern_text: nextConcernText });
  };

  const handleSuggestionClick = (suggestion: string) => {
    clearSuggestionTimer();
    setShowConcernSuggestions(false);
    onChange({ ...value, concern_text: suggestion });
    window.requestAnimationFrame(() => textareaRef.current?.focus());
  };

  return (
    <section className="search-hero" aria-labelledby="hero-title">
      <p className="eyebrow hero-eyebrow">Tell us about your skin</p>
      <h1 id="hero-title" className="hero-title">
        어떤 피부 고민이 있으신가요?
      </h1>
      <p className="hero-copy">한 문장으로 편하게 적어주세요. 성분으로 답을 찾아드릴게요.</p>

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
            ref={textareaRef}
            id="concern"
            className={
              isConcernLimitShaking ? "concern-textarea concern-textarea-shake" : "concern-textarea"
            }
            autoFocus
            maxLength={concernTextMaxLength}
            placeholder={concernPlaceholder}
            value={value.concern_text}
            onChange={(event) => handleConcernChange(event.target.value)}
            onFocus={() => queueConcernSuggestions(value.concern_text)}
            onAnimationEnd={() => setIsConcernLimitShaking(false)}
          />
          <div className="form-meta">
            <span className={trimmedConcern.length === 0 ? "form-meta-danger" : undefined}>
              {trimmedConcern.length === 0 ? "공백만 입력하면 추천을 시작할 수 없어요." : ""}
            </span>
            <span>
              {value.concern_text.length}/{concernTextMaxLength}
            </span>
          </div>

          <div
            className={showConcernSuggestions ? "suggestion-panel visible" : "suggestion-panel"}
            aria-hidden={!showConcernSuggestions}
            aria-label="피부 고민 예시"
          >
            <p className="suggestion-title">이런 고민은 어때요?</p>
            <div className="suggestion-chips">
              {concernSuggestions.map((suggestion) => (
                <button
                  className="suggestion-chip"
                  key={suggestion}
                  type="button"
                  tabIndex={showConcernSuggestions ? 0 : -1}
                  onClick={() => handleSuggestionClick(suggestion)}
                >
                  {suggestion}
                </button>
              ))}
            </div>
          </div>
        </div>

        {errorMessage ? <p className="form-error">{errorMessage}</p> : null}

        <button className="primary-button wide" type="submit" disabled={isDisabled}>
          {isSubmitting ? "분석 준비 중" : "추천 시작"}
        </button>
      </form>

      {showConcernLimitToast ? (
        <div className="limit-toast" role="status" aria-live="polite">
          피부 고민은 100자까지 입력할 수 있어요.
        </div>
      ) : null}
    </section>
  );
}

export default ConcernInputPage;
