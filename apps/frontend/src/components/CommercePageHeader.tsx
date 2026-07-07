type CommerceStep = "cart" | "checkout" | "complete";

type CommercePageHeaderProps = {
  title: string;
  description?: string;
  currentStep: CommerceStep;
};

const steps: Array<{ key: CommerceStep; label: string }> = [
  { key: "cart", label: "장바구니" },
  { key: "checkout", label: "주문서" },
  { key: "complete", label: "결제완료" },
];

function CommercePageHeader({ title, description, currentStep }: CommercePageHeaderProps) {
  const currentStepIndex = steps.findIndex((step) => step.key === currentStep);

  return (
    <div className="commerce-page-header">
      <div>
        <h1>{title}</h1>
        {description ? <p>{description}</p> : null}
      </div>
      <div className="commerce-page-steps" aria-label="구매 진행 단계">
        {steps.map((step, index) => {
          const isCompleted = index < currentStepIndex;
          const isCurrent = index === currentStepIndex;
          const stepState = isCompleted ? " completed" : isCurrent ? " current" : "";

          return (
            <span className="commerce-page-step-group" key={step.key}>
              <span className={`commerce-page-step${stepState}`}>
                <span className="commerce-page-step-marker" aria-hidden="true">
                  {isCompleted ? "✓" : String(index + 1).padStart(2, "0")}
                </span>
                <span className="commerce-page-step-label">{step.label}</span>
              </span>
              {index < steps.length - 1 ? <span className="commerce-page-step-line" aria-hidden="true" /> : null}
            </span>
          );
        })}
      </div>
    </div>
  );
}

export default CommercePageHeader;
