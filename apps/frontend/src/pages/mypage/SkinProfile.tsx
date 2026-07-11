import type { CSSProperties, ReactNode } from "react";
import { useEffect, useRef, useState } from "react";
import { avoidIngredientCategories } from "../../constants/avoidIngredientCategories";
import { ToggleGroup, ToggleGroupItem } from "../../components/ui/toggle-group";
import { getMySkinProfile, updateMySkinProfile, type SkinProfileData } from "../../lib/profileApi";
import type { Sensitivity, SkinType } from "../../types/recommendation";
import { MyPageLayout, MypageToastMessage, PageTitle, type MypageEventContext } from "./MyPageShell";

type SkinTypeId = "dry" | "oily" | "combination" | "dehydrated_oily" | "normal";
type SensitivityId = "low" | "normal" | "high";
type ConcernId =
  | "concern_acne"
  | "concern_brightening_spots"
  | "concern_pore"
  | "concern_sebum_oil"
  | "concern_dry_barrier"
  | "concern_wrinkle"
  | "concern_elasticity"
  | "concern_redness_irritation"
  | "concern_dead_skin_texture"
  | "concern_blemish_mark"
  | "concern_skin_tone"
  | "concern_dark_circle"
  | "none";
type AvoidIngredientId = (typeof avoidIngredientCategories)[number]["id"];

export type SkinProfileDraft = {
  skinType: SkinTypeId;
  sensitivity: SensitivityId;
  concerns: ConcernId[];
  avoidIngredients: AvoidIngredientId[];
  eventContext?: MypageEventContext;
};

type SkinProfileProps = {
  initialProfile?: SkinProfileDraft;
  onSubmitDraft?: (profile: SkinProfileDraft) => void;
};

const skinTypeOptions: { id: SkinTypeId; label: string }[] = [
  { id: "dry", label: "건성" },
  { id: "oily", label: "지성" },
  { id: "combination", label: "복합성" },
  { id: "dehydrated_oily", label: "수부지" },
  { id: "normal", label: "중성" }
];

const sensitivityOptions: { id: SensitivityId; label: string }[] = [
  { id: "low", label: "낮음" },
  { id: "normal", label: "보통" },
  { id: "high", label: "높음" }
];

