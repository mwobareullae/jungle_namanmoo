import type { SkinTestResult } from "../types/skinTest";

export const SKIN_TEST_LATEST_RESULT_STORAGE_KEY = "skinTestLatestResult";

const imageCdnBaseUrl = (import.meta.env.VITE_IMAGE_CDN_BASE_URL ?? "").replace(/\/$/, "");

export const getSkinTestImageUrl = (storageKey?: string | null, size: "w400" | "w1200" = "w400") => {
  if (!imageCdnBaseUrl || !storageKey) {
    return "";
  }

  return `${imageCdnBaseUrl}/resized/${size}/${storageKey.replace(/^\//, "")}`;
};

export const saveLatestSkinTestResult = (result: SkinTestResult) => {
  sessionStorage.setItem(SKIN_TEST_LATEST_RESULT_STORAGE_KEY, JSON.stringify(result));
};

export const getLatestSkinTestResult = () => {
  const rawResult = sessionStorage.getItem(SKIN_TEST_LATEST_RESULT_STORAGE_KEY);

  if (!rawResult) {
    return null;
  }

  try {
    return JSON.parse(rawResult) as SkinTestResult;
  } catch {
    sessionStorage.removeItem(SKIN_TEST_LATEST_RESULT_STORAGE_KEY);
    return null;
  }
};

export const skinTypeLabels: Record<string, string> = {
  dry: "건성",
  oily: "지성",
  combination: "복합성",
  water_oil: "수부지",
  normal: "중성",
  건성: "건성",
  지성: "지성",
  복합성: "복합성",
  수부지: "수부지",
  중성: "중성",
};

export const sensitivityLabels: Record<string, string> = {
  low: "낮음",
  mid: "보통",
  medium: "보통",
  high: "높음",
  낮음: "낮음",
  보통: "보통",
  높음: "높음",
};

export const getSkinTypeLabel = (value?: string | null) => {
  if (!value) {
    return "분석 중";
  }

  return skinTypeLabels[value] ?? value;
};

export const getSensitivityLabel = (value?: string | null) => {
  if (!value) {
    return "분석 중";
  }

  return sensitivityLabels[value] ?? value;
};
