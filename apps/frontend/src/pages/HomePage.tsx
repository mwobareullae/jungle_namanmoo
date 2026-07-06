import { useEffect, useState } from "react";
import HomeHero from "../components/HomeHero";
import HomeHeader from "../components/HomeHeader";
import HomeMainContent from "../components/HomeMainContent";
import HomeOverlays from "../components/HomeOverlays";
import { installHomeRuntime } from "../lib/homeRuntime";
import { getSavedSkinProfile } from "../lib/profileApi";
import { HomeFooter, HomeMatchResult } from "../components/HomeStaticSections";
import type { RecommendationProfile } from "../types/recommendation";

type HomeSection = {
  id: string;
  html: string;
};

type HomePageProps = {
  bodyHtml: string;
};

const HOME_SECTION_MARKERS = [
  "<!-- CART OVERLAY -->",
  "<!-- HEADER -->",
  "<!-- HERO -->",
  "<!-- MATCH RESULT SECTION -->",
  "<!-- MAIN CONTENT -->",
  "<!-- HOW IT WORKS -->",
  "<!-- INGREDIENTS -->",
  "<!-- FOOTER -->"
] as const;

const defaultRecommendationProfile: RecommendationProfile = {
  skin: "수부지",
  sensitivity: "보통",
  avoidIngredients: []
};

const splitHomeSections = (bodyHtml: string): HomeSection[] => {
  const sections: HomeSection[] = [];

  HOME_SECTION_MARKERS.forEach((marker, index) => {
    const startIndex = bodyHtml.indexOf(marker);
    if (startIndex === -1) {
      return;
    }

    const nextMarker = HOME_SECTION_MARKERS[index + 1];
    const endIndex = nextMarker
      ? bodyHtml.indexOf(nextMarker, startIndex + marker.length)
      : bodyHtml.length;

    sections.push({
      id: marker.replace(/[<>\-! ]/g, "").toLowerCase(),
      html: bodyHtml.slice(startIndex, endIndex === -1 ? bodyHtml.length : endIndex)
    });
  });

  return sections;
};

function HomePage({ bodyHtml }: HomePageProps) {
  const sections = splitHomeSections(bodyHtml);
  const [profile, setProfile] = useState<RecommendationProfile>(defaultRecommendationProfile);
  const [hasSavedProfile, setHasSavedProfile] = useState(false);

  useEffect(() => installHomeRuntime(profile), [profile]);

  useEffect(() => {
    let isMounted = true;

    getSavedSkinProfile().then((savedProfile) => {
      if (isMounted && savedProfile) {
        setProfile(savedProfile);
        setHasSavedProfile(true);
      }
    });

    return () => {
      isMounted = false;
    };
  }, []);

  return (
    <>
      {sections.map((section) =>
        section.id === "cartoverlay" ? (
          <HomeOverlays key={section.id} />
        ) : section.id === "header" ? (
          <HomeHeader key={section.id} />
        ) : section.id === "hero" ? (
          <HomeHero key={section.id} hasSavedProfile={hasSavedProfile} initialProfile={profile} />
        ) : section.id === "matchresultsection" ? (
          <HomeMatchResult key={section.id} />
        ) : section.id === "maincontent" ? (
          <HomeMainContent key={section.id} initialProfile={profile} />
        ) : section.id === "howitworks" || section.id === "ingredients" ? null : section.id ===
          "footer" ? (
          <HomeFooter key={section.id} />
        ) : (
          <div
            className="spa-origin-section"
            dangerouslySetInnerHTML={{ __html: section.html }}
            key={section.id}
          />
        )
      )}
    </>
  );
}

export default HomePage;