const concernOptions: { id: ConcernId; label: string }[] = [
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

const avoidOptions = avoidIngredientCategories.map(({ id, label, mappedIngredients }) => ({
  id,
  label,
  mappedIngredients
}));

const emptyProfile: SkinProfileDraft = {
  skinType: "" as SkinTypeId,
  sensitivity: "" as SensitivityId,
  concerns: [],
  avoidIngredients: [],
  eventContext: {
    page: "mypage_skin_profile",
    source: "mypage_skin_profile_form",
    sectionId: "skin_profile"
  }
};

const SAVE_INDICATOR_MIN_DURATION_MS = 600;

const labelOf = <T extends string>(options: { id: T; label: string }[], id: T) =>
  options.find((option) => option.id === id)?.label ?? "-";

const toggleMultiValue = <T extends string>(values: T[], value: T) => {
  if (value === "none") {
    return values.includes(value) ? [] : [value];
  }

  const withoutNone = values.filter((item) => item !== "none");
  return withoutNone.includes(value)
    ? withoutNone.filter((item) => item !== value)
    : [...withoutNone, value];
};

const idFromLabel = <T extends string>(options: { id: T; label: string }[], label: string | null | undefined) =>
  options.find((option) => option.label === label)?.id;

const labelsFromIds = <T extends string>(options: { id: T; label: string }[], ids: T[]) =>
  ids
    .filter((id) => id !== "none")
    .map((id) => labelOf(options, id))
    .filter((label) => label !== "-");

const idsFromLabels = <T extends string>(options: { id: T; label: string }[], labels: string[]) =>
  labels.map((label) => idFromLabel(options, label)).filter((id): id is T => Boolean(id));

const sameValues = (left: string[], right: string[]) =>
  left.length === right.length && left.every((value, index) => value === right[index]);

const isSameProfileDraft = (left: SkinProfileDraft, right: SkinProfileDraft) =>
  left.skinType === right.skinType &&
  left.sensitivity === right.sensitivity &&
  sameValues(left.concerns, right.concerns) &&
  sameValues(left.avoidIngredients, right.avoidIngredients);

const avoidIdFromStoredValue = (value: string) =>
  avoidOptions.find(
    (option) =>
      option.id === value ||
      option.label === value ||
      (option.mappedIngredients as readonly string[]).includes(value)
  )?.id;

const avoidIdsFromStoredValues = (values: string[]) =>
  values.map((value) => avoidIdFromStoredValue(value)).filter((id): id is AvoidIngredientId => Boolean(id));

const draftFromSkinProfile = (profile: SkinProfileData, fallback: SkinProfileDraft): SkinProfileDraft => {
  const concerns = idsFromLabels(concernOptions, profile.concerns);
  const avoidIngredients = avoidIdsFromStoredValues(profile.avoidIngredients);

  return {
    ...fallback,
    skinType: idFromLabel(skinTypeOptions, profile.skinType) ?? fallback.skinType,
    sensitivity: idFromLabel(sensitivityOptions, profile.sensitivity) ?? fallback.sensitivity,
    concerns: concerns.length > 0 ? concerns : fallback.concerns,
    avoidIngredients: avoidIngredients.length > 0 ? avoidIngredients : []
  };
};

export default function SkinProfile({ initialProfile = emptyProfile, onSubmitDraft }: SkinProfileProps) {
  const [profile, setProfile] = useState<SkinProfileDraft>(initialProfile);
  const [savedProfile, setSavedProfile] = useState<SkinProfileDraft>(initialProfile);
  const [isLoadingProfile, setIsLoadingProfile] = useState(true);
  const [isSaving, setIsSaving] = useState(false);
  const [showSaveToast, setShowSaveToast] = useState(false);
  const [statusMessage, setStatusMessage] = useState<string | null>(null);
  const saveToastTimerRef = useRef<number | null>(null);
  const canSave =
    Boolean(profile.skinType && profile.sensitivity) &&
    !isSameProfileDraft(profile, savedProfile);

  useEffect(() => {
    let isActive = true;

    getMySkinProfile()
      .then((savedProfile) => {
        if (!isActive) {
          return;
        }

        if (savedProfile) {
          const nextProfile = draftFromSkinProfile(savedProfile, emptyProfile);
          setProfile(nextProfile);
          setSavedProfile(nextProfile);
          setStatusMessage(null);
        }
      })
      .catch(() => {
        if (isActive) {
          setStatusMessage("저장된 피부 프로필을 불러오지 못했습니다.");
        }
      })
      .finally(() => {
        if (isActive) {
          setIsLoadingProfile(false);
        }
      });

    return () => {
      isActive = false;
    };
  }, []);

  useEffect(() => {
    return () => {
      if (saveToastTimerRef.current !== null) {
        window.clearTimeout(saveToastTimerRef.current);
      }
    };
  }, []);

  const saveProfile = async () => {
    if (!canSave || isSaving) {
      return;
    }

    setIsSaving(true);
    setStatusMessage(null);
    const savingStartedAt = Date.now();

    try {
      const savedProfile = await updateMySkinProfile({
        skinType: labelOf(skinTypeOptions, profile.skinType) as SkinType,
        sensitivity: labelOf(sensitivityOptions, profile.sensitivity) as Sensitivity,
        avoidIngredients: labelsFromIds(avoidOptions, profile.avoidIngredients),
        concerns: labelsFromIds(concernOptions, profile.concerns)
      });

      if (savedProfile) {
        const nextProfile = draftFromSkinProfile(savedProfile, emptyProfile);
        setProfile(nextProfile);
        setSavedProfile(nextProfile);
      }

      onSubmitDraft?.(profile);
      setShowSaveToast(true);
      if (saveToastTimerRef.current !== null) {
        window.clearTimeout(saveToastTimerRef.current);
      }
      saveToastTimerRef.current = window.setTimeout(() => {
        setShowSaveToast(false);
        saveToastTimerRef.current = null;
      }, 2500);
    } catch {
      setStatusMessage("피부 프로필 저장에 실패했습니다. 잠시 후 다시 시도해주세요.");
    } finally {
      const remainingDuration = Math.max(0, SAVE_INDICATOR_MIN_DURATION_MS - (Date.now() - savingStartedAt));
      window.setTimeout(() => setIsSaving(false), remainingDuration);
    }
  };

  return (
    <MyPageLayout activePath="/mypage/skin-profile">
      <PageTitle
        title="피부 프로필 관리"
      />
      {isLoadingProfile ? <p style={styles.statusMessage}>저장된 피부 프로필을 불러오는 중입니다.</p> : null}
      {statusMessage ? <p style={styles.statusMessage}>{statusMessage}</p> : null}
      <ProfileSection title="피부 타입">
        <ToggleGroup
          className="flex flex-wrap gap-[12px_10px]"
          onValueChange={(value) => {
            if (value) {
              setProfile((prev) => ({ ...prev, skinType: value as SkinTypeId }));
            }
          }}
          type="single"
          value={profile.skinType}
        >
          {skinTypeOptions.map((option) => (
            <ToggleGroupItem className="min-w-[78px]" key={option.id} pill size="lg" tone="mint" value={option.id}>
              {option.label}
            </ToggleGroupItem>
          ))}
        </ToggleGroup>
      </ProfileSection>
      <ProfileSection title="민감도">
        <ToggleGroup
          className="flex flex-wrap gap-[12px_10px]"
          onValueChange={(value) => {
            if (value) {
              setProfile((prev) => ({ ...prev, sensitivity: value as SensitivityId }));
            }
          }}
          type="single"
          value={profile.sensitivity}
        >
          {sensitivityOptions.map((option) => (
            <ToggleGroupItem className="min-w-[78px]" key={option.id} pill size="lg" tone="mint" value={option.id}>
              {option.label}
            </ToggleGroupItem>
          ))}
        </ToggleGroup>
      </ProfileSection>
      <ProfileSection suffix="복수 선택" title="피부 고민">
        <ToggleGroup
          className="flex flex-wrap gap-[12px_10px]"
          onValueChange={(nextValues) => {
            const changed =
              nextValues.find((value) => !profile.concerns.includes(value as ConcernId)) ??
              profile.concerns.find((value) => !nextValues.includes(value));

            if (changed) {
              setProfile((prev) => ({
                ...prev,
                concerns: toggleMultiValue(prev.concerns, changed as ConcernId)
              }));
            }
          }}
          type="multiple"
          value={profile.concerns}
        >
          {concernOptions.map((option) => (
            <ToggleGroupItem
              key={option.id}
              pill
              size="lg"
              tone={option.id === "none" ? "neutral" : "mint"}
              value={option.id}
            >
              {option.label}
            </ToggleGroupItem>
          ))}
        </ToggleGroup>
      </ProfileSection>
      <ProfileSection suffix="복수 선택" title="피해야 할 성분">
        <ToggleGroup
          className="flex flex-wrap gap-[12px_10px]"
          onValueChange={(nextValues) => {
            const changed =
              nextValues.find((value) => !profile.avoidIngredients.includes(value as AvoidIngredientId)) ??
              profile.avoidIngredients.find((value) => !nextValues.includes(value));

            if (changed) {
              setProfile((prev) => ({
                ...prev,
                avoidIngredients: toggleMultiValue(prev.avoidIngredients, changed as AvoidIngredientId)
              }));
            }
          }}
          type="multiple"
          value={profile.avoidIngredients}
        >
          {avoidOptions.map((option) => (
            <ToggleGroupItem
              key={option.id}
              pill
              size="lg"
              tone={option.id === "none" ? "neutral" : "danger"}
              value={option.id}
            >
              {option.label}
            </ToggleGroupItem>
          ))}
        </ToggleGroup>
      </ProfileSection>
      <div className="flex items-center justify-end gap-3.5">
        <button
          className={`inline-flex min-h-[46px] w-[180px] items-center justify-center rounded-[10px] text-[14px] font-semibold ${
            isSaving
              ? "cursor-wait bg-[#0C1117] text-white"
              : canSave
                ? "cursor-pointer bg-[#0C1117] text-white hover:bg-[#1A1A1A]"
                : "cursor-not-allowed bg-[#E5E7EB] text-[#9CA3AF]"
          }`}
          disabled={!canSave || isSaving}
          onClick={saveProfile}
          type="button"
        >
          {isSaving ? (
            <>
              <span aria-hidden="true" className="skin-profile-save-spinner" />
              저장 중
            </>
          ) : canSave ? "저장하기" : "저장완료"}
        </button>
      </div>
      {showSaveToast ? <MypageToastMessage message="저장되었습니다" /> : null}
    </MyPageLayout>
  );
}

function ProfileSection({ title, suffix, children }: { title: string; suffix?: string; children: ReactNode }) {
  return (
    <section style={styles.section}>
      <h2 style={styles.sectionTitle}>
        <span>{title}</span>
        {suffix ? <span style={styles.sectionSuffix}>{suffix}</span> : null}
      </h2>
      {children}
    </section>
  );
}

const styles: Record<string, CSSProperties> = {
  statusMessage: {
    margin: "0 0 18px",
    color: "#6b7280",
    fontSize: 13,
    lineHeight: 1.5
  },
  section: {
    paddingBottom: 30,
    marginBottom: 30,
    borderBottom: "1px solid #eceff1"
  },
  sectionTitle: {
    display: "flex",
    alignItems: "center",
    gap: 7,
    margin: "0 0 16px",
    color: "#222222",
    fontFamily: "'Pretendard Variable', 'Pretendard', 'Noto Sans KR', sans-serif",
    fontSize: 15,
    fontWeight: 700,
    lineHeight: 1.35
  },
  sectionSuffix: {
    marginLeft: 4,
    alignSelf: "center",
    color: "#9ca3af",
    fontSize: 12,
    fontWeight: 500
  },
};
