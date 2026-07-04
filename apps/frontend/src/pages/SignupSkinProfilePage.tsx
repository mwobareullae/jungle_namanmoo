import { useState } from "react";
import { useNavigate } from "react-router-dom";
import AuthHeader from "../components/AuthHeader";
import SignupProgress from "../components/SignupProgress";
import { avoidIngredientCategories } from "../constants/avoidIngredientCategories";

type SkinProfileForm = {
  skinType: string;
  sensitivity: string;
  concerns: string[];
  avoidIngredients: string[];
};

const skinTypeOptions = [
  { id: "dry", label: "건성" },
  { id: "oily", label: "지성" },
  { id: "combination", label: "복합성" },
  { id: "dehydrated_oily", label: "수부지" },
  { id: "normal", label: "중성" }
];

const sensitivityOptions = [
  { id: "low", label: "낮음" },
  { id: "normal", label: "보통" },
  { id: "high", label: "높음" }
];

const concernOptions = [
  { id: "concern_acne", label: "여드름" },
  { id: "concern_brightening_spots", label: "미백" },
  { id: "concern_pore", label: "모공" },
  { id: "concern_sebum_oil", label: "피지/유분" },
  { id: "concern_dry_barrier", label: "속건조" },
  { id: "concern_wrinkle", label: "주름" },
  { id: "concern_elasticity", label: "탄력" },
  { id: "concern_redness_irritation", label: "홍조" },
  { id: "concern_dead_skin_texture", label: "각질" },
  { id: "concern_blemish_mark", label: "흔적 관리" },
  { id: "concern_skin_tone", label: "피부톤" },
  { id: "concern_dark_circle", label: "다크서클" },
  { id: "none", label: "해당없음" }
];

const avoidIngredientOptions = avoidIngredientCategories.map(({ id, label }) => ({ id, label }));

