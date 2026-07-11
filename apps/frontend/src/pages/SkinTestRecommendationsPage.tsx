import { useEffect, useMemo, useRef, useState } from "react";
import { useLocation, useNavigate, useSearchParams } from "react-router-dom";
import HomeHeader from "../components/HomeHeader";
import { useAuth } from "../contexts/useAuth";
import { addMyWishlistItem, deleteMyWishlistItem, getMyWishlist } from "../lib/activityApi";
import { api } from "../lib/api";
import {
  getLatestSkinTestResult,
  getSensitivityLabel,
  getSkinTestImageUrl,
  getSkinTypeLabel,
  saveLatestSkinTestResult,
} from "../lib/skinTest";
import type { HomeSectionProduct } from "../types/recommendation";
import type { SkinTestResult } from "../types/skinTest";

type SkinTestRecommendationsLocationState = {
  result?: SkinTestResult;
};

type RecommendationProduct = {
  product_id: string;
  brand: string;
  name: string;
  category_code: string;
  thumbnail_url: string | null;
  lowest_price: number | null;
  reason_summary: string;
  tags: string[];
  social_proof: string;
  style_reason: string;
};

type RecommendationSection = {
  id: string;
  title: string;
  subtitle: string;
  products: RecommendationProduct[];
  meta: "fit" | "popular" | "style";
};

const fallbackProducts: RecommendationProduct[] = [
  {
    product_id: "skin-fit-toner-1",
    brand: "Torriden",
    name: "다이브인 저분자 히알루론산 토너",
    category_code: "toner",
    thumbnail_url: null,
    lowest_price: 22000,
    reason_summary: "고보습 성분으로 속당김과 푸석함을 먼저 채워요.",
    tags: ["고보습", "장벽"],
    social_proof: "같은 타입 1,240명이 담았어요",
    style_reason: "대용량과 산뜻한 사용감을 함께 보는 스타일에게 맞아요.",
  },
  {
    product_id: "skin-fit-serum-1",
    brand: "Aestura",
    name: "아토베리어 세라마이드 수분 세럼",
    category_code: "serum",
    thumbnail_url: null,
    lowest_price: 28000,
    reason_summary: "장벽 케어 성분으로 건조한 결을 편안하게 잡아줘요.",
    tags: ["보습", "장벽"],
    social_proof: "같은 타입 980명이 비교했어요",
    style_reason: "성분표를 꼼꼼히 보는 사용자에게 좋은 장벽 세럼이에요.",
  },
  {
    product_id: "skin-fit-cream-1",
    brand: "Round Lab",
    name: "자작나무 수분 크림",
    category_code: "cream",
    thumbnail_url: null,
    lowest_price: 24000,
    reason_summary: "가벼운 보습막으로 당김을 오래 줄여줘요.",
    tags: ["수분", "진정"],
    social_proof: "같은 타입 1,560명이 찾았어요",
    style_reason: "끈적임보다 편안한 마무리를 선호할 때 좋아요.",
  },
  {
    product_id: "skin-fit-sunscreen-1",
    brand: "Dr.G",
    name: "그린 마일드 업 선 플러스",
    category_code: "sunscreen",
    thumbnail_url: null,
    lowest_price: 26000,
    reason_summary: "민감한 피부도 매일 쓰기 쉬운 자외선 케어예요.",
    tags: ["진정", "저자극"],
    social_proof: "같은 타입 860명이 저장했어요",
    style_reason: "자극 걱정이 큰 사용자에게 부담을 낮춘 선택이에요.",
  },
  {
    product_id: "skin-fit-toner-2",
    brand: "Bioderma",
    name: "하이드라비오 토너",
    category_code: "toner",
    thumbnail_url: null,
    lowest_price: 19000,
    reason_summary: "세안 후 건조한 피부에 수분 레이어를 빠르게 올려요.",
    tags: ["보습", "결케어"],
    social_proof: "같은 타입 740명이 재방문했어요",
    style_reason: "가격과 용량을 함께 보는 구매 스타일에 맞아요.",
  },
  {
    product_id: "skin-fit-serum-2",
    brand: "d'Alba",
    name: "비타 토닝 세럼",
    category_code: "serum",
    thumbnail_url: null,
    lowest_price: 32000,
    reason_summary: "칙칙함과 색소 고민을 밝은 톤 케어로 이어줘요.",
    tags: ["미백", "톤케어"],
    social_proof: "같은 타입 1,020명이 봤어요",
    style_reason: "효능 키워드가 분명한 제품을 찾을 때 어울려요.",
  },
  {
    product_id: "skin-fit-cream-2",
    brand: "Illiyoon",
    name: "세라마이드 아토 집중 크림",
    category_code: "cream",
    thumbnail_url: null,
    lowest_price: 21000,
    reason_summary: "건조한 장벽에 보습감을 차곡차곡 쌓아줘요.",
    tags: ["장벽", "고보습"],
    social_proof: "같은 타입 1,890명이 담았어요",
    style_reason: "가성비와 장벽 케어를 같이 챙기는 사용자에게 맞아요.",
  },
  {
    product_id: "skin-fit-sunscreen-2",
    brand: "Round Lab",
    name: "자작나무 수분 선크림",
    category_code: "sunscreen",
    thumbnail_url: null,
    lowest_price: 25000,
    reason_summary: "건조감 없이 데일리 자외선 차단을 이어가기 좋아요.",
    tags: ["수분", "데일리"],
    social_proof: "같은 타입 1,110명이 클릭했어요",
    style_reason: "보습감 있는 선케어를 찾는 사용자에게 맞아요.",
  },
  {
    product_id: "skin-fit-serum-3",
    brand: "Goodal",
    name: "청귤 비타C 잡티 케어 세럼",
    category_code: "serum",
    thumbnail_url: null,
    lowest_price: 30000,
    reason_summary: "색소침착과 칙칙함 고민에 밝은 인상을 더해줘요.",
    tags: ["미백", "잡티"],
    social_proof: "같은 타입 920명이 비교했어요",
    style_reason: "고민 키워드가 잡티 쪽으로 뚜렷할 때 보기 좋아요.",
  },
];

