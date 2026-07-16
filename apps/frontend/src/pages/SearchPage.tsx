import { useEffect, useMemo, useState } from "react";
import HomeHeader from "../components/HomeHeader";
import HomeMainContent from "../components/HomeMainContent";
import HomeOverlays from "../components/HomeOverlays";
import SearchBarPanel from "../components/SearchBarPanel";
import { useAuth } from "../contexts/useAuth";
import { useSkinProfileQuery } from "../hooks/useSkinProfileQuery";
import { HomeMatchResult } from "../components/HomeStaticSections";
import { installHomeRuntime } from "../lib/homeRuntime";
import { toRecommendationProfile } from "../lib/profileApi";
import type {
  RecommendationProfile,
  RecommendationRefinementFilters,
  SearchMode,
  Sensitivity,
  SkinType,
} from "../types/recommendation";

const skinTypes = ["건성", "지성", "복합성", "수부지", "중성"] as const;
const sensitivities = ["낮음", "보통", "높음"] as const;

const defaultRecommendationProfile: RecommendationProfile = {
  skin: "수부지",
  sensitivity: "보통",
  avoidIngredients: []
};

const normalizePositiveNumber = (value: string | null, fallback: number) => {
  const parsed = Number(value);
  return Number.isFinite(parsed) && parsed > 0 ? Math.floor(parsed) : fallback;
};

const normalizeOptionalNonNegativeNumber = (value: string | null) => {
  if (value === null || value.trim() === "") return undefined;
  const parsed = Number(value);
  return Number.isFinite(parsed) && parsed >= 0 ? Math.floor(parsed) : undefined;
};

const getSearchParams = () => {
  const params = new URLSearchParams(window.location.search);
  const skinType = params.get("skin_type");
  const sensitivity = params.get("sensitivity");
  const hasSkinType = skinTypes.includes(skinType as SkinType);
  const hasSensitivity = sensitivities.includes(sensitivity as Sensitivity);
  const refinementFilters: RecommendationRefinementFilters = {
    min_price: normalizeOptionalNonNegativeNumber(params.get("refine_min_price")),
    max_price: normalizeOptionalNonNegativeNumber(params.get("refine_max_price")),
    category_code: params.get("refine_category_code") ?? undefined,
    skin_type: params.get("refine_skin_type") ?? undefined,
    sensitivity: params.get("refine_sensitivity") ?? undefined,
    effect_keywords: params.getAll("refine_effect").filter(Boolean),
  };
  const hasRefinementFilters = Object.values(refinementFilters).some((value) =>
    Array.isArray(value) ? value.length > 0 : value !== undefined,
  );

  return {
    keyword: params.get("keyword") ?? "",
    skin: hasSkinType ? (skinType as SkinType) : undefined,
    sensitivity: hasSensitivity ? (sensitivity as Sensitivity) : undefined,
    page: normalizePositiveNumber(params.get("page"), 1),
    pageSize: normalizePositiveNumber(params.get("page_size"), 10),
    recommendationId: params.get("recommendation_id") ?? undefined,
    refinementFilters: hasRefinementFilters ? refinementFilters : undefined,
    agentPending: params.get("agent_pending") === "1",
    searchMode: params.get("search_mode") === "general" ? "general" as SearchMode : "ai" as SearchMode
  };
};

function SearchPage() {
  const { isAuthLoading, user } = useAuth();
  const skinProfileQuery = useSkinProfileQuery(user?.id ?? null, !isAuthLoading && Boolean(user));
  const { keyword, skin, sensitivity, page, pageSize, recommendationId, refinementFilters, searchMode, agentPending } = useMemo(
    () => getSearchParams(),
    []
  );
  const [savedProfile, setSavedProfile] = useState<RecommendationProfile | null>(null);
  const [isProfileResolved, setIsProfileResolved] = useState(false);
  const profile = useMemo<RecommendationProfile>(
    () => ({
      skin: skin ?? savedProfile?.skin ?? defaultRecommendationProfile.skin,
      sensitivity:
        sensitivity ?? savedProfile?.sensitivity ?? defaultRecommendationProfile.sensitivity,
      avoidIngredients:
        savedProfile?.avoidIngredients ?? defaultRecommendationProfile.avoidIngredients
    }),
    [savedProfile, sensitivity, skin]
  );

  useEffect(() => installHomeRuntime(profile), [profile]);

  useEffect(() => {
    if (isAuthLoading) {
      return;
    }

    if (!user) {
      const timerId = window.setTimeout(() => {
        setSavedProfile(null);
        setIsProfileResolved(true);
      }, 0);
      return () => window.clearTimeout(timerId);
    }

    if (skinProfileQuery.isPending) {
      return;
    }

    const timerId = window.setTimeout(() => {
      setSavedProfile(skinProfileQuery.data ? toRecommendationProfile(skinProfileQuery.data) : null);
      setIsProfileResolved(true);
    }, 0);
    return () => window.clearTimeout(timerId);
  }, [isAuthLoading, skinProfileQuery.data, skinProfileQuery.isPending, user]);

  return (
    <div className="search-page-shell">
      <HomeOverlays />
      <HomeHeader />
      <SearchBarPanel
        key={`${profile.skin}-${profile.sensitivity}-${profile.avoidIngredients.join("|")}`}
        hasSavedProfile={Boolean(savedProfile)}
        initialProfile={profile}
        initialQuery={keyword}
        initialSearchMode={searchMode}
      />
      <HomeMatchResult compact />
      <HomeMainContent
        initialProfile={profile}
        initialQuery={isProfileResolved ? keyword : ""}
        initialPage={page}
        initialRecommendationId={recommendationId}
        initialRefinementFilters={refinementFilters}
        initialSearchMode={searchMode}
        pageSize={pageSize}
        mode="search"
        deferInitialSearch={agentPending}
        showDefaultSection={false}
      />
    </div>
  );
}

export default SearchPage;
