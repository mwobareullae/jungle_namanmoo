type SignupProgressProps = {
  currentStep: 1 | 2 | 3;
};

const signupSteps = ["약관 동의", "회원 정보", "피부 타입 [선택]"];

function SignupProgress({ currentStep }: SignupProgressProps) {
  return (
    <div aria-label="회원가입 진행 단계" className="mb-7">
      <div className="grid grid-cols-3 text-center text-[12px] font-semibold text-[#9CA3AF]">
        {signupSteps.map((step, index) => {
          const stepNumber = index + 1;
          const isActive = stepNumber <= currentStep;

          return (
            <span className={isActive ? "text-[#0096C6]" : "text-[#9CA3AF]"} key={step}>
              {step}
            </span>
          );
        })}
      </div>
      <div className="mt-3 grid grid-cols-3 items-center">
        {signupSteps.map((step, index) => {
          const stepNumber = index + 1;
          const isActive = stepNumber <= currentStep;
          const isConnectorActive = stepNumber < currentStep;

          return (
            <div className="relative flex justify-center" key={step}>
              {index < signupSteps.length - 1 && (
                <span
                  aria-hidden="true"
                  className={`absolute top-1/2 left-[calc(50%+8px)] right-[calc(-50%+8px)] h-px -translate-y-1/2 ${
                    isConnectorActive ? "bg-[#0096C6]" : "bg-[#D1D5DB]"
                  }`}
                />
              )}
              <span
                aria-hidden="true"
                className={`relative z-10 h-4 w-4 rounded-full border-2 ${
                  isActive ? "border-[#0096C6] bg-[#0096C6]" : "border-[#D1D5DB] bg-white"
                }`}
              />
            </div>
          );
        })}
      </div>
    </div>
  );
}

export default SignupProgress;
