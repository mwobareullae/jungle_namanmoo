import HomeHero from "../components/HomeHero";
import HomeHeader from "../components/HomeHeader";
import HomeMainContent from "../components/HomeMainContent";
import HomeOverlays from "../components/HomeOverlays";
import { HomeMatchResult } from "../components/HomeStaticSections";
import type { Sensitivity, SkinType } from "../types/recommendation";

const skinTypes = ["건성", "지성", "복합성", "수부지", "중성"] as const;
const sensitivities = ["낮음", "보통", "높음"] as const;

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
  };
};

function SearchPage() {
  const { keyword, skin, sensitivity } = getSearchParams();

  return (
    <>
      <HomeOverlays />
      <HomeHeader />
      <HomeHero />
      <HomeMatchResult />
      <HomeMainContent
        initialProfile={{ skin, sensitivity }}
        initialQuery={keyword}
        showDefaultSection={false}
      />
    </>
  );
}

export default SearchPage;
