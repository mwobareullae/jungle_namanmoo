import { useEffect, useMemo, useState } from "react";
import HomeHeader from "../components/HomeHeader";
import { api } from "../lib/api";
import { getFallbackProductDetail } from "../lib/fallbackProducts";
import { installHomeRuntime } from "../lib/homeRuntime";
import type { IngredientEvidence, ProductDetail } from "../types/recommendation";

const formatPrice = (price: number | null) =>
  price === null ? "가격 정보 없음" : `${price.toLocaleString("ko-KR")}원`;

const confidenceLabel: Record<ProductDetail["content_confidence"], string> = {
  high: "높음",
  medium: "보통",
  low: "낮음",
  unknown: "확인 필요",
};

const evidenceLevelLabel: Record<IngredientEvidence["evidence_level"], string> = {
  high: "근거 높음",
  medium: "근거 보통",
  low: "근거 낮음",
};

const getDetailParams = () => {
  const params = new URLSearchParams(window.location.search);
  return {
    productId: params.get("id") ?? "",
    recommendationId: params.get("recommendation_id") ?? undefined,
    skinType: params.get("skin_type") ?? "",
    sensitivity: params.get("sensitivity") ?? "",
  };
};

const getEffectIcon = (effect: string) => {
  if (effect.includes("미백") || effect.includes("톤")) return "!";
  if (effect.includes("주름") || effect.includes("탄력")) return "↻";
  if (effect.includes("여드름") || effect.includes("피지") || effect.includes("모공")) return "●";
  if (effect.includes("보습") || effect.includes("장벽")) return "◆";
  return "•";
};

const getEffectLabel = (effect: string) => {
  if (effect.includes("미백") || effect.includes("톤")) return "피부 미백에 도움되는 기능성 성분";
  if (effect.includes("주름") || effect.includes("탄력")) return "주름 개선에 도움되는 기능성 성분";
  if (effect.includes("여드름") || effect.includes("피지")) return "여드름·피지 케어에 연결된 성분";
  if (effect.includes("모공")) return "모공 케어에 연결된 성분";
  if (effect.includes("보습")) return "보습에 도움되는 성분";
  return `${effect} 효능과 연결된 성분`;
};

const getPurchaseOptions = (product: ProductDetail) => {
  if (product.prices.length > 0) return product.prices.slice(0, 8);
  if (!product.purchase_url || product.lowest_price === null) return [];

  return [{
    mall_name: "구매처",
    price: product.lowest_price,
    product_url: product.purchase_url,
    is_lowest: true,
  }];
};

const isCommunityMode = import.meta.env.VITE_APP_MODE === "community";
const normalizeDetailHash = (hash: string) =>
  isCommunityMode && hash === "#related" ? "#summary" : hash || "#summary";

