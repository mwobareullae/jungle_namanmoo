import { API_BASE_URL, fetchWithTimeout, parseJson } from "./api";
import type { RecommendationProfile, Sensitivity, SkinType } from "../types/recommendation";

type BackendSkinProfileData = {
  id?: number;
  user_id?: number | null;
  skin_type?: string | null;
  sensitivity?: string | null;
  skin_type_source?: string | null;
  sensitivity_source?: string | null;
  explicit_skin_type?: string | null;
  explicit_sensitivity?: string | null;
  avoid_ingredients?: unknown;
  concerns?: unknown;
  latest_skin_test_result_id?: number | null;
  latest_skin_test_result_code?: string | null;
  baumann_type_code?: string | null;
  baumann_inferred_skin_type?: string | null;
  baumann_inferred_sensitivity?: string | null;
  baumann_signal_weight?: number | null;
  commerce_profile?: Record<string, unknown> | null;
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
  explicitSkinType?: string | null;
  explicitSensitivity?: string | null;
  avoidIngredients: string[];
  concerns: string[];
  latestSkinTestResultId?: number | null;
  latestSkinTestResultCode?: string | null;
  baumannTypeCode?: string | null;
  baumannInferredSkinType?: string | null;
  baumannInferredSensitivity?: string | null;
  baumannSignalWeight?: number | null;
  commerceProfile?: Record<string, unknown> | null;
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
    explicit_skin_type,
    explicit_sensitivity,
    avoid_ingredients,
    concerns,
    latest_skin_test_result_id,
    latest_skin_test_result_code,
    baumann_type_code,
    baumann_inferred_skin_type,
    baumann_inferred_sensitivity,
    baumann_signal_weight,
    commerce_profile,
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
    explicitSkinType: explicit_skin_type,
    explicitSensitivity: explicit_sensitivity,
    avoidIngredients: normalizeAvoidIngredients(avoid_ingredients),
    concerns: normalizeStringList(concerns),
    latestSkinTestResultId: latest_skin_test_result_id,
    latestSkinTestResultCode: latest_skin_test_result_code,
    baumannTypeCode: baumann_type_code,
    baumannInferredSkinType: baumann_inferred_skin_type,
    baumannInferredSensitivity: baumann_inferred_sensitivity,
    baumannSignalWeight: baumann_signal_weight,
    commerceProfile: commerce_profile,
    source,
    createdAt: created_at,
    updatedAt: updated_at
  };
};

export const toRecommendationProfile = (profile: SkinProfileData): RecommendationProfile => ({
  skin: profile.skinType,
  sensitivity: profile.sensitivity,
  avoidIngredients: profile.avoidIngredients
});

const SKIN_PROFILE_CACHE_TTL_MS = 5 * 60_000;
const skinProfileCache = new Map<number, { value: SkinProfileData | null; expiresAt: number }>();
let inFlightSkinProfileRequest: { userId: number; request: Promise<SkinProfileData | null> } | null = null;

export const getMySkinProfile = async (userId?: number | null): Promise<SkinProfileData | null> => {
  const numericUserId = typeof userId === "number" ? userId : null;
  if (numericUserId !== null) {
    const cached = skinProfileCache.get(numericUserId);
    if (cached && cached.expiresAt > Date.now()) {
      return cached.value;
    }
    if (inFlightSkinProfileRequest?.userId === numericUserId) {
      return inFlightSkinProfileRequest.request;
    }
  }

  const request = (async () => {
    const response = await fetchWithTimeout(`${API_BASE_URL}/me/skin-profile`);
    return mapSkinProfileData(await parseJson<BackendSkinProfileResponse>(response));
  })();
  if (numericUserId !== null) {
    inFlightSkinProfileRequest = { userId: numericUserId, request };
  }

  try {
    const value = await request;
    if (numericUserId !== null) {
      skinProfileCache.set(numericUserId, { value, expiresAt: Date.now() + SKIN_PROFILE_CACHE_TTL_MS });
    }
    return value;
  } finally {
    if (inFlightSkinProfileRequest?.request === request) {
      inFlightSkinProfileRequest = null;
    }
  }
};

export const setMySkinProfileCache = (userId: number | null | undefined, value: SkinProfileData | null) => {
  if (typeof userId === "number") {
    skinProfileCache.set(userId, { value, expiresAt: Date.now() + SKIN_PROFILE_CACHE_TTL_MS });
  }
};

export const invalidateMySkinProfileCache = (userId: number | null | undefined) => {
  if (typeof userId === "number") {
    skinProfileCache.delete(userId);
  }
};

export const getSavedSkinProfile = async (userId?: number | null): Promise<RecommendationProfile | null> => {
  try {
    const profile = await getMySkinProfile(userId);
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
