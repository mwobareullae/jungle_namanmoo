type CommerceStep = "cart" | "checkout" | "complete";

type CommercePageHeaderProps = {
  title: string;
  description: string;
  currentStep: CommerceStep;
};

const steps: Array<{ key: CommerceStep; label: string }> = [
  { key: "cart", label: "장바구니" },
  { key: "checkout", label: "주문서" },
  { key: "complete", label: "결제완료" },
];

function CommercePageHeader({ title, description, currentStep }: CommercePageHeaderProps) {
  return (
    <div className="commerce-page-header">
      <div>
        <h1>{title}</h1>
        <p>{description}</p>
      </div>
      <div className="commerce-page-steps" aria-label="구매 진행 단계">
        {steps.map((step, index) => (
          <span className="commerce-page-step-group" key={step.key}>
            {step.key === currentStep ? <strong>{step.label}</strong> : <span>{step.label}</span>}
            {index < steps.length - 1 ? <span aria-hidden="true">›</span> : null}
          </span>
        ))}
      </div>
    </div>
  );
}

export default CommercePageHeader;