function ProductDetailSpaPage() {
  const [{ productId, recommendationId, skinType, sensitivity }] = useState(getDetailParams);
  const [product, setProduct] = useState<ProductDetail | null>(null);
  const [isLoading, setIsLoading] = useState(Boolean(productId));
  const [errorMessage, setErrorMessage] = useState("");
  const [activeTab, setActiveTab] = useState(() => normalizeDetailHash(window.location.hash));
  const [selectedEffect, setSelectedEffect] = useState<{
    icon: string;
    label: string;
    items: IngredientEvidence[];
  } | null>(null);

  useEffect(() => installHomeRuntime(), []);

  useEffect(() => {
    const handleHashChange = () => {
      const normalizedHash = normalizeDetailHash(window.location.hash);
      setActiveTab(normalizedHash);
      if (normalizedHash !== window.location.hash) {
        window.history.replaceState(null, "", `${window.location.pathname}${window.location.search}${normalizedHash}`);
      }
    };
    handleHashChange();
    window.addEventListener("hashchange", handleHashChange);
    return () => window.removeEventListener("hashchange", handleHashChange);
  }, []);

  useEffect(() => {
    if (!productId) {
      setErrorMessage("상품 정보를 찾을 수 없습니다.");
      setIsLoading(false);
      return;
    }

    let isMounted = true;
    setIsLoading(true);
    api.getProduct(productId, recommendationId)
      .then((response) => {
        if (isMounted) setProduct(response);
      })
      .catch(() => {
        if (!isMounted) return;
        const fallbackProduct = getFallbackProductDetail(productId);
        if (fallbackProduct) {
          setProduct(fallbackProduct);
          setErrorMessage("");
          return;
        }
        setErrorMessage("상품 상세 정보를 불러오지 못했습니다.");
      })
      .finally(() => {
        if (isMounted) setIsLoading(false);
      });

    return () => {
      isMounted = false;
    };
  }, [productId, recommendationId]);

  const detailData = useMemo(() => {
    if (!product) return null;

    const relatedIngredients =
      product.related_ingredients.length > 0 ? product.related_ingredients : product.key_ingredients;
    const effectiveIngredients = Array.from(
      new Set(product.evidence.map((item) => item.ingredient_name).filter(Boolean)),
    );
    const effectGroups = Array.from(new Set(product.evidence.map((item) => item.effect_name).filter(Boolean)))
      .map((effect) => ({
        effect,
        icon: getEffectIcon(effect),
        label: getEffectLabel(effect),
        items: product.evidence.filter((item) => item.effect_name === effect),
      }))
      .filter((group) => group.items.length > 0);

    return {
      relatedIngredients,
      effectiveIngredients,
      effectGroups,
      purchaseOptions: getPurchaseOptions(product),
    };
  }, [product]);

  const tabClassName = (hash: string) => `detail-tab${activeTab === hash ? " active" : ""}`;
  const checkoutQuery = useMemo(() => {
    const params = new URLSearchParams({ id: productId });
    if (recommendationId) params.set("recommendation_id", recommendationId);
    if (skinType) params.set("skin_type", skinType);
    if (sensitivity) params.set("sensitivity", sensitivity);
    return params;
  }, [productId, recommendationId, skinType, sensitivity]);

  const goToCheckout = (mode: "cart" | "buy") => {
    const params = new URLSearchParams(checkoutQuery);
    params.set("mode", mode);
    window.location.href = `/checkout?${params.toString()}`;
  };

  return (
    <>
      <HomeHeader />
      <main className="detail-page">
        <section className="detail-shell">
          <div className="detail-breadcrumb">
            <a href="/">홈</a>
            <span>/</span>
            <span>스킨케어</span>
            <span>/</span>
            <span id="breadcrumbProduct">{product?.name ?? "상품 상세"}</span>
          </div>

          {isLoading ? (
            <div className="detail-loading">상품 상세 정보를 불러오는 중입니다.</div>
          ) : errorMessage ? (
            <div className="detail-loading">{errorMessage}</div>
          ) : product ? (
            <div className="detail-hero">
              <div className="detail-media">
                <div className="detail-image-box">
                  {product.thumbnail_url ? (
                    <img id="productImage" src={product.thumbnail_url} alt={product.name} />
                  ) : null}
                  {!product.thumbnail_url ? (
                    <div className="detail-image-empty" id="productImageEmpty">이미지 준비중</div>
                  ) : null}
                </div>
                <div className="detail-image-gallery" id="productImageGallery">
                  {product.image_urls.slice(0, 6).map((imageUrl, index) => (
                    <button
                      className={`detail-thumb${index === 0 ? " active" : ""}`}
                      type="button"
                      key={imageUrl}
                    >
                      <img src={imageUrl} alt="" loading="lazy" />
                    </button>
                  ))}
                </div>
              </div>

              <div className="detail-summary">
                <div className="detail-brand-row">
                  <div className="detail-brand" id="productBrand">{product.brand}</div>
                  <div className="detail-actions">
                    <button className="detail-icon-btn" type="button" aria-label="공유">
                      <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                        <circle cx="18" cy="5" r="3" />
                        <circle cx="6" cy="12" r="3" />
                        <circle cx="18" cy="19" r="3" />
                        <path d="M8.59 13.51 15.42 17.49M15.41 6.51 8.59 10.49" />
                      </svg>
                    </button>
                    <button data-commerce-only className="detail-icon-btn" type="button" aria-label="찜">
                      <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                        <path d="M20.84 4.61a5.5 5.5 0 0 0-7.78 0L12 5.67l-1.06-1.06a5.5 5.5 0 0 0-7.78 7.78L12 21.23l7.78-8.84a5.5 5.5 0 0 0 1.06-7.78z" />
                      </svg>
                    </button>
                  </div>
                </div>
                <h1 className="detail-title" id="productName">{product.name}</h1>
                <div className="detail-rating">
                  <span id="reviewSummary">{formatPrice(product.lowest_price)}</span>
                </div>
                <div className="detail-price-panel">
                  <div className="detail-price-row">
                    <span className="detail-price" id="productPrice">{formatPrice(product.lowest_price)}</span>
                  </div>
                </div>
                <div className="detail-tags" id="productTags">
                  {product.evidence_tags.map((tag) => (
                    <span className="detail-tag" key={tag}>{tag}</span>
                  ))}
                </div>
                <div className="detail-match">
                  <div className="detail-match-score" id="matchScore">{product.total_score}</div>
                  <div>
                    <strong>내 피부 고민 기준 추천 근거</strong>
                    <p id="matchReason">{product.reason_summary}</p>
                  </div>
                </div>
                <div className="detail-score-breakdown" id="detailScoreBreakdown">
                  {product.score_breakdown ? (
                    <>
                      <div className="detail-score-title">추천 점수 세부 기준</div>
                      <div className="detail-score-chip-list">
                        <span className="detail-score-chip">
                          <b>성분 효능</b>
                          {product.score_breakdown.ingredient_effect_score}점
                        </span>
                        <span className="detail-score-chip">
                          <b>성분 근거</b>
                          {product.score_breakdown.ingredient_evidence_score}점
                        </span>
                        <span className="detail-score-chip">
                          <b>피부 타입</b>
                          {product.score_breakdown.skin_type_match_score}점
                        </span>
                        <span className="detail-score-chip">
                          <b>가격</b>
                          {product.score_breakdown.price_value_score}점
                        </span>
                        <span className="detail-score-chip">
                          <b>검색 매칭</b>
                          {product.score_breakdown.search_match_score}점
                        </span>
                      </div>
                    </>
                  ) : null}
                </div>
                <div
                  className="detail-selectors"
                  id="profileSelectors"
                  style={{ display: skinType || sensitivity ? undefined : "none" }}
                >
                  <div className="detail-select-row" id="skinTypeRow" style={{ display: skinType ? undefined : "none" }}>
                    <span>피부 타입</span>
                    <strong id="skinTypeValue">{skinType}</strong>
                  </div>
                  <div className="detail-select-row" id="sensitivityRow" style={{ display: sensitivity ? undefined : "none" }}>
                    <span>민감성</span>
                    <strong id="sensitivityValue">{sensitivity}</strong>
                  </div>
                </div>
                <div data-commerce-only className="detail-cta-row">
                  <button className="detail-btn" type="button" onClick={() => goToCheckout("cart")}>장바구니</button>
                  <button className="detail-btn primary" type="button" onClick={() => goToCheckout("buy")}>구매하기</button>
                </div>
              </div>
            </div>
          ) : null}
        </section>

        {product && detailData ? (
          <>
            <nav className="detail-tabs" aria-label="상품 상세 탭">
              <a className={tabClassName("#summary")} href="#summary">요약</a>
              <a className={tabClassName("#reviews")} href="#reviews">성분</a>
              <a className={tabClassName("#ingredients")} href="#ingredients">성분 근거</a>
              <a data-commerce-only className={tabClassName("#related")} href="#related">구매처</a>
            </nav>

            <section className="detail-sections">
              <section className="detail-section" id="summary">
                <div className="section-kicker">Product Summary</div>
                <h2>피부 고민과 성분 근거를 함께 보는 상세 정보</h2>
                <div className="evidence-grid" id="summaryGrid">
                  <article className="evidence-card">
                    <strong>추천 점수 {product.total_score}</strong>
                    <p>{product.reason_summary || "피부 고민 기준 추천 근거를 확인했습니다."}</p>
                  </article>
                  <article className="evidence-card">
                    <strong>함량 신뢰도 {confidenceLabel[product.content_confidence]}</strong>
                    <p>성분 근거와 상품 정보를 함께 확인해 추천에 반영했습니다.</p>
                  </article>
                  <article className="evidence-card">
                    <strong>{formatPrice(product.lowest_price)}</strong>
                    <p>현재 확인 가능한 가격 정보를 함께 표시합니다.</p>
                  </article>
                </div>
              </section>

              <section className="detail-section" id="reviews">
                <div className="section-kicker">Ingredients</div>
                <h2>성분 정보</h2>
                <div className="review-ingredient-layout ingredients-only">
                  <div className="ingredient-panel">
                    <div className="ingredient-stat-grid">
                      <div className="ingredient-stat stat-total">
                        <strong id="totalIngredientCount">{detailData.relatedIngredients.length || "-"}</strong>
                        <span>전체 성분</span>
                      </div>
                      <div className="ingredient-stat stat-effective">
                        <strong id="effectiveIngredientCount">{detailData.effectiveIngredients.length}</strong>
                        <span>효능 성분</span>
                      </div>
                      <div className="ingredient-stat stat-risk">
                        <strong id="riskIngredientCount">{product.risk_flags.length}</strong>
                        <span>주의 성분</span>
                      </div>
                    </div>
                    <div className="effect-toggle-list" id="effectToggleList">
                      {detailData.effectGroups.length > 0 ? (
                        <>
                          <div className="effect-toggle-title">목적별 성분</div>
                          {detailData.effectGroups.map((group) => (
                            <button
                              className="effect-toggle-row"
                              type="button"
                              onClick={() => setSelectedEffect(group)}
                              key={group.effect}
                            >
                              <span className="effect-toggle-icon">{group.icon}</span>
                              <span>{group.label}</span>
                              <strong>{group.items.length}</strong>
                              <span className="effect-toggle-caret">⌄</span>
                            </button>
                          ))}
                        </>
                      ) : null}
                    </div>
                    <div className="ingredient-tags" id="ingredientTags">
                      <div className="ingredient-tag-group">
                        <div className="ingredient-tag-label">효능 성분</div>
                        <div className="ingredient-tag-list">
                          {detailData.effectiveIngredients.length > 0 ? (
                            detailData.effectiveIngredients.map((ingredient) => (
                              <span className="ingredient-tag effective" key={ingredient}>{ingredient}</span>
                            ))
                          ) : (
                            <span className="ingredient-tag empty">효능 성분 정보 없음</span>
                          )}
                        </div>
                      </div>
                      <div className="ingredient-tag-group">
                        <div className="ingredient-tag-label">주의 성분</div>
                        <div className="ingredient-tag-list">
                          {product.risk_flags.length > 0 ? (
                            product.risk_flags.map((riskFlag) => (
                              <span className="ingredient-tag risk" key={riskFlag}>{riskFlag}</span>
                            ))
                          ) : (
                            <span className="ingredient-tag empty">표시할 주의 성분 없음</span>
                          )}
                        </div>
                      </div>
                    </div>
                    <div className="ingredient-copy" id="ingredientCopy">
                      {detailData.relatedIngredients.length > 0
                        ? detailData.relatedIngredients.join(", ")
                        : "성분 정보가 준비 중입니다."}
                    </div>
                  </div>
                </div>
              </section>

              <section className="detail-section" id="ingredients">
                <div className="section-kicker">Evidence</div>
                <h2>성분 효능 근거</h2>
                <div className="review-list" id="evidenceList">
                  {product.evidence.length > 0 ? (
                    product.evidence.map((evidence) => (
                      <article
                        className="review-item"
                        key={`${evidence.ingredient_name}-${evidence.effect_name}-${evidence.source_title}`}
                      >
                        <div className="review-item-head">
                          <strong>{evidence.ingredient_name || "성분"}</strong>
                          <span>{evidenceLevelLabel[evidence.evidence_level]}</span>
                        </div>
                        <p>{evidence.evidence_text || `${evidence.effect_name} 효능 근거를 확인했습니다.`}</p>
                        {evidence.source_title ? (
                          <a className="review-source-link" href="#sourceList">
                            {evidence.source_title}
                          </a>
                        ) : null}
                      </article>
                    ))
                  ) : (
                    <div className="review-item"><p>표시할 성분 효능 근거가 없습니다.</p></div>
                  )}
                </div>
                <div className="source-list" id="sourceList">
                  {product.sources.length > 0 ? (
                    <>
                      <div className="source-list-title">근거 출처</div>
                      <div className="source-chip-list">
                        {product.sources.map((source) => (
                          <a
                            className="source-chip"
                            href={source.url || "#"}
                            target="_blank"
                            rel="noopener noreferrer"
                            key={`${source.title}-${source.url}`}
                          >
                            <span>{source.source_type || "source"}</span>
                            <strong>{source.title || "출처"}</strong>
                          </a>
                        ))}
                      </div>
                    </>
                  ) : (
                    <div className="review-item"><p>표시할 근거 출처 정보가 없습니다.</p></div>
                  )}
                </div>
              </section>

              <section className="detail-section" id="risks">
                <div className="section-kicker">Cautions</div>
                <h2>주의 성분</h2>
                <div className="review-list" id="riskList">
                  {product.risk_flags.length > 0 ? (
                    product.risk_flags.map((riskFlag) => (
                      <article className="review-item" key={riskFlag}>
                        <div className="review-item-head">
                          <strong>{riskFlag}</strong>
                          <span>주의 정보</span>
                        </div>
                        <p>민감도와 피부 타입에 따라 사용 전 성분 확인이 필요합니다.</p>
                      </article>
                    ))
                  ) : (
                    <div className="review-item"><p>표시할 주의 성분 정보가 없습니다.</p></div>
                  )}
                </div>
              </section>

              <section data-commerce-only className="detail-section" id="related">
                <div className="section-kicker">Purchase Options</div>
                <h2>구매처 가격 비교</h2>
                <div className="related-grid" id="relatedGrid">
                  {detailData.purchaseOptions.length > 0 ? (
                    detailData.purchaseOptions.map((price) => (
                      <a
                        className={`related-card${price.is_lowest ? " is-lowest-price" : ""}`}
                        href={price.product_url || product.purchase_url || "#"}
                        target="_blank"
                        rel="noopener noreferrer"
                        key={`${price.mall_name}-${price.product_url}`}
                      >
                        <div className="related-brand">{price.mall_name || "구매처"}</div>
                        <div className="related-name">{price.is_lowest ? "최저가 구매처" : "가격 비교 구매처"}</div>
                        <div className="related-price">{formatPrice(price.price)}</div>
                      </a>
                    ))
                  ) : (
                    <div className="review-item"><p>표시할 구매처 가격 정보가 없습니다.</p></div>
                  )}
                </div>
              </section>
            </section>
          </>
        ) : null}
      </main>

      <div
        className={`ingredient-sheet-backdrop${selectedEffect ? " open" : ""}`}
        id="ingredientSheetBackdrop"
        onClick={() => setSelectedEffect(null)}
      />
      <aside
        className={`ingredient-sheet${selectedEffect ? " open" : ""}`}
        id="ingredientSheet"
        aria-hidden={selectedEffect ? "false" : "true"}
        aria-labelledby="ingredientSheetTitle"
      >
        <button className="ingredient-sheet-close" type="button" aria-label="닫기" onClick={() => setSelectedEffect(null)}>
          ×
        </button>
        <div className="ingredient-sheet-handle" />
        <div className="ingredient-sheet-head">
          <div className="ingredient-sheet-icon" id="ingredientSheetIcon">{selectedEffect?.icon ?? "•"}</div>
          <div>
            <h3 id="ingredientSheetTitle">{selectedEffect?.label ?? "효능 성분"}</h3>
            <p id="ingredientSheetDescription">해당 성분명은 식품의약품안전처 기준 및 성분 근거 데이터에 따른 표시입니다.</p>
          </div>
          <strong id="ingredientSheetCount">{selectedEffect?.items.length ?? 0}</strong>
        </div>
        <div className="ingredient-sheet-list" id="ingredientSheetList">
          {selectedEffect?.items.map((item, index) => (
            <div className="ingredient-sheet-item" key={`${item.ingredient_name}-${item.source_title}-${index}`}>
              <span>{index + 1}</span>
              <div>
                <strong>{item.ingredient_name || "성분"}</strong>
                <p>{item.evidence_text || item.source_title || "성분 효능 근거를 확인했습니다."}</p>
              </div>
            </div>
          ))}
        </div>
      </aside>
    </>
  );
}

export default ProductDetailSpaPage;
