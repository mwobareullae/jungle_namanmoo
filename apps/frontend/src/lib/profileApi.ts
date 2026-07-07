import { API_BASE_URL, fetchWithTimeout, parseJson } from "./api";
import type { RecommendationProfile, Sensitivity, SkinType } from "../types/recommendation";

type BackendSkinProfileData = {
  id?: number;
  user_id?: number | null;
  skin_type?: string | null;
  sensitivity?: string | null;
  skin_type_source?: string | null;
  sensitivity_source?: string | null;
  avoid_ingredients?: unknown;
  concerns?: unknown;
  source?: string | null;
  created_at?: string | null;
  updated_at?: string | null;
};

type BackendSkinProfileResponse = {
  has_profile: boolean;
  profile: BackendSkinProfileData | null;
};

export type SkinProfileData = {
  id?: number;
  userId?: number | null;
  skinType: SkinType;
  sensitivity: Sensitivity;
  skinTypeSource?: string | null;
  sensitivitySource?: string | null;
  avoidIngredients: string[];
  concerns: string[];
  source?: string | null;
  createdAt?: string | null;
  updatedAt?: string | null;
};

export type SkinProfileUpdatePayload = {
  skinType: SkinType;
  sensitivity: Sensitivity;
  avoidIngredients: string[];
  concerns?: string[];
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

const normalizeStringList = normalizeAvoidIngredients;

const mapSkinProfileData = (response: BackendSkinProfileResponse): SkinProfileData | null => {
  if (!response.has_profile || !response.profile) {
    return null;
  }

  const {
    id,
    user_id,
    skin_type,
    sensitivity,
    skin_type_source,
    sensitivity_source,
    avoid_ingredients,
    concerns,
    source,
    created_at,
    updated_at
  } = response.profile;
  if (!isSkinType(skin_type) || !isSensitivity(sensitivity)) {
    return null;
  }

  return {
    id,
    userId: user_id,
    skinType: skin_type,
    sensitivity,
    skinTypeSource: skin_type_source,
    sensitivitySource: sensitivity_source,
    avoidIngredients: normalizeAvoidIngredients(avoid_ingredients),
    concerns: normalizeStringList(concerns),
    source,
    createdAt: created_at,
    updatedAt: updated_at
  };
};

const toRecommendationProfile = (profile: SkinProfileData): RecommendationProfile => ({
  skin: profile.skinType,
  sensitivity: profile.sensitivity,
  avoidIngredients: profile.avoidIngredients
});

export const getMySkinProfile = async (): Promise<SkinProfileData | null> => {
  const response = await fetchWithTimeout(`${API_BASE_URL}/me/skin-profile`);
  return mapSkinProfileData(await parseJson<BackendSkinProfileResponse>(response));
};

export const getSavedSkinProfile = async (): Promise<RecommendationProfile | null> => {
  try {
    const profile = await getMySkinProfile();
    return profile ? toRecommendationProfile(profile) : null;
  } catch {
    return null;
  }
};

export const updateMySkinProfile = async (payload: SkinProfileUpdatePayload): Promise<SkinProfileData | null> => {
  const response = await fetchWithTimeout(`${API_BASE_URL}/me/skin-profile`, {
    method: "PUT",
    headers: {
      "Content-Type": "application/json"
    },
    body: JSON.stringify({
      skin_type: payload.skinType,
      sensitivity: payload.sensitivity,
      avoid_ingredients: payload.avoidIngredients,
      concerns: payload.concerns ?? []
    })
  });

  return mapSkinProfileData(await parseJson<BackendSkinProfileResponse>(response));
};
