import { useEffect, useRef } from "react";
import { RadioGroup, RadioGroupItem } from "./ui/radio-group";
import type { SkinTestOption, SkinTestQuestion } from "../types/skinTest";

type SkinTestQuestionCardProps = {
  question: SkinTestQuestion;
  selectedOptionId: SkinTestOption["id"] | null;
  onSelect: (optionId: SkinTestOption["id"], commit: boolean) => void;
  onConfirm: (optionId: SkinTestOption["id"] | null) => void;
};

function SkinTestQuestionCard({ question, selectedOptionId, onSelect, onConfirm }: SkinTestQuestionCardProps) {
  const groupRef = useRef<HTMLDivElement>(null);
  // Radix RadioGroup은 화살표로 포커스 이동 시 내부적으로 해당 항목을 자동 클릭하려고 시도하지만,
  // 실제로는 타이밍에 따라 안 먹을 때가 많다(document 리스너가 포커스 이동보다 늦게 잡힘).
  // 그래서 클릭 여부와 무관하게 "지금 포커스가 어느 항목에 있는지"를 별도로 직접 추적한다 — Enter로
  // 확정할 때는 이 값을 쓴다.
  const focusedOptionIdRef = useRef<SkinTestOption["id"] | null>(null);
  // 실제 사용자 클릭(isTrusted: true)과 Radix가 코드로 만든 클릭(isTrusted: false)을 구분해서,
  // 화살표 탐색 중 우연히 클릭이 걸리더라도 자동 진행은 하지 않는다.
  const isTrustedClickRef = useRef(true);

  // 질문이 바뀔 때마다 이 컴포넌트가 통째로 다시 마운트되면서(SkinTestPage의 key={currentQuestion.id})
  // 포커스가 매번 사라진다. 포커스 없이 화살표 키를 누르면 브라우저가 페이지 스크롤로 처리해버리므로,
  // 마운트 시 선택된 항목(없으면 첫 번째 항목)에 포커스를 되돌려준다.
  useEffect(() => {
    const container = groupRef.current;
    if (!container) {
      return;
    }

    const items = container.querySelectorAll<HTMLElement>('[role="radio"]');
    const checkedItem = container.querySelector<HTMLElement>('[role="radio"][aria-checked="true"]');
    (checkedItem ?? items[0])?.focus({ preventScroll: true });
    focusedOptionIdRef.current = selectedOptionId ?? question.options[0]?.id ?? null;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <section className="skin-test-question" aria-labelledby={`skin-test-question-${question.id}`}>
      <p className="skin-test-question__eyebrow">맞춤 추천 테스트</p>
      <h2 className="skin-test-question__title" id={`skin-test-question-${question.id}`}>
        {question.text}
      </h2>
      <RadioGroup
        aria-label={question.text}
        className="skin-test-options"
        onKeyDown={(event) => {
          if (event.key === "Enter") {
            onConfirm(focusedOptionIdRef.current);
          }
        }}
        onValueChange={(value) => {
          const option = question.options.find((candidate) => String(candidate.id) === value);
          if (option) {
            onSelect(option.id, isTrustedClickRef.current);
          }
        }}
        ref={groupRef}
        value={selectedOptionId !== null ? String(selectedOptionId) : ""}
      >
        {question.options.map((option, index) => {
          const isSelected = String(option.id) === String(selectedOptionId);

          return (
            <RadioGroupItem
              className={`skin-test-option${isSelected ? " is-selected" : ""}`}
              key={option.id}
              onClick={(event) => {
                isTrustedClickRef.current = event.isTrusted;
              }}
              onFocus={() => {
                focusedOptionIdRef.current = option.id;
              }}
              value={String(option.id)}
            >
              <span className="skin-test-option__number" aria-hidden="true">
                {index + 1}
              </span>
              <span className="skin-test-option__text">{option.text}</span>
              <span className="skin-test-option__spacer" aria-hidden="true">
                {index + 1}
              </span>
            </RadioGroupItem>
          );
        })}
      </RadioGroup>
    </section>
  );
}

export default SkinTestQuestionCard;