function SignupSkinProfilePage() {
  const navigate = useNavigate();
  const [form, setForm] = useState<SkinProfileForm>({
    skinType: "",
    sensitivity: "",
    concerns: [],
    avoidIngredients: []
  });
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [errorMessage, setErrorMessage] = useState("");
  const canSubmit =
    form.skinType !== "" &&
    form.sensitivity !== "" &&
    form.concerns.length > 0 &&
    form.avoidIngredients.length > 0;

  const handleSingleSelect = (key: "skinType" | "sensitivity", value: string) => {
    setForm((prev) => ({
      ...prev,
      [key]: value
    }));
  };

  const handleMultiSelect = (key: "concerns" | "avoidIngredients", value: string) => {
    setForm((prev) => {
      const currentValues = prev[key];

      if (value === "none") {
        return {
          ...prev,
          [key]: currentValues.includes("none") ? [] : ["none"]
        };
      }

      const valuesWithoutNone = currentValues.filter((item) => item !== "none");

      return {
        ...prev,
        [key]: valuesWithoutNone.includes(value)
          ? valuesWithoutNone.filter((item) => item !== value)
          : [...valuesWithoutNone, value]
      };
    });
  };

  const handleSubmit = async () => {
    if (!canSubmit || isSubmitting) {
      return;
    }

    setIsSubmitting(true);
    setErrorMessage("");

    try {
      const response = await fetch("http://localhost:8000/api/skin-profile", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(form)
      });

      if (!response.ok) {
        setErrorMessage("피부 타입 저장에 실패했습니다. 다시 시도해주세요.");
        return;
      }

      navigate("/", { replace: true });
    } catch {
      setErrorMessage("피부 타입 저장에 실패했습니다. 다시 시도해주세요.");
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <div className="flex min-h-screen flex-col bg-[#FAFAFA] font-['Pretendard_Variable','Pretendard','Noto_Sans_KR',system-ui,sans-serif] text-[#1A1A1A]">
      <AuthHeader />
      <main className="flex flex-1 items-center justify-center px-5 py-10">
        <div className="w-full max-w-[680px] rounded-[20px] border border-[rgba(0,0,0,0.07)] bg-white px-6 py-8 shadow-[0_2px_24px_rgba(0,0,0,0.06)] sm:px-9 sm:py-10">
          <div className="mb-7">
            <SignupProgress currentStep={3} />
            <h1 className="text-[28px] font-semibold leading-[1.25] text-[#1A1A1A]">
              피부 타입 선택
            </h1>
            <p className="mt-3 text-[14px] leading-[1.6] font-medium text-[#6B7280]">
              맞춤 추천을 위해 피부 타입과 관심 정보를 선택해주세요.
            </p>
          </div>
          <form className="grid gap-7">
            <section>
              <h2 className="text-[15px] font-semibold text-[#1A1A1A]">피부 타입</h2>
              <div className="mt-3 grid grid-cols-2 gap-2 sm:grid-cols-5">
                {skinTypeOptions.map((option) => {
                  const isSelected = form.skinType === option.id;

                  return (
                    <button
                      className={`min-h-11 rounded-[14px] border px-3 py-2 text-[14px] font-semibold ${
                        isSelected
                          ? "border-[#0096C6] bg-[rgba(0,150,198,0.12)] text-[#005F7E]"
                          : "border-[rgba(0,0,0,0.07)] bg-white text-[#3D3D3D]"
                      }`}
                      key={option.id}
                      onClick={() => handleSingleSelect("skinType", option.id)}
                      type="button"
                    >
                      {option.label}
                    </button>
                  );
                })}
              </div>
            </section>

            <section>
              <h2 className="text-[15px] font-semibold text-[#1A1A1A]">민감도</h2>
              <div className="mt-3 grid grid-cols-3 gap-2">
                {sensitivityOptions.map((option) => {
                  const isSelected = form.sensitivity === option.id;

                  return (
                    <button
                      className={`min-h-11 rounded-[14px] border px-3 py-2 text-[14px] font-semibold ${
                        isSelected
                          ? "border-[#0096C6] bg-[rgba(0,150,198,0.12)] text-[#005F7E]"
                          : "border-[rgba(0,0,0,0.07)] bg-white text-[#3D3D3D]"
                      }`}
                      key={option.id}
                      onClick={() => handleSingleSelect("sensitivity", option.id)}
                      type="button"
                    >
                      {option.label}
                    </button>
                  );
                })}
              </div>
            </section>

            <section>
              <h2 className="text-[15px] font-semibold text-[#1A1A1A]">피부 고민</h2>
              <div className="mt-3 flex flex-wrap gap-2">
                {concernOptions.map((option) => {
                  const isSelected = form.concerns.includes(option.id);

                  return (
                    <button
                      className={`min-h-10 rounded-[14px] border px-3.5 py-2 text-[13px] font-semibold ${
                        isSelected
                          ? "border-[#0096C6] bg-[rgba(0,150,198,0.12)] text-[#005F7E]"
                          : "border-[rgba(0,0,0,0.07)] bg-white text-[#3D3D3D]"
                      }`}
                      key={option.id}
                      onClick={() => handleMultiSelect("concerns", option.id)}
                      type="button"
                    >
                      {option.label}
                    </button>
                  );
                })}
              </div>
            </section>

            <section>
              <h2 className="text-[15px] font-semibold text-[#1A1A1A]">
                피하고 싶은 성분
              </h2>
              <div className="mt-3 flex flex-wrap gap-2">
                {avoidIngredientOptions.map((option) => {
                  const isSelected = form.avoidIngredients.includes(option.id);

                  return (
                    <button
                      className={`min-h-10 rounded-[14px] border px-3.5 py-2 text-[13px] font-semibold ${
                        isSelected
                          ? "border-[#0096C6] bg-[rgba(0,150,198,0.12)] text-[#005F7E]"
                          : "border-[rgba(0,0,0,0.07)] bg-white text-[#3D3D3D]"
                      }`}
                      key={option.id}
                      onClick={() => handleMultiSelect("avoidIngredients", option.id)}
                      type="button"
                    >
                      {option.label}
                    </button>
                  );
                })}
              </div>
            </section>

            <div className="mt-1 grid grid-cols-2 gap-2">
              <button
                className="rounded-[14px] border border-[rgba(0,0,0,0.07)] bg-white py-3.5 text-[15px] font-semibold text-[#3D3D3D] hover:bg-[#FAFAFA]"
                onClick={() => navigate("/", { replace: true })}
                type="button"
              >
                건너뛰기
              </button>
              <button
                className={`rounded-[14px] border-0 bg-[#111820] py-3.5 text-[15px] font-semibold text-white ${
                  canSubmit && !isSubmitting ? "cursor-pointer opacity-100" : "cursor-not-allowed opacity-50"
                }`}
                disabled={!canSubmit || isSubmitting}
                onClick={handleSubmit}
                type="button"
              >
                완료
              </button>
            </div>
            {errorMessage && (
              <p className="text-center text-[13px] font-medium text-[#ff2b2b]">
                {errorMessage}
              </p>
            )}
          </form>
        </div>
      </main>
    </div>
  );
}

export default SignupSkinProfilePage;
