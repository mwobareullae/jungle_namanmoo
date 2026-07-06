import type { CSSProperties, ReactNode } from "react";
import { useEffect, useRef, useState } from "react";
import { avoidIngredientCategories } from "../../constants/avoidIngredientCategories";
import { getMySkinProfile, updateMySkinProfile, type SkinProfileData } from "../../lib/profileApi";
import type { Sensitivity, SkinType } from "../../types/recommendation";
import { MyPageLayout, PageTitle, type MypageEventContext } from "./MyPageShell";

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

const defaultProfile: SkinProfileDraft = {
  skinType: "dehydrated_oily",
  sensitivity: "normal",
  concerns: ["concern_acne", "concern_dry_barrier"],
  avoidIngredients: ["fragrance"],
  eventContext: {
    page: "mypage_skin_profile",
    source: "mypage_skin_profile_form",
    sectionId: "skin_profile"
  }
};

const labelOf = <T extends string>(options: { id: T; label: string }[], id: T) =>
  options.find((option) => option.id === id)?.label ?? "-";

const labelsOf = <T extends string>(options: { id: T; label: string }[], ids: T[]) =>
  ids.map((id) => labelOf(options, id)).filter(Boolean);

const formatSensitivityLabel = (label: string) => `민감 ${label}`;

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

const avoidIdFromStoredValue = (value: string) =>
  avoidOptions.find(
    (option) => option.id === value || option.label === value || option.mappedIngredients.includes(value)
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
    avoidIngredients: avoidIngredients.length > 0 ? avoidIngredients : ["none"]
  };
};

