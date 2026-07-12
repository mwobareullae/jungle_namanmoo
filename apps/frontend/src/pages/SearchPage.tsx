import { useEffect, useMemo, useState } from "react";
import HomeHeader from "../components/HomeHeader";
import HomeMainContent from "../components/HomeMainContent";
import HomeOverlays from "../components/HomeOverlays";
import SearchBarPanel from "../components/SearchBarPanel";
import { HomeMatchResult } from "../components/HomeStaticSections";
import { installHomeRuntime } from "../lib/homeRuntime";
import { getSavedSkinProfile } from "../lib/profileApi";
import type { RecommendationProfile, SearchMode, Sensitivity, SkinType } from "../types/recommendation";

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

const getSearchParams = () => {
  const params = new URLSearchParams(window.location.search);
  const skinType = params.get("skin_type");
  const sensitivity = params.get("sensitivity");
  const hasSkinType = skinTypes.includes(skinType as SkinType);
  const hasSensitivity = sensitivities.includes(sensitivity as Sensitivity);

  return {
    keyword: params.get("keyword") ?? "",
    skin: hasSkinType ? (skinType as SkinType) : undefined,
    sensitivity: hasSensitivity ? (sensitivity as Sensitivity) : undefined,
    page: normalizePositiveNumber(params.get("page"), 1),
    pageSize: normalizePositiveNumber(params.get("page_size"), 10),
    recommendationId: params.get("recommendation_id") ?? undefined,
    searchMode: params.get("search_mode") === "general" ? "general" as SearchMode : "ai" as SearchMode
  };
};

function SearchPage() {
  const { keyword, skin, sensitivity, page, pageSize, recommendationId, searchMode } = useMemo(
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
    let isMounted = true;

    getSavedSkinProfile().then((nextSavedProfile) => {
      if (isMounted) {
        setSavedProfile(nextSavedProfile);
        setIsProfileResolved(true);
      }
    });

    return () => {
      isMounted = false;
    };
  }, []);

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
      {searchMode === "ai" ? <HomeMatchResult compact /> : null}
      <HomeMainContent
        initialProfile={profile}
        initialQuery={isProfileResolved ? keyword : ""}
        initialPage={page}
        initialRecommendationId={recommendationId}
        initialSearchMode={searchMode}
        pageSize={pageSize}
        mode="search"
        showDefaultSection={false}
      />
    </div>
  );
}

export default SearchPage;
