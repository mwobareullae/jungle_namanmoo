import { useCallback, useEffect, useId, useState } from "react";
import { useNavigate } from "react-router-dom";
import { dismissSkinTestPromptForSevenDays } from "../lib/skinTestPrompt";

type SkinTestPromptModalProps = {
  onClose: () => void;
};

const answers = [
  "당기고 건조해요",
  "괜찮다가 시간 지나면 당겨요",
  "번들거리고 유분기 있어요",
  "부위별로 달라요 (T존 번들, 볼 당김)"
];

function SkinTestPromptModal({ onClose }: SkinTestPromptModalProps) {
  const navigate = useNavigate();
  const titleId = useId();
  const questionId = useId();
  const [selectedAnswerIndex, setSelectedAnswerIndex] = useState<number | null>(null);
  const [hideForSevenDays, setHideForSevenDays] = useState(false);

  const rememberPreference = useCallback(() => {
    if (hideForSevenDays) {
      dismissSkinTestPromptForSevenDays();
    }
  }, [hideForSevenDays]);

  const handleClose = useCallback(() => {
    rememberPreference();
    onClose();
  }, [onClose, rememberPreference]);

  const handleStart = () => {
    rememberPreference();
    onClose();
    navigate("/skin-test");
  };

  useEffect(() => {
    const previousBodyOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";

    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        handleClose();
      }
    };

    document.addEventListener("keydown", handleKeyDown);

    return () => {
      document.body.style.overflow = previousBodyOverflow;
      document.removeEventListener("keydown", handleKeyDown);
    };
  }, [handleClose]);

  return (
    <div className="skin-test-prompt" role="presentation">
      <button
        aria-label="피부 테스트 알림 닫기"
        className="skin-test-prompt__backdrop"
        onClick={handleClose}
        type="button"
      />
      <section
        aria-labelledby={titleId}
        aria-modal="true"
        className="skin-test-prompt__dialog"
        role="dialog"
      >
        <button
          aria-label="피부 테스트 알림 닫기"
          className="skin-test-prompt__close"
          onClick={handleClose}
          type="button"
        >
          <svg
            aria-hidden="true"
            fill="none"
            height="18"
            stroke="currentColor"
            strokeLinecap="round"
            strokeWidth="2"
            viewBox="0 0 24 24"
            width="18"
          >
            <path d="M6 6l12 12M18 6 6 18" />
          </svg>
        </button>

        <span className="skin-test-prompt__badge">잠깐 테스트!</span>
        <p className="skin-test-prompt__intro">내 피부, 정확히 알고 계세요?</p>
        <h2 className="skin-test-prompt__title" id={titleId}>
          8초 피부 테스트로 타입 확인하기
        </h2>

        <div className="skin-test-prompt__question" id={questionId}>
          <span aria-hidden="true" className="skin-test-prompt__question-dot" />
          세안 후 아무것도 안 바르면 내 피부는?
        </div>
        <div
          aria-labelledby={questionId}
          className="skin-test-prompt__options"
          role="radiogroup"
        >
          {answers.map((answer, index) => {
            const isSelected = selectedAnswerIndex === index;

            return (
              <button
                aria-checked={isSelected}
                className={`skin-test-prompt__option${isSelected ? " is-selected" : ""}`}
                key={answer}
                onClick={() => setSelectedAnswerIndex(index)}
                role="radio"
                type="button"
              >
                <span className="skin-test-prompt__radio" />
                <span>{answer}</span>
              </button>
            );
          })}
        </div>

        <button className="skin-test-prompt__cta" onClick={handleStart} type="button">
          <span>테스트 시작하고 내 피부 타입 확인하기</span>
          <svg
            aria-hidden="true"
            fill="none"
            height="18"
            stroke="currentColor"
            strokeLinecap="round"
            strokeLinejoin="round"
            strokeWidth="2.2"
            viewBox="0 0 24 24"
            width="18"
          >
            <path d="M5 12h14M13 6l6 6-6 6" />
          </svg>
        </button>

        <label className="skin-test-prompt__dismiss">
          <input
            checked={hideForSevenDays}
            className="skin-test-prompt__dismiss-input"
            onChange={(event) => setHideForSevenDays(event.target.checked)}
            type="checkbox"
          />
          <span className="skin-test-prompt__checkbox" aria-hidden="true">
            {hideForSevenDays ? (
              <svg
                fill="none"
                height="11"
                stroke="currentColor"
                strokeLinecap="round"
                strokeLinejoin="round"
                strokeWidth="3.5"
                viewBox="0 0 24 24"
                width="11"
              >
                <path d="M4 12l6 6L20 6" />
              </svg>
            ) : null}
          </span>
          <span>7일 동안 보지 않기</span>
        </label>
      </section>
    </div>
  );
}

export default SkinTestPromptModal;
