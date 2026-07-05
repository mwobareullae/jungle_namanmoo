import { API_BASE_URL, fetchWithTimeout, parseJson } from "./api";
import type { RecommendationProfile, Sensitivity, SkinType } from "../types/recommendation";

type BackendSkinProfileData = {
  skin_type?: string | null;
  sensitivity?: string | null;
  avoid_ingredients?: unknown;
};

type BackendSkinProfileResponse = {
  has_profile: boolean;
  profile: BackendSkinProfileData | null;
};

const skinTypes: readonly SkinType[] = ["건성", "지성", "복합성", "수부지", "중성"];
const sensitivities: readonly Sensitivity[] = ["낮음", "보통", "높음"];

const isSkinType = (value: unknown): value is SkinType =>
  typeof value === "string" && skinTypes.includes(value as SkinType);

const isSensitivity = (value: unknown): value is Sensitivity =>
  typeof value === "string" && sensitivities.includes(value as Sensitivity);

const normalizeAvoidIngredients = (value: unknown) =>
  Array.isArray(value)
    ? value.filter((item): item is string => typeof item === "string" && item.trim().length > 0)
    : [];

const mapSkinProfile = (response: BackendSkinProfileResponse): RecommendationProfile | null => {
  if (!response.has_profile || !response.profile) {
    return null;
  }

  const { skin_type, sensitivity, avoid_ingredients } = response.profile;
  if (!isSkinType(skin_type) || !isSensitivity(sensitivity)) {
    return null;
  }

  return {
    skin: skin_type,
    sensitivity,
    avoidIngredients: normalizeAvoidIngredients(avoid_ingredients)
  };
};

export const getSavedSkinProfile = async (): Promise<RecommendationProfile | null> => {
  try {
    const response = await fetchWithTimeout(`${API_BASE_URL}/me/skin-profile`);
    return mapSkinProfile(await parseJson<BackendSkinProfileResponse>(response));
  } catch {
    return null;
  }
};