const formatPrice = (price: number | null) =>
  price === null ? "가격 정보 없음" : `${price.toLocaleString("ko-KR")}원`;

const getResultIdFromSearchParams = (searchParams: URLSearchParams) => {
  const resultId = Number(searchParams.get("result_id"));
  return Number.isFinite(resultId) && resultId > 0 ? resultId : null;
};

const mapHomeProduct = (product: HomeSectionProduct, index: number, typeCode: string): RecommendationProduct => ({
  product_id: product.product_id,
  brand: product.brand,
  name: product.name,
  category_code: product.category_code,
  thumbnail_url: product.thumbnail_url,
  lowest_price: product.lowest_price,
  reason_summary: product.reason_summary,
  tags: product.tags.length ? product.tags : product.badges,
  social_proof: `${typeCode} 타입 ${860 + index * 137}명이 확인했어요`,
  style_reason: product.badges.length
    ? `${product.badges.slice(0, 2).join(" · ")} 기준까지 함께 볼 수 있어요.`
    : "피부 키워드와 가격대를 함께 비교하기 좋아요.",
});

const takeProducts = (products: RecommendationProduct[], startIndex: number) => {
  const displayCount = 8;

  if (products.length <= displayCount) {
    return products;
  }

    return Array.from({ length: displayCount }, (_, index) => products[(startIndex + index) % products.length]);
};

const skeletonSections = [
  "내 피부에 잘 맞는 제품",
  "같은 타입이 많이 찾은 제품",
  "내 구매 스타일과 잘 맞는 제품",
];

