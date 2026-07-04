import type { SkinTestOption, SkinTestQuestion } from "../types/skinTest";

type SkinTestQuestionCardProps = {
  question: SkinTestQuestion;
  selectedOptionId: SkinTestOption["id"] | null;
  onSelect: (optionId: SkinTestOption["id"]) => void;
};

function SkinTestQuestionCard({ question, selectedOptionId, onSelect }: SkinTestQuestionCardProps) {
  return (
    <section className="skin-test-question" aria-labelledby={`skin-test-question-${question.id}`}>
      <h2 className="skin-test-question__title" id={`skin-test-question-${question.id}`}>
        {question.text}
      </h2>
      <div className="skin-test-options" role="radiogroup" aria-label={question.text}>
        {question.options.map((option, index) => {
          const isSelected = String(option.id) === String(selectedOptionId);

          return (
            <button
              aria-checked={isSelected}
              className={`skin-test-option${isSelected ? " is-selected" : ""}`}
              key={option.id}
              onClick={() => onSelect(option.id)}
              role="radio"
              type="button"
            >
              <span className="skin-test-option__index">{index + 1}</span>
              <span>{option.text}</span>
            </button>
          );
        })}
      </div>
    </section>
  );
}

export default SkinTestQuestionCard;