export default function SkinProfile({ initialProfile = defaultProfile, onSubmitDraft }: SkinProfileProps) {
  const [profile, setProfile] = useState<SkinProfileDraft>(initialProfile);
  const [isLoadingProfile, setIsLoadingProfile] = useState(true);
  const [isSaving, setIsSaving] = useState(false);
  const [showSaveToast, setShowSaveToast] = useState(false);
  const [statusMessage, setStatusMessage] = useState<string | null>(null);
  const saveToastTimerRef = useRef<number | null>(null);
  const canSave =
    profile.skinType &&
    profile.sensitivity &&
    profile.concerns.length > 0 &&
    profile.avoidIngredients.length > 0;

  useEffect(() => {
    let isActive = true;

    getMySkinProfile()
      .then((savedProfile) => {
        if (!isActive) {
          return;
        }

        if (savedProfile) {
          setProfile((current) => draftFromSkinProfile(savedProfile, current));
          setStatusMessage(null);
        }
      })
      .catch(() => {
        if (isActive) {
          setStatusMessage("저장된 피부 프로필을 불러오지 못해 기본값으로 표시 중입니다.");
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

    try {
      const savedProfile = await updateMySkinProfile({
        skinType: labelOf(skinTypeOptions, profile.skinType) as SkinType,
        sensitivity: labelOf(sensitivityOptions, profile.sensitivity) as Sensitivity,
        avoidIngredients: labelsFromIds(avoidOptions, profile.avoidIngredients),
        concerns: labelsFromIds(concernOptions, profile.concerns)
      });

      if (savedProfile) {
        setProfile((current) => draftFromSkinProfile(savedProfile, current));
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
      setIsSaving(false);
    }
  };

  return (
    <MyPageLayout activePath="/mypage/skin-profile">
      <PageTitle
        title="피부 프로필 관리"
        rightSlot={
          <div style={styles.titleTags}>
            <span style={styles.primaryTag}>{labelOf(skinTypeOptions, profile.skinType)}</span>
            <span style={styles.tag}>{formatSensitivityLabel(labelOf(sensitivityOptions, profile.sensitivity))}</span>
            {labelsOf(concernOptions, profile.concerns).slice(0, 2).map((label) => (
              <span style={styles.tag} key={label}>{label}</span>
            ))}
          </div>
        }
      />
      {isLoadingProfile ? <p style={styles.statusMessage}>저장된 피부 프로필을 불러오는 중입니다.</p> : null}
      {statusMessage ? <p style={styles.statusMessage}>{statusMessage}</p> : null}
      <ProfileSection title="피부 타입">
        <div style={styles.skinGrid}>
          {skinTypeOptions.map((option) => (
            <ChoiceButton
              active={profile.skinType === option.id}
              key={option.id}
              label={option.label}
              onClick={() => setProfile((prev) => ({ ...prev, skinType: option.id }))}
            />
          ))}
        </div>
      </ProfileSection>
      <ProfileSection title="민감도">
        <div style={styles.sensitivityGrid}>
          {sensitivityOptions.map((option) => (
            <ChoiceButton
              active={profile.sensitivity === option.id}
              key={option.id}
              label={option.label}
              onClick={() => setProfile((prev) => ({ ...prev, sensitivity: option.id }))}
            />
          ))}
        </div>
      </ProfileSection>
      <ProfileSection title="피부 고민" suffix="복수 선택">
        <div style={styles.chipGrid}>
          {concernOptions.map((option) => (
            <ChoiceButton
              active={profile.concerns.includes(option.id)}
              compact
              key={option.id}
              label={option.label}
              tone={option.id === "none" ? "neutral" : "default"}
              onClick={() =>
                setProfile((prev) => ({
                  ...prev,
                  concerns: toggleMultiValue(prev.concerns, option.id)
                }))
              }
            />
          ))}
        </div>
      </ProfileSection>
      <ProfileSection title="피해야 할 성분" suffix="복수 선택">
        <div style={styles.chipGrid}>
          {avoidOptions.map((option) => (
            <ChoiceButton
              active={profile.avoidIngredients.includes(option.id)}
              compact
              tone={option.id === "none" ? "neutral" : "danger"}
              key={option.id}
              label={option.label}
              onClick={() =>
                setProfile((prev) => ({
                  ...prev,
                  avoidIngredients: toggleMultiValue(prev.avoidIngredients, option.id)
                }))
              }
            />
          ))}
        </div>
      </ProfileSection>
      <div style={styles.actions}>
        <button
          type="button"
          disabled={!canSave || isSaving}
          onClick={saveProfile}
          style={{
            ...styles.saveButton,
            ...(canSave && !isSaving ? styles.saveButtonEnabled : styles.saveButtonDisabled)
          }}
        >
          {isSaving ? "저장 중" : "저장하기"}
        </button>
      </div>
      {showSaveToast ? (
        <div style={styles.toast} role="status" aria-live="polite">
          <span style={styles.toastDot} />
          <span>저장되었습니다</span>
        </div>
      ) : null}
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

function ChoiceButton({
  active,
  compact = false,
  label,
  onClick,
  tone = "default"
}: {
  active: boolean;
  compact?: boolean;
  label: string;
  onClick: () => void;
  tone?: "default" | "danger" | "neutral";
}) {
  const defaultStyle =
    tone === "danger"
      ? styles.choiceButtonDangerDefault
      : tone === "neutral"
        ? styles.choiceButtonNeutralDefault
        : styles.choiceButtonDefault;
  const activeStyle =
    tone === "danger"
      ? styles.choiceButtonDangerActive
      : tone === "neutral"
        ? styles.choiceButtonNeutralActive
        : styles.choiceButtonActive;

  return (
    <button
      type="button"
      onClick={onClick}
      style={{
        ...styles.choiceButton,
        ...(compact ? styles.choiceButtonCompact : {}),
        ...(active ? activeStyle : defaultStyle)
      }}
    >
      {label}
    </button>
  );
}

const styles: Record<string, CSSProperties> = {
  titleTags: {
    display: "flex",
    gap: 5,
    flexWrap: "wrap"
  },
  primaryTag: {
    display: "inline-flex",
    alignItems: "center",
    minHeight: 22,
    padding: "0 9px",
    borderRadius: 999,
    background: "rgba(148,224,248,0.18)",
    border: "1px solid rgba(148,224,248,0.5)",
    color: "#063445",
    fontSize: 12,
    fontWeight: 600
  },
  tag: {
    display: "inline-flex",
    alignItems: "center",
    minHeight: 22,
    padding: "0 9px",
    borderRadius: 999,
    border: "1px solid #e0e0e0",
    color: "#555555",
    fontSize: 12
  },
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
  skinGrid: {
    display: "flex",
    flexWrap: "wrap",
    gap: "12px 10px"
  },
  sensitivityGrid: {
    display: "flex",
    flexWrap: "wrap",
    gap: "12px 10px"
  },
  chipGrid: {
    display: "flex",
    flexWrap: "wrap",
    gap: "12px 10px"
  },
  choiceButton: {
    minHeight: 42,
    minWidth: 78,
    borderRadius: 999,
    padding: "0 18px",
    fontSize: 14,
    cursor: "pointer",
    fontFamily: "inherit",
    display: "inline-flex",
    alignItems: "center",
    justifyContent: "center",
    lineHeight: 1,
    transition: "background 0.15s ease, border-color 0.15s ease, color 0.15s ease"
  },
  choiceButtonCompact: {
    minHeight: 42,
    minWidth: "auto",
    padding: "0 18px",
    fontSize: 14
  },
  choiceButtonActive: {
    border: "1px solid rgba(148,224,248,0.95)",
    background: "rgba(148,224,248,0.22)",
    color: "#063445",
    fontWeight: 700
  },
  choiceButtonDefault: {
    border: "1px solid #e1e5e8",
    background: "#ffffff",
    color: "#4b5563",
    fontWeight: 500
  },
  choiceButtonDangerActive: {
    border: "1px solid rgba(239,68,68,0.34)",
    background: "rgba(239,68,68,0.12)",
    color: "#9f2c2c",
    fontWeight: 600
  },
  choiceButtonDangerDefault: {
    border: "1px solid #e1e5e8",
    background: "#ffffff",
    color: "#4b5563",
    fontWeight: 500
  },
  choiceButtonNeutralActive: {
    border: "1px solid #4b5563",
    background: "#4b5563",
    color: "#ffffff",
    fontWeight: 600
  },
  choiceButtonNeutralDefault: {
    border: "1px solid #e1e5e8",
    background: "#ffffff",
    color: "#4b5563",
    fontWeight: 500
  },
  actions: {
    display: "flex",
    alignItems: "center",
    justifyContent: "flex-end",
    gap: 14
  },
  saveButton: {
    display: "inline-flex",
    alignItems: "center",
    justifyContent: "center",
    width: 180,
    minHeight: 46,
    padding: "0 30px",
    borderRadius: 10,
    border: "none",
    fontSize: 14,
    fontWeight: 600,
    fontFamily: "inherit"
  },
  saveButtonEnabled: {
    background: "#0c1117",
    color: "#ffffff",
    cursor: "pointer"
  },
  saveButtonDisabled: {
    background: "#e5e7eb",
    color: "#9ca3af",
    cursor: "not-allowed"
  },
  toast: {
    position: "fixed",
    left: "50%",
    bottom: 36,
    zIndex: 1000,
    transform: "translateX(-50%)",
    display: "inline-flex",
    alignItems: "center",
    gap: 9,
    minHeight: 42,
    padding: "0 18px",
    borderRadius: 999,
    background: "#0c1117",
    color: "#ffffff",
    boxShadow: "0 12px 32px rgba(15,23,42,0.22)",
    fontSize: 14,
    fontWeight: 600
  },
  toastDot: {
    width: 7,
    height: 7,
    borderRadius: "50%",
    background: "#94e0f8",
    flex: "0 0 auto"
  }
};
