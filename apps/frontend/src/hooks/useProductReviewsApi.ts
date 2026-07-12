import { useEffect, useMemo, useState } from "react";
import { API_BASE_URL, fetchWithTimeout, parseJson } from "../lib/api";
import { getStaticAssetUrl } from "../lib/imageUrls";
import type { ProductReviewSummary as ApiReviewSummary } from "../types/recommendation";
import type { ProductReview, ProductReviewSummary } from "./useProductReviews";

type ApiReviewProfileLabel = {
  dimension: string;
  value_code: string;
  display_label: string;
};

type ApiReviewItem = {
  review_id: string;
  rating: number | null;
  review_text: string | null;
  reviewed_at: string | null;
  option_text: string | null;
  review_type: string | null;
  is_repurchase_review: boolean | null;
  helpful_count: number;
  author: { display_name: string; profile_image_url: string | null } | null;
  profile_labels: ApiReviewProfileLabel[];
  media: { media_type: string; url: string }[];
};

type ApiProductReviewsResponse = {
  product_id: string;
  sort: string;
  limit: number;
  items: ApiReviewItem[];
  next_cursor: string | null;
  has_next: boolean;
};

const emptyRatingDistribution: ProductReviewSummary["ratingDistribution"] = {
  1: 0,
  2: 0,
  3: 0,
  4: 0,
  5: 0,
};

const getLabel = (labels: ApiReviewProfileLabel[], dimension: string) =>
  labels.find((label) => label.dimension === dimension)?.display_label ?? "";

const mapReview = (review: ApiReviewItem): ProductReview => {
  const nickname = review.author?.display_name?.trim() || "구매 고객";
  const concerns = review.profile_labels
    .filter((label) => label.dimension === "SKIN_CONCERN")
    .map((label) => label.display_label);

  return {
    id: review.review_id,
    nickname,
    initial: nickname.slice(0, 1),
    skinType: getLabel(review.profile_labels, "SKIN_TYPE") || "피부 타입 미등록",
    skinTone: getLabel(review.profile_labels, "SKIN_TONE"),
    concerns,
    irritation: "low",
    rating: review.rating ?? 0,
    createdAt: review.reviewed_at?.slice(0, 10) ?? "",
    optionName: review.option_text || "구매 옵션 정보 없음",
    body: review.review_text || "작성된 리뷰 내용이 없습니다.",
    photos: review.media.map((media) => getStaticAssetUrl(media.url)).filter(Boolean),
    likeCount: review.helpful_count,
    isRepurchase: review.is_repurchase_review === true,
    usedOverMonth: review.review_type === "MONTH_USE",
  };
};

const buildSummary = (summary?: ApiReviewSummary): ProductReviewSummary => {
  if (!summary) {
    return {
      averageRating: 0,
      totalCount: 0,
      ratingDistribution: emptyRatingDistribution,
      stats: [],
    };
  }

  const repurchasePercent =
    summary.repurchase_rate === null ? 0 : Math.round(summary.repurchase_rate * 100);

  return {
    averageRating: summary.average_rating ?? 0,
    totalCount: summary.review_count,
    ratingDistribution: {
      1: summary.rating_distribution["1"] ?? 0,
      2: summary.rating_distribution["2"] ?? 0,
      3: summary.rating_distribution["3"] ?? 0,
      4: summary.rating_distribution["4"] ?? 0,
      5: summary.rating_distribution["5"] ?? 0,
    },
    stats: [
      { label: "일반 리뷰", text: `${summary.general_review_count}개`, percent: summary.review_count ? Math.round((summary.general_review_count / summary.review_count) * 100) : 0 },
      { label: "한달 사용", text: `${summary.month_use_review_count}개`, percent: summary.review_count ? Math.round((summary.month_use_review_count / summary.review_count) * 100) : 0 },
      { label: "재구매", text: summary.repurchase_rate === null ? "정보 없음" : `${repurchasePercent}%`, percent: repurchasePercent },
    ],
  };
};

export const useProductReviewsApi = (
  productId: string | null | undefined,
  summary?: ApiReviewSummary,
) => {
  const [reviews, setReviews] = useState<ProductReview[]>([]);

  useEffect(() => {
    if (!productId) {
      return;
    }

    let isMounted = true;
    const params = new URLSearchParams({ limit: "50", sort: "helpful" });

    fetchWithTimeout(
      `${API_BASE_URL}/products/${encodeURIComponent(productId)}/reviews?${params.toString()}`,
    )
      .then((response) => parseJson<ApiProductReviewsResponse>(response))
      .then((response) => {
        if (isMounted) setReviews(response.items.map(mapReview));
      })
      .catch(() => {
        if (isMounted) setReviews([]);
      });

    return () => {
      isMounted = false;
    };
  }, [productId]);

  return useMemo(
    () => ({ reviews: productId ? reviews : [], summary: buildSummary(summary) }),
    [productId, reviews, summary],
  );
};
