import { useEffect, useMemo, useRef, useState } from "react";
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
  verified_purchase: boolean | null;
  helpful_count: number;
  updated_at: string | null;
  is_mine: boolean;
  can_edit: boolean;
  can_delete: boolean;
  badges: string[];
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

const PRODUCT_REVIEWS_CACHE_TTL_MS = 45_000;
const productReviewsCache = new Map<string, { value: ApiProductReviewsResponse; expiresAt: number }>();
const productReviewsRequests = new Map<string, Promise<ApiProductReviewsResponse>>();

export const invalidateProductReviews = (productId: string | null | undefined) => {
  if (!productId) return;
  const prefix = `${productId}?`;
  for (const key of productReviewsCache.keys()) {
    if (key.startsWith(prefix)) productReviewsCache.delete(key);
  }
};

export type ProductReviewsQuery = {
  append?: boolean;
  cursor?: string | null;
  sort?: "latest" | "helpful" | "rating_high" | "rating_low";
  reviewType?: "GENERAL" | "MONTH_USE";
  repurchase?: boolean;
  skinType?: string | null;
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
    verifiedPurchase: review.verified_purchase,
    updatedAt: review.updated_at,
    isMine: review.is_mine,
    badges: review.badges,
    author: review.author
      ? { displayName: review.author.display_name, profileImageUrl: review.author.profile_image_url }
      : null,
    profileLabels: review.profile_labels.map((label) => ({
      dimension: label.dimension,
      valueCode: label.value_code,
      displayLabel: label.display_label,
    })),
    media: review.media.map((media) => ({
      mediaType: media.media_type,
      url: media.url,
    })),
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
  query: ProductReviewsQuery = {},
) => {
  const [reviews, setReviews] = useState<ProductReview[]>([]);
  const [hasNext, setHasNext] = useState(false);
  const [nextCursor, setNextCursor] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(Boolean(productId));
  const [errorMessage, setErrorMessage] = useState("");
  const loadedQueryKeyRef = useRef<string | null>(null);

  useEffect(() => {
    let isMounted = true;
    if (!productId) {
      queueMicrotask(() => {
        if (!isMounted) return;
        setReviews([]);
        setHasNext(false);
        setNextCursor(null);
        setIsLoading(false);
        loadedQueryKeyRef.current = null;
      });
      return () => {
        isMounted = false;
      };
    }

    const params = new URLSearchParams({ limit: "10", sort: query.sort ?? "helpful" });
    if (query.cursor) params.set("cursor", query.cursor);
    if (query.reviewType) params.set("review_type", query.reviewType);
    if (query.repurchase !== undefined) params.set("repurchase", String(query.repurchase));
    if (query.skinType) params.set("skin_type", query.skinType);
    const queryKey = `${productId}?sort=${query.sort ?? "helpful"}&review_type=${query.reviewType ?? ""}&repurchase=${query.repurchase ?? ""}&skin_type=${query.skinType ?? ""}`;
    queueMicrotask(() => {
      if (!isMounted) return;
      setIsLoading(true);
      setErrorMessage("");
    });

    const cacheKey = `${productId}?${params.toString()}`;
    const cached = productReviewsCache.get(cacheKey);
    const pending = productReviewsRequests.get(cacheKey);
    const isFresh = Boolean(cached && cached.expiresAt > Date.now());
    const request = isFresh
      ? Promise.resolve(cached!.value)
      : pending ?? fetchWithTimeout(
          `${API_BASE_URL}/products/${encodeURIComponent(productId)}/reviews?${params.toString()}`,
        ).then((response) => parseJson<ApiProductReviewsResponse>(response));
    if (!isFresh && !pending) productReviewsRequests.set(cacheKey, request);

    request
      .then((response) => {
        if (!isFresh) productReviewsCache.set(cacheKey, { value: response, expiresAt: Date.now() + PRODUCT_REVIEWS_CACHE_TTL_MS });
        if (isMounted) {
          const nextReviews = response.items.map(mapReview);
          const shouldAppend = query.append === true && Boolean(query.cursor) && loadedQueryKeyRef.current === queryKey;
          setReviews((current) => {
            if (!shouldAppend) return nextReviews;

            const existingIds = new Set(current.map((review) => review.id));
            return [...current, ...nextReviews.filter((review) => !existingIds.has(review.id))];
          });
          loadedQueryKeyRef.current = queryKey;
          setHasNext(response.has_next);
          setNextCursor(response.next_cursor);
        }
      })
      .catch((error) => {
        if (isMounted) {
          setReviews([]);
          setHasNext(false);
          setNextCursor(null);
          setErrorMessage(error instanceof Error ? error.message : "리뷰를 불러오지 못했습니다.");
        }
      })
      .finally(() => {
        if (productReviewsRequests.get(cacheKey) === request) productReviewsRequests.delete(cacheKey);
        if (isMounted) setIsLoading(false);
      });

    return () => {
      isMounted = false;
    };
  }, [productId, query.append, query.cursor, query.repurchase, query.reviewType, query.skinType, query.sort]);

  return useMemo(
    () => ({
      reviews: productId ? reviews : [],
      summary: buildSummary(summary),
      hasNext,
      nextCursor,
      isLoading,
      errorMessage,
    }),
    [productId, reviews, summary, hasNext, nextCursor, isLoading, errorMessage],
  );
};
