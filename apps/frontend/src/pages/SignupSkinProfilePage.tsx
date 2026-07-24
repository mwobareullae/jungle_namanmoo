import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { useQueryClient } from "@tanstack/react-query";
import HomeHeader from "../components/HomeHeader";
import SignupProgress from "../components/SignupProgress";
import { Button } from "../components/ui/button";
import { ToggleGroup, ToggleGroupItem } from "../components/ui/toggle-group";
import { avoidIngredientCategories } from "../constants/avoidIngredientCategories";
import { useAuth } from "../contexts/useAuth";
import { skinProfileQueryKey } from "../hooks/useSkinProfileQuery";
import { createSignupSkinProfile, setMySkinProfileCache } from "../lib/profileApi";

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
const getAvoidIngredientLabels = (ids: string[]) =>
  ids.map((id) => avoidIngredientOptions.find((option) => option.id === id)?.label ?? id);

function SignupSkinProfilePage() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const { refreshAuthenticatedUser, user } = useAuth();
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
      const signupSkinProfilePayload = {
        ...form,
        avoidIngredients: getAvoidIngredientLabels(form.avoidIngredients)
      };

      const savedProfile = await createSignupSkinProfile(signupSkinProfilePayload);
      if (!savedProfile) {
        setErrorMessage("피부 타입 저장에 실패했습니다. 다시 시도해주세요.");
        return;
      }

      const refreshedUser = await refreshAuthenticatedUser().catch(() => null);
      const userId = refreshedUser?.id ?? user?.id;
      setMySkinProfileCache(userId, savedProfile);
      if (typeof userId === "number") {
        queryClient.setQueryData(skinProfileQueryKey(userId), savedProfile);
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
      <HomeHeader />
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
              <ToggleGroup
                className="mt-3 grid grid-cols-2 gap-2 sm:grid-cols-5"
                onValueChange={(value) => {
                  if (value) {
                    handleSingleSelect("skinType", value);
                  }
                }}
                type="single"
                value={form.skinType}
              >
                {skinTypeOptions.map((option) => (
                  <ToggleGroupItem key={option.id} value={option.id}>
                    {option.label}
                  </ToggleGroupItem>
                ))}
              </ToggleGroup>
            </section>

            <section>
              <h2 className="text-[15px] font-semibold text-[#1A1A1A]">민감도</h2>
              <ToggleGroup
                className="mt-3 grid grid-cols-3 gap-2"
                onValueChange={(value) => {
                  if (value) {
                    handleSingleSelect("sensitivity", value);
                  }
                }}
                type="single"
                value={form.sensitivity}
              >
                {sensitivityOptions.map((option) => (
                  <ToggleGroupItem key={option.id} value={option.id}>
                    {option.label}
                  </ToggleGroupItem>
                ))}
              </ToggleGroup>
            </section>

            <section>
              <h2 className="text-[15px] font-semibold text-[#1A1A1A]">피부 고민</h2>
              <ToggleGroup
                className="mt-3 flex flex-wrap gap-2"
                onValueChange={(nextValues) => {
                  const changed =
                    nextValues.find((value) => !form.concerns.includes(value)) ??
                    form.concerns.find((value) => !nextValues.includes(value));

                  if (changed) {
                    handleMultiSelect("concerns", changed);
                  }
                }}
                type="multiple"
                value={form.concerns}
              >
                {concernOptions.map((option) => (
                  <ToggleGroupItem key={option.id} size="sm" value={option.id}>
                    {option.label}
                  </ToggleGroupItem>
                ))}
              </ToggleGroup>
            </section>

            <section>
              <h2 className="text-[15px] font-semibold text-[#1A1A1A]">
                피하고 싶은 성분
              </h2>
              <ToggleGroup
                className="mt-3 flex flex-wrap gap-2"
                onValueChange={(nextValues) => {
                  const changed =
                    nextValues.find((value) => !form.avoidIngredients.includes(value)) ??
                    form.avoidIngredients.find((value) => !nextValues.includes(value));

                  if (changed) {
                    handleMultiSelect("avoidIngredients", changed);
                  }
                }}
                type="multiple"
                value={form.avoidIngredients}
              >
                {avoidIngredientOptions.map((option) => (
                  <ToggleGroupItem key={option.id} size="sm" value={option.id}>
                    {option.label}
                  </ToggleGroupItem>
                ))}
              </ToggleGroup>
            </section>

            <div className="mt-1 grid grid-cols-2 gap-2">
              <Button
                onClick={() => navigate("/", { replace: true })}
                variant="outline"
              >
                건너뛰기
              </Button>
              <Button
                className="disabled:cursor-not-allowed disabled:opacity-50"
                disabled={!canSubmit || isSubmitting}
                onClick={handleSubmit}
              >
                완료
              </Button>
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
