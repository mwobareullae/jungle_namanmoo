import { useEffect, useState } from "react";
import HomeHero from "../components/HomeHero";
import HomeHeader from "../components/HomeHeader";
import HomeMainContent from "../components/HomeMainContent";
import HomeOverlays from "../components/HomeOverlays";
import SkinTestPromptModal from "../components/SkinTestPromptModal";
import { useAuth } from "../contexts/useAuth";
import { useSkinProfileQuery } from "../hooks/useSkinProfileQuery";
import { HomeMatchResult } from "../components/HomeStaticSections";
import { installHomeRuntime } from "../lib/homeRuntime";
import { toRecommendationProfile } from "../lib/profileApi";
import { consumeSkinTestPromptPending, hasDismissedSkinTestPrompt } from "../lib/skinTestPrompt";
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
  const { isAuthLoading, user } = useAuth();
  const skinProfileQuery = useSkinProfileQuery(user?.id ?? null, !isAuthLoading && Boolean(user));
  const [profile, setProfile] = useState<RecommendationProfile>(defaultRecommendationProfile);
  const [hasSavedProfile, setHasSavedProfile] = useState(false);
  const [isProfileLoading, setIsProfileLoading] = useState(true);
  const [isSkinTestPromptOpen, setIsSkinTestPromptOpen] = useState(false);

  useEffect(() => installHomeRuntime(profile), [profile]);

  useEffect(() => {
    if (isAuthLoading) {
      return;
    }

    if (!user) {
      const timerId = window.setTimeout(() => {
        setProfile(defaultRecommendationProfile);
        setHasSavedProfile(false);
        setIsProfileLoading(false);
      }, 0);

      return () => window.clearTimeout(timerId);
    }

    if (skinProfileQuery.isPending) {
      const timerId = window.setTimeout(() => setIsProfileLoading(true), 0);
      return () => window.clearTimeout(timerId);
    }

    const savedProfile = skinProfileQuery.data ? toRecommendationProfile(skinProfileQuery.data) : null;
    const timerId = window.setTimeout(() => {
      setProfile(savedProfile ?? defaultRecommendationProfile);
      setHasSavedProfile(Boolean(savedProfile));
      setIsProfileLoading(false);
    }, 0);
    return () => window.clearTimeout(timerId);
  }, [isAuthLoading, skinProfileQuery.data, skinProfileQuery.isPending, user]);

  useEffect(() => {
    if (!user) {
      return;
    }

    const shouldPrompt = consumeSkinTestPromptPending();

    if (shouldPrompt && !hasDismissedSkinTestPrompt()) {
      const promptTimer = window.setTimeout(() => {
        setIsSkinTestPromptOpen(true);
      }, 0);

      return () => window.clearTimeout(promptTimer);
    }
  }, [user]);

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
          <HomeMainContent
            key={section.id}
            initialProfile={profile}
            showForYouSkinTypeFilters={
              !isAuthLoading && !isProfileLoading && (!user || !hasSavedProfile)
            }
          />
        ) : section.id === "howitworks" || section.id === "ingredients" ? null : section.id ===
          "footer" ? null : (
          <div
            className="spa-origin-section"
            dangerouslySetInnerHTML={{ __html: section.html }}
            key={section.id}
          />
        )
      )}
      {isSkinTestPromptOpen && (
        <SkinTestPromptModal onClose={() => setIsSkinTestPromptOpen(false)} />
      )}
    </>
  );
}

export default HomePage;