function SkinTestRecommendationSkeleton() {
  return (
    <div className="skin-test-recommendation-sections" aria-hidden="true">
      {skeletonSections.map((title) => (
        <section className="skin-test-recommendation-section" key={title}>
          <div className="skin-test-recommendation-section__head">
            <div className="skin-test-recommendation-skeleton-head">
              <span className="skin-test-recommendation-skeleton-line skin-test-recommendation-skeleton-line--title skeleton-shimmer" />
              <span className="skin-test-recommendation-skeleton-line skin-test-recommendation-skeleton-line--subtitle skeleton-shimmer" />
            </div>
          </div>
          <div className="skin-test-recommendation-grid">
            {Array.from({ length: 8 }, (_, index) => (
              <article className="skin-test-recommendation-card skin-test-recommendation-card--skeleton" key={index}>
                <div className="skin-test-recommendation-card__image skeleton-shimmer" />
                <div className="skin-test-recommendation-card__body">
                  <span className="skin-test-recommendation-skeleton-line skin-test-recommendation-skeleton-line--brand skeleton-shimmer" />
                  <span className="skin-test-recommendation-skeleton-line skin-test-recommendation-skeleton-line--name skeleton-shimmer" />
                  <span className="skin-test-recommendation-skeleton-line skin-test-recommendation-skeleton-line--name-short skeleton-shimmer" />
                  <div className="skin-test-recommendation-skeleton-pills">
                    <span className="skin-test-recommendation-skeleton-pill skeleton-shimmer" />
                    <span className="skin-test-recommendation-skeleton-pill skeleton-shimmer" />
                  </div>
                  <span className="skin-test-recommendation-skeleton-line skin-test-recommendation-skeleton-line--price skeleton-shimmer" />
                </div>
              </article>
            ))}
          </div>
        </section>
      ))}
    </div>
  );
}

const buildSections = (
  products: RecommendationProduct[],
  typeCode: string,
  skinTypeLabel: string,
): RecommendationSection[] => [
  {
    id: "skin-fit",
    title: "내 피부에 잘 맞는 제품",
    subtitle: "피부 키워드와 효능을 기반으로 골랐어요",
    products: takeProducts(products, 0),
    meta: "fit",
  },
  {
    id: "type-popular",
    title: `${typeCode} 타입이 많이 찾은 제품`,
    subtitle: `나와 같은 ${skinTypeLabel} 피부타입 사용자들의 인기템이에요`,
    products: takeProducts(products, 3),
    meta: "popular",
  },
  {
    id: "purchase-style",
    title: "내 구매 스타일과 잘 맞는 제품",
    subtitle: "가격대와 취향을 반영했어요",
    products: takeProducts(products, 6),
    meta: "style",
  },
];

