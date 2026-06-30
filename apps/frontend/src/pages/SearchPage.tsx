import { useEffect } from "react";
import HomeHeader from "../components/HomeHeader";
import HomeMainContent from "../components/HomeMainContent";
import HomeOverlays from "../components/HomeOverlays";
import SearchBarPanel from "../components/SearchBarPanel";
import { HomeMatchResult } from "../components/HomeStaticSections";
import { installHomeRuntime } from "../lib/homeRuntime";
import type { Sensitivity, SkinType } from "../types/recommendation";

const skinTypes = ["건성", "지성", "복합성", "수부지", "중성"] as const;
const sensitivities = ["낮음", "보통", "높음"] as const;

const normalizePositiveNumber = (value: string | null, fallback: number) => {
  const parsed = Number(value);
  return Number.isFinite(parsed) && parsed > 0 ? Math.floor(parsed) : fallback;
};

const getSearchParams = () => {
  const params = new URLSearchParams(window.location.search);
  const skinType = params.get("skin_type");
  const sensitivity = params.get("sensitivity");

  return {
    keyword: params.get("keyword") ?? "",
    skin: skinTypes.includes(skinType as SkinType) ? (skinType as SkinType) : "수부지",
    sensitivity: sensitivities.includes(sensitivity as Sensitivity)
      ? (sensitivity as Sensitivity)
      : "보통",
    page: normalizePositiveNumber(params.get("page"), 1),
    pageSize: normalizePositiveNumber(params.get("page_size"), 10),
    recommendationId: params.get("recommendation_id") ?? undefined,
  };
};

function SearchPage() {
  const { keyword, skin, sensitivity, page, pageSize, recommendationId } = getSearchParams();
  const profile = { skin, sensitivity };

  useEffect(() => installHomeRuntime(profile), [skin, sensitivity]);

  return (
    <div className="search-page-shell">
      <HomeOverlays />
      <HomeHeader />
      <SearchBarPanel initialProfile={profile} initialQuery={keyword} />
      <HomeMatchResult compact />
      <HomeMainContent
        initialProfile={profile}
        initialQuery={keyword}
        initialPage={page}
        initialRecommendationId={recommendationId}
        pageSize={pageSize}
        mode="search"
        showDefaultSection={false}
      />
    </div>
  );
}

export default SearchPage;