function SkinTestRecommendationsPage() {
  const navigate = useNavigate();
  const location = useLocation();
  const [searchParams] = useSearchParams();
  const { user } = useAuth();
  const locationState = location.state as SkinTestRecommendationsLocationState | null;
  const [result, setResult] = useState<SkinTestResult | null>(() => locationState?.result ?? getLatestSkinTestResult());
  const [products, setProducts] = useState<RecommendationProduct[]>(fallbackProducts);
  const [isResultLoading, setIsResultLoading] = useState(false);
  const [isProductsLoading, setIsProductsLoading] = useState(false);
  const [errorMessage, setErrorMessage] = useState("");
  const [wishedProductIds, setWishedProductIds] = useState<Set<string>>(() => new Set());
  const [pendingWishlistProductIds, setPendingWishlistProductIds] = useState<Set<string>>(() => new Set());
  const [toastMessage, setToastMessage] = useState("");
  const toastTimerRef = useRef<number | null>(null);
  const resultId = getResultIdFromSearchParams(searchParams) ?? result?.result_id ?? null;

  useEffect(() => () => {
    if (toastTimerRef.current !== null) {
      window.clearTimeout(toastTimerRef.current);
    }
  }, []);

  useEffect(() => {
    if (locationState?.result) {
      saveLatestSkinTestResult(locationState.result);
      return;
    }

    if (!resultId || result?.result_id === resultId) {
      return;
    }

    let isActive = true;

    const loadResult = async () => {
      setIsResultLoading(true);
      setErrorMessage("");

      try {
        const response = await api.getSkinTestResult(resultId);

        if (!isActive) {
          return;
        }

        setResult(response.result);
        saveLatestSkinTestResult(response.result);
      } catch {
        if (isActive) {
          setErrorMessage("피부 타입 결과를 불러오지 못했습니다.");
        }
      } finally {
        if (isActive) {
          setIsResultLoading(false);
        }
      }
    };

    void loadResult();

    return () => {
      isActive = false;
    };
  }, [locationState?.result, result?.result_id, resultId]);

  const typeCode = result?.type_code ?? "TYPE";
  const skinTypeLabel = getSkinTypeLabel(result?.skin_type);
  const sensitivityLabel = getSensitivityLabel(result?.sensitivity);
  const imageUrl = getSkinTestImageUrl(result?.image_storage_key);
  const headerTags = result?.recommended_effects.length
    ? result.recommended_effects.slice(0, 3)
    : ["보습", "진정", "장벽"];

  useEffect(() => {
    if (!result) {
      return;
    }

    let isActive = true;

    const loadProducts = async () => {
      setIsProductsLoading(true);

      try {
        const [marketPopular, forYou, evidencePicks] = await Promise.all([
          api.getMarketPopular({ limit: 12 }),
          api.getForYou({ skinType: skinTypeLabel, sensitivity: sensitivityLabel, limit: 12 }),
          api.getEvidencePicks({ limit: 12 }),
        ]);
        const nextProducts = [...marketPopular.products, ...forYou.products, ...evidencePicks.products].map(
          (product, index) => mapHomeProduct(product, index, typeCode),
        );

        if (isActive) {
          setProducts(nextProducts.length ? nextProducts : fallbackProducts);
        }
      } catch {
        if (isActive) {
          setProducts(fallbackProducts);
        }
      } finally {
        if (isActive) {
          setIsProductsLoading(false);
        }
      }
    };

    void loadProducts();

    return () => {
      isActive = false;
    };
  }, [result, sensitivityLabel, skinTypeLabel, typeCode]);

  useEffect(() => {
    if (!user) {
      return;
    }

    let isActive = true;

    getMyWishlist()
      .then((items) => {
        if (!isActive) return;
        setWishedProductIds(new Set(items.map((item) => item.productId)));
      })
      .catch(() => {
        if (isActive) setWishedProductIds(new Set());
      });

    return () => {
      isActive = false;
    };
  }, [user]);

  const recommendationProducts = products.length ? products : fallbackProducts;
  const sections = useMemo(
    () => buildSections(recommendationProducts, typeCode, skinTypeLabel),
    [recommendationProducts, skinTypeLabel, typeCode],
  );

  const openProduct = (productId: string) => {
    navigate(`/product-detail?id=${encodeURIComponent(productId)}`);
  };

  const showToast = (message: string) => {
    setToastMessage(message);
    if (toastTimerRef.current !== null) {
      window.clearTimeout(toastTimerRef.current);
    }
    toastTimerRef.current = window.setTimeout(() => {
      setToastMessage("");
      toastTimerRef.current = null;
    }, 2500);
  };

  const toggleWishlist = async (productId: string) => {
    if (pendingWishlistProductIds.has(productId)) {
      return;
    }

    if (!user) {
      navigate("/login", { state: { from: window.location.pathname + window.location.search } });
      return;
    }

    const wasWished = wishedProductIds.has(productId);
    setPendingWishlistProductIds((current) => new Set(current).add(productId));
    setWishedProductIds((current) => {
      const next = new Set(current);
      if (wasWished) {
        next.delete(productId);
      } else {
        next.add(productId);
      }
      return next;
    });

    try {
      if (wasWished) {
        await deleteMyWishlistItem(productId);
        showToast("찜한 상품에서 해제했습니다.");
      } else {
        await addMyWishlistItem(productId);
        showToast("찜한 상품에 추가했습니다.");
      }
    } catch {
      setWishedProductIds((current) => {
        const next = new Set(current);
        if (wasWished) {
          next.add(productId);
        } else {
          next.delete(productId);
        }
        return next;
      });
      showToast("찜 처리에 실패했습니다. 잠시 후 다시 시도해주세요.");
    } finally {
      setPendingWishlistProductIds((current) => {
        const next = new Set(current);
        next.delete(productId);
        return next;
      });
    }
  };

  return (
    <div className="skin-test-shell">
      <HomeHeader />
      <main className="skin-test-recommendation-main">
        <section className="skin-test-recommendation-page">
          <div className="skin-test-recommendation-hero">
            <div className="skin-test-recommendation-hero__visual" aria-hidden="true">
              {imageUrl ? <img src={imageUrl} alt="" /> : <span>{typeCode}</span>}
            </div>
            <div>
              <h1>
                <span>{typeCode} 타입</span>을 위한 큐레이션
              </h1>
              <p>
                {skinTypeLabel} · 민감도 {sensitivityLabel} 기준으로 지금 보기 좋은 상품을 모았어요.
              </p>
              <div className="skin-test-recommendation-tags">
                {headerTags.map((tag) => (
                  <span key={tag}>#{tag}</span>
                ))}
              </div>
            </div>
          </div>

          {isResultLoading ? (
            <SkinTestRecommendationSkeleton />
          ) : errorMessage && !result ? (
            <div className="skin-test-state">
              <p>{errorMessage}</p>
              <button className="skin-test-primary-button" onClick={() => navigate("/skin-test")} type="button">
                테스트 시작하기
              </button>
            </div>
          ) : isProductsLoading ? (
            <SkinTestRecommendationSkeleton />
          ) : (
            <div className="skin-test-recommendation-sections" aria-busy={isProductsLoading}>
              {sections.map((section) => (
                <section className="skin-test-recommendation-section" key={section.id}>
                  <div className="skin-test-recommendation-section__head">
                    <div>
                      <h2>{section.title}</h2>
                      <p>{section.subtitle}</p>
                    </div>
                  </div>

                  <div className="skin-test-recommendation-grid">
                    {section.products.map((product, index) => {
                        const isWished = wishedProductIds.has(product.product_id);
                        const isPending = pendingWishlistProductIds.has(product.product_id);

                        return (
                          <article
                            className="skin-test-recommendation-card"
                            key={`${section.id}-${product.product_id}-${index}`}
                            onClick={() => openProduct(product.product_id)}
                            onKeyDown={(event) => {
                              if (event.key === "Enter" || event.key === " ") {
                                event.preventDefault();
                                openProduct(product.product_id);
                              }
                            }}
                            role="link"
                            tabIndex={0}
                          >
                            <div className="skin-test-recommendation-card__image">
                              <button
                                aria-label={isWished ? `${product.name} 찜 해제` : `${product.name} 찜하기`}
                                aria-pressed={isWished}
                                className={`skin-test-recommendation-card__heart${isWished ? " is-wished" : ""}`}
                                disabled={isPending}
                                onClick={(event) => {
                                  event.stopPropagation();
                                  void toggleWishlist(product.product_id);
                                }}
                                onKeyDown={(event) => {
                                  if (event.key === "Enter" || event.key === " ") {
                                    event.stopPropagation();
                                  }
                                }}
                                type="button"
                              >
                                <svg
                                  aria-hidden="true"
                                  fill={isWished ? "currentColor" : "none"}
                                  height="26"
                                  stroke="currentColor"
                                  strokeLinecap="round"
                                  strokeLinejoin="round"
                                  strokeWidth="2.3"
                                  viewBox="0 0 24 24"
                                  width="26"
                                >
                                  <path d="M20.84 4.61a5.5 5.5 0 0 0-7.78 0L12 5.67l-1.06-1.06a5.5 5.5 0 0 0-7.78 7.78L12 21.23l7.78-8.84a5.5 5.5 0 0 0 1.06-7.78z" />
                                </svg>
                              </button>
                              {product.thumbnail_url ? (
                                <img src={product.thumbnail_url} alt="" loading="lazy" />
                              ) : (
                                <span>뭐바를래</span>
                              )}
                            </div>
                            <div className="skin-test-recommendation-card__body">
                              <p className="skin-test-recommendation-card__brand">{product.brand}</p>
                              <h3>{product.name}</h3>
                              <div className="skin-test-recommendation-card__tags">
                                {product.tags.slice(0, 3).map((tag) => (
                                  <span key={tag}>{tag}</span>
                                ))}
                              </div>
                              <p className="skin-test-recommendation-card__price">{formatPrice(product.lowest_price)}</p>
                            </div>
                          </article>
                        );
                    })}
                  </div>
                </section>
              ))}
            </div>
          )}
        </section>
      </main>
      {toastMessage ? (
        <div className="activity-toast" role="status" aria-live="polite">
          <span className="activity-toast__dot" />
          {toastMessage}
        </div>
      ) : null}
    </div>
  );
}

export default SkinTestRecommendationsPage;
