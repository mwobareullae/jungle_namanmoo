import "./ProductDetailPreviewPage.css";
import { useEffect, useState, type MouseEvent } from "react";
import HomeHeader from "../components/HomeHeader";
import { api } from "../lib/api";
import type { ProductDetail } from "../types/recommendation";
import type { ProductListingItem } from "../types/product";
import { getProductImageUrl } from "../lib/imageUrls";
import LoginRequiredDialog from "../components/LoginRequiredDialog";
import ActivityToast from "../components/ui/ActivityToast";
import { useAuth } from "../contexts/useAuth";
import { useActivityToast, wishlistToastMessage } from "../hooks/useActivityToast";
import { addMyWishlistItem, deleteMyWishlistItem, getMyWishlist } from "../lib/activityApi";
import { addCartItem } from "../lib/cartApi";
import { useProductReviewsApi } from "../hooks/useProductReviewsApi";
import type { ProductReview } from "../hooks/useProductReviews";
import HeartIcon from "../components/ui/HeartIcon";
import ShoppingBagIcon from "../components/ui/ShoppingBagIcon";
import StarIcon from "../components/ui/StarIcon";
import PlusIcon from "../components/ui/PlusIcon";
import MinusIcon from "../components/ui/MinusIcon";
import CaretRightIcon from "../components/ui/CaretRightIcon";
import CaretDownIcon from "../components/ui/CaretDownIcon";
import CaretUpIcon from "../components/ui/CaretUpIcon";
import RecommendationCriteriaPanel from "../components/product-detail/RecommendationCriteriaPanel";

const tabs = ["상세정보", "성분정보", "리뷰", "점수분석", "Q&A"];
const scoreLabels: Record<string, string> = { ingredient_effect_score: "성분 효능", ingredient_evidence_score: "근거 신뢰도", concentration_fit_score: "함량 적합도", skin_type_match_score: "피부 타입", sensitivity_score: "민감도", price_value_score: "가격 가치", keyword_score: "키워드", vector_score: "유사도", search_match_score: "검색 일치" };

type EvidenceIconKey = "brighten" | "wrinkle" | "acne" | "moisture" | "soothe";

const getEvidenceIconKey = (effect: string): EvidenceIconKey => {
  if (effect.includes("미백") || effect.includes("톤")) return "brighten";
  if (effect.includes("주름") || effect.includes("탄력")) return "wrinkle";
  if (effect.includes("여드름") || effect.includes("피지") || effect.includes("모공")) return "acne";
  if (effect.includes("보습") || effect.includes("장벽")) return "moisture";
  return "soothe";
};

function EvidenceIcon({ icon }: { icon: EvidenceIconKey }) {
  return <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    {icon === "moisture" ? <path d="M12 2.5c4 5 7 8.5 7 12a7 7 0 1 1-14 0c0-3.5 3-7 7-12z" /> : null}
    {icon === "soothe" ? <path d="M20.8 4.6a5.5 5.5 0 0 0-7.8 0L12 5.6l-1-1a5.5 5.5 0 1 0-7.8 7.8l1 1L12 21l7.8-7.8 1-1a5.5 5.5 0 0 0 0-7.8z" /> : null}
    {icon === "brighten" ? <><circle cx="12" cy="12" r="4" /><path d="M12 3v2M12 19v2M4.2 4.2l1.4 1.4M18.4 18.4l1.4 1.4M3 12h2M19 12h2M4.2 19.8l1.4-1.4M18.4 5.6l1.4-1.4" /></> : null}
    {icon === "wrinkle" ? <><path d="M4 12a8 8 0 0 1 14-5.3M20 12a8 8 0 0 1-14 5.3" /><path d="M18 3v4h-4M6 21v-4h4" /></> : null}
    {icon === "acne" ? <path d="M12 3l7 3.5v5c0 5-3 8.5-7 9.5-4-1-7-4.5-7-9.5v-5L12 3z" /> : null}
  </svg>;
}

function ProductDetailPreviewPage() {
  const recommendationId = new URLSearchParams(window.location.search).get("recommendation_id");
  const [activeTab, setActiveTab] = useState(0);
  const [product, setProduct] = useState<ProductDetail | null>(null);
  const [isDetailsExpanded, setIsDetailsExpanded] = useState(false);
  const [quantity, setQuantity] = useState(1);
  const [selectedEvidenceEffect, setSelectedEvidenceEffect] = useState<string | null>(null);
  const [brandProducts, setBrandProducts] = useState<ProductListingItem[]>([]);
  const [wishedProductIds, setWishedProductIds] = useState<Set<string>>(() => new Set());
  const [pendingWishlistProductIds, setPendingWishlistProductIds] = useState<Set<string>>(() => new Set());
  const [isLoginDialogOpen, setIsLoginDialogOpen] = useState(false);
  const [reviewSort, setReviewSort] = useState<"latest" | "helpful" | "rating_high" | "rating_low">("helpful");
  const [reviewType, setReviewType] = useState<"ALL" | "GENERAL" | "MONTH_USE">("ALL");
  const [reviewRepurchase, setReviewRepurchase] = useState(false);
  const [reviewSkinType, setReviewSkinType] = useState("");
  const [reviewCursor, setReviewCursor] = useState<string | null>(null);
  const { user } = useAuth();
  const { message: toastMessage, showToast } = useActivityToast();
  const reviewApi = useProductReviewsApi(product?.product_id, product?.review_summary, {
    cursor: reviewCursor,
    sort: reviewSort,
    reviewType: reviewType === "ALL" ? undefined : reviewType,
    repurchase: reviewRepurchase || undefined,
    skinType: reviewSkinType || undefined,
  });

  useEffect(() => {
    const productId = new URLSearchParams(window.location.search).get("id");
    if (!productId) return;
    let isMounted = true;
    api.getProduct(productId, recommendationId ?? undefined).then(async (response) => {
      if (!isMounted) return;
      setProduct(response);
      try {
        const brands = await api.getBrands(response.brand, 1, 100);
        const brand = brands.items.find((item) => item.name.trim() === response.brand.trim());
        if (!brand) {
          setBrandProducts([]);
          return;
        }
        const listing = await api.getProductListing({ brandCodes: [brand.code], page: 1, pageSize: 8, sort: "popular" });
        setBrandProducts(listing.items.filter((item) => item.product_id !== response.product_id).slice(0, 4));
      } catch {
        setBrandProducts([]);
      }
    }).catch(() => {
      if (isMounted) {
        setProduct(null);
        setBrandProducts([]);
      }
    });
    return () => {
      isMounted = false;
    };
  }, [recommendationId]);

  useEffect(() => {
    if (!user) {
      setWishedProductIds(new Set());
      return;
    }
    getMyWishlist()
      .then((items) => setWishedProductIds(new Set(items.map((item) => item.productId))))
      .catch(() => setWishedProductIds(new Set()));
  }, [user]);

  const toggleWishlist = async (productId: string) => {
    if (!user) {
      setIsLoginDialogOpen(true);
      return;
    }
    if (pendingWishlistProductIds.has(productId)) return;
    const wasWished = wishedProductIds.has(productId);
    setWishedProductIds((previous) => {
      const next = new Set(previous);
      if (wasWished) next.delete(productId); else next.add(productId);
      return next;
    });
    setPendingWishlistProductIds((previous) => new Set(previous).add(productId));
    try {
      if (wasWished) {
        await deleteMyWishlistItem(productId);
        showToast(wishlistToastMessage.removed);
      } else {
        await addMyWishlistItem(productId);
        showToast(wishlistToastMessage.added);
      }
    } catch {
      setWishedProductIds((previous) => {
        const next = new Set(previous);
        if (wasWished) next.add(productId); else next.delete(productId);
        return next;
      });
      showToast(wishlistToastMessage.failed);
    } finally {
      setPendingWishlistProductIds((previous) => {
        const next = new Set(previous);
        next.delete(productId);
        return next;
      });
    }
  };

  const handlePurchase = () => {
    if (product?.purchase_url) window.location.assign(product.purchase_url);
    else showToast("구매 가능한 상품 URL이 없습니다.");
  };

  const handleAddToCart = async () => {
    if (!product) return;
    try {
      await addCartItem({ product_id: product.product_id, quantity, source: "product_detail_preview" });
      window.dispatchEvent(new Event("cart:updated"));
      showToast("장바구니에 담았습니다.");
      window.location.assign("/cart");
    } catch {
      showToast("장바구니 담기에 실패했습니다. 잠시 후 다시 시도해 주세요.");
    }
  };

  useEffect(() => {
    const sections = tabs
      .map((_, index) => document.getElementById(`preview-${index}`))
      .filter((section): section is HTMLElement => Boolean(section));
    if (!sections.length) return;

    const observer = new IntersectionObserver(
      (entries) => {
        const visible = entries
          .filter((entry) => entry.isIntersecting)
          .sort((a, b) => a.boundingClientRect.top - b.boundingClientRect.top);
        if (visible[0]) {
          const nextIndex = sections.indexOf(visible[0].target as HTMLElement);
          if (nextIndex >= 0) setActiveTab(nextIndex);
        }
      },
      { rootMargin: "-88px 0px -55% 0px", threshold: 0.1 },
    );

    sections.forEach((section) => observer.observe(section));
    return () => observer.disconnect();
  }, []);

  const handleTabClick = (event: MouseEvent<HTMLAnchorElement>, index: number) => {
    event.preventDefault();
    const section = document.getElementById(`preview-${index}`);
    if (!section) return;
    setActiveTab(index);
    window.history.replaceState(null, "", `#preview-${index}`);
    window.scrollTo({ top: section.getBoundingClientRect().top + window.scrollY - 88, behavior: "smooth" });
  };

  const reviewSummary = product?.review_summary;
  const highRatingCount = reviewSummary
    ? (reviewSummary.rating_distribution[4] ?? 0) + (reviewSummary.rating_distribution[5] ?? 0)
    : 0;
  const highRatingPercent = reviewSummary && reviewSummary.review_count > 0
    ? Math.round((highRatingCount / reviewSummary.review_count) * 100)
    : null;
  const ingredientEvidenceGroups = product?.evidence.reduce<Array<{ effect: string; items: ProductDetail["evidence"] }>>(
    (groups, evidence) => {
      const effect = evidence.effect_name.trim();
      if (!effect) return groups;
      const existing = groups.find((group) => group.effect === effect);
      if (existing) existing.items.push(evidence);
      else groups.push({ effect, items: [evidence] });
      return groups;
    },
    [],
  ) ?? [];

  return (
    <>
      {!product ? <div className="product-detail-loading-overlay" role="status" aria-label="상품 상세 불러오는 중"><span className="product-detail-loading-spinner" aria-hidden="true" /></div> : null}
      <HomeHeader />
      <main className="naver-preview-page">

      <section className="naver-preview-product-top">
        <div className="naver-preview-gallery">
          <div className="naver-preview-gallery-main">
            {product?.image_urls[0] ? <img src={product.image_urls[0]} alt={product.name} /> : "대표 이미지"}
          </div>
        </div>
        <div className="naver-preview-info">
          <h1>{product?.name ?? "상품명이 표시되는 영역입니다. 네이버 상품 상세 제목이 들어갑니다"}</h1>
          <div className="naver-preview-review-line"><b><StarIcon size={16} /> {product?.review_summary?.average_rating?.toFixed(2) ?? "4.84"}</b>　<u>{product?.review_summary?.review_count?.toLocaleString() ?? "5,643"}건 리뷰</u></div>
          <div className="naver-preview-single-price"><span>판매가</span><strong>{product?.lowest_price?.toLocaleString() ?? "-"}{product?.lowest_price !== null && product?.lowest_price !== undefined ? "원" : ""}</strong></div>
          <div className="naver-preview-info-row naver-preview-brand-row"><b>브랜드</b><a href={`/brand/${encodeURIComponent(product?.brand ?? "믹순")}`}><span>{product?.brand ?? "믹순"} <CaretRightIcon size={14} /></span></a></div>
          <section className="naver-preview-ai-summary"><h2>AI 추천 요약</h2><strong>내 피부 고민 기준 추천 근거예요</strong><b className="naver-preview-ai-score">{Math.round(product?.total_score ?? 0)}점</b><p>{product?.reason_summary ?? "추천 근거를 준비 중입니다."}</p>{!product ? <span className="naver-preview-ai-loading" aria-label="추천 근거 로딩 중" /> : null}{product?.score_breakdown?.concentration_warning ? <div className="naver-preview-ai-notice"><span aria-hidden="true">i</span>{product.score_breakdown.concentration_warning}</div> : null}</section>
          <div className="naver-preview-buy-grid"><button className="buy" type="button" onClick={handlePurchase}>구매하기</button><button className={product && wishedProductIds.has(product.product_id) ? "is-wished" : ""} type="button" onClick={() => product && void toggleWishlist(product.product_id)}><HeartIcon size={20} />찜하기</button><button type="button" onClick={() => void handleAddToCart()}><ShoppingBagIcon size={20} />장바구니</button></div>
        </div>
      </section>

      <section className="naver-preview-review-strip"><h2>4점 이상 리뷰가 <strong>{highRatingPercent === null ? "-" : `${highRatingPercent}%`}</strong>예요 ⓘ</h2><div>{reviewSummary ? Object.entries(reviewSummary.rating_distribution).slice(0, 3).map(([rating, count]) => <article key={rating}><b><StarIcon size={14} /> {rating}점</b><p>실제 리뷰 {count.toLocaleString()}건</p></article>) : <div className="naver-preview-empty">리뷰 요약을 불러오는 중입니다.</div>}</div><button type="button">리뷰 전체보기 ›</button></section>

      <nav className="naver-preview-tabs">{tabs.map((tab, i) => <a className={i === activeTab ? "active" : ""} href={`#preview-${i}`} key={tab} onClick={(event) => handleTabClick(event, i)}>{tab}</a>)}</nav>
      <section className="naver-preview-detail-layout">
        <div className="naver-preview-detail-main">
          <div className="naver-preview-warning">ⓘ 판매자 안내 및 현금 결제, 개인정보 유도 시 결제/입력하지 마시고 즉시 신고해주세요.</div>
          <article id="preview-0"><h2>상세정보</h2>{product?.image_urls?.length ? <><div className={`naver-preview-detail-images${isDetailsExpanded ? " is-expanded" : ""}`}>{product.image_urls.slice(1).map((imageUrl) => <img key={imageUrl} src={imageUrl} alt={`${product.name} 상세 이미지`} />)}</div>{product.image_urls.length > 2 ? <button className="naver-preview-detail-expand" type="button" onClick={() => setIsDetailsExpanded((expanded) => !expanded)}>{isDetailsExpanded ? "상세정보 접기" : "상세정보 펼쳐보기"}{isDetailsExpanded ? <CaretUpIcon size={24} /> : <CaretDownIcon size={24} />}</button> : null}</> : <div className="naver-preview-empty">상세 이미지를 불러오는 중입니다.</div>}</article>
          {brandProducts.length ? <section className="naver-preview-brand-products" aria-label="같은 브랜드 상품"><div className="naver-preview-brand-products-head"><h2>이 브랜드의 다른 상품</h2><a href={`/brand/${encodeURIComponent(product?.brand ?? "")}`}>더보기</a></div><div className="naver-preview-brand-product-grid">{brandProducts.map((item) => { const isWished = wishedProductIds.has(item.product_id); return <a className="naver-preview-brand-product-card" href={`/product-detail-preview?id=${encodeURIComponent(item.product_id)}`} key={item.product_id}><div className="naver-preview-brand-product-image">{item.thumbnail_url ? <img src={getProductImageUrl(item.thumbnail_url, "w400")} alt={item.name} /> : <span>이미지 없음</span>}<button className={`naver-preview-brand-wishlist${isWished ? " is-wished" : ""}`} type="button" aria-label={isWished ? `${item.name} 찜 해제` : `${item.name} 찜하기`} aria-pressed={isWished} disabled={pendingWishlistProductIds.has(item.product_id)} onClick={(event) => { event.preventDefault(); event.stopPropagation(); void toggleWishlist(item.product_id); }}><HeartIcon size={12} /></button></div><strong>{item.brand}</strong><p>{item.name}</p>{item.lowest_price !== null ? <b>{item.lowest_price.toLocaleString("ko-KR")}원</b> : <b>가격 정보 없음</b>}</a>; })}</div></section> : null}
          <article id="preview-1" className="naver-preview-ingredients"><h2>성분정보</h2><div className="naver-preview-ingredient-block"><h3>전성분</h3><div className="naver-preview-ingredient-copy">{product?.ingredients?.length ? product.ingredients.map((ingredient, index) => <span key={`${ingredient.name}-${index}`}>{ingredient.name}{index < product.ingredients.length - 1 ? ", " : ""}</span>) : <span className="naver-preview-empty-copy">성분 정보를 불러오는 중입니다.</span>}</div>{product?.ingredients?.length ? <p className="naver-preview-ingredient-note">해당 성분명은 식품의약품안전처 기준 및 성분 근거 데이터에 따른 표시입니다.</p> : null}</div><div className="naver-preview-ingredient-block"><h3>성분 근거</h3>{ingredientEvidenceGroups.length ? <div className="naver-preview-evidence-grid">{ingredientEvidenceGroups.map((group) => <button aria-pressed={selectedEvidenceEffect === group.effect} className={`naver-preview-evidence-card${selectedEvidenceEffect === group.effect ? " is-selected" : ""}`} key={group.effect} type="button" onClick={() => setSelectedEvidenceEffect(group.effect)}><div className="naver-preview-evidence-icon" aria-hidden="true"><EvidenceIcon icon={getEvidenceIconKey(group.effect)} /></div><strong>{group.effect}</strong><span>관련 성분 {group.items.length}개</span></button>)}</div> : <div className="naver-preview-empty">표시할 성분 효능 근거가 없습니다.</div>}{selectedEvidenceEffect ? <div className="naver-preview-evidence-detail" role="dialog" aria-label={`${selectedEvidenceEffect} 성분 근거`}><div className="naver-preview-evidence-detail-head"><div><span>선택한 근거</span><strong>{selectedEvidenceEffect}</strong></div><button type="button" aria-label="성분 근거 닫기" onClick={() => setSelectedEvidenceEffect(null)}>×</button></div>{ingredientEvidenceGroups.find((group) => group.effect === selectedEvidenceEffect)?.items.map((evidence) => <div className="naver-preview-evidence-detail-item" key={`${evidence.ingredient_name}-${evidence.source_title}`}><strong>{evidence.ingredient_name}</strong><p>{evidence.evidence_text}</p>{evidence.source_title ? <small>출처: {evidence.source_title}</small> : null}</div>)}</div> : null}</div></article>
          <article id="preview-2" className="naver-preview-reviews"><h2>리뷰</h2>{recommendationId && product ? <RecommendationCriteriaPanel product={product} /> : null}<div className="naver-preview-review-controls"><select aria-label="리뷰 정렬" value={reviewSort} onChange={(event) => { setReviewCursor(null); setReviewSort(event.target.value as typeof reviewSort); }}><option value="helpful">추천순</option><option value="latest">최신순</option><option value="rating_high">평점 높은순</option><option value="rating_low">평점 낮은순</option></select><select aria-label="리뷰 유형" value={reviewType} onChange={(event) => { setReviewCursor(null); setReviewType(event.target.value as typeof reviewType); }}><option value="ALL">전체 리뷰</option><option value="GENERAL">일반 리뷰</option><option value="MONTH_USE">한달 사용 리뷰</option></select><label><input type="checkbox" checked={reviewRepurchase} onChange={(event) => { setReviewCursor(null); setReviewRepurchase(event.target.checked); }} /> 재구매</label><select aria-label="피부 타입" value={reviewSkinType} onChange={(event) => { setReviewCursor(null); setReviewSkinType(event.target.value); }}><option value="">전체 피부 타입</option>{["건성", "지성", "복합성", "수부지", "중성", "민감성"].map((type) => <option value={type} key={type}>{type}</option>)}</select></div>{reviewApi.isLoading && reviewApi.reviews.length === 0 ? <div className="naver-preview-empty">리뷰를 불러오는 중입니다.</div> : null}{reviewApi.errorMessage ? <div className="naver-preview-empty">리뷰를 불러오지 못했습니다.</div> : null}{!reviewApi.isLoading && !reviewApi.errorMessage && reviewApi.reviews.length === 0 ? <div className="naver-preview-empty">조건에 맞는 리뷰가 없습니다.</div> : null}<div className="naver-preview-review-list">{reviewApi.reviews.map((review: ProductReview) => <article className="naver-preview-review-card" key={review.id}><div className="naver-preview-review-card-head"><strong>{review.nickname}</strong><span><StarIcon size={14} /> {review.rating.toFixed(1)}</span></div><div className="naver-preview-review-meta">{review.skinType}{review.isRepurchase ? " · 재구매" : ""}{review.usedOverMonth ? " · 한달 사용" : ""} · {review.createdAt}</div><p>{review.body}</p>{review.photos.length ? <div className="naver-preview-review-photos">{review.photos.slice(0, 3).map((photo) => <img src={photo} alt="리뷰 첨부 이미지" key={photo} />)}</div> : null}<small>도움돼요 {review.likeCount}</small></article>)}</div>{reviewApi.hasNext && reviewApi.nextCursor ? <button className="naver-preview-review-more" type="button" onClick={() => setReviewCursor(reviewApi.nextCursor)}>다음 리뷰 보기</button> : null}</article>
          <article id="preview-3" className="naver-preview-score-analysis"><h2>점수분석</h2><div className="naver-preview-score-intro"><strong>이 상품을 추천한 근거를 확인해보세요</strong><span>{product?.reason_summary ?? "점수 분석을 준비 중입니다."}</span></div>{product?.score_breakdown ? <div className="naver-preview-score-grid">{Object.entries(scoreLabels).map(([key, label]) => { const value = product.score_breakdown?.[key as keyof typeof product.score_breakdown]; return typeof value === "number" ? <div className="naver-preview-score-card" key={key}><span>{label}</span><strong>{Math.round(value)}점</strong></div> : null; })}</div> : <div className="naver-preview-empty">점수 분석을 불러오는 중입니다.</div>}{product?.score_breakdown?.risk_penalty && product.score_breakdown.risk_penalty < 0 ? <div className="naver-preview-score-warning">주의 항목으로 {Math.abs(product.score_breakdown.risk_penalty)}점이 감점되었습니다.</div> : null}</article>
          <article id="preview-4" className="naver-preview-qna"><h2>Q&amp;A</h2><details><summary>주의사항</summary><p>상품별 사용법과 성분 정보를 확인한 뒤 피부 상태에 맞게 사용해 주세요.</p></details><details><summary>배송 안내</summary><p>배송 정보와 도착 예정일은 주문 시점과 배송지에 따라 달라질 수 있습니다.</p></details><details><summary>교환·반품 안내</summary><p>교환·반품 조건은 상품 상태와 신청 시점에 따라 달라질 수 있습니다.</p></details></article>
        </div>
        <aside className="naver-preview-sticky-buy"><div className="naver-preview-quantity"><b>수량 선택</b><div><button type="button" aria-label="수량 줄이기" onClick={() => setQuantity((value) => Math.max(1, value - 1))}><MinusIcon size={20} /></button><span>{quantity}</span><button type="button" aria-label="수량 늘리기" onClick={() => setQuantity((value) => value + 1)}><PlusIcon size={20} /></button></div></div><div className="naver-preview-total"><span>총 {quantity}개</span><b>총 금액　<strong>{((product?.lowest_price ?? 199000) * quantity).toLocaleString()}원</strong></b></div><div className="naver-preview-buy-grid"><button className="buy" type="button" onClick={handlePurchase}>구매하기</button><button className={product && wishedProductIds.has(product.product_id) ? "is-wished" : ""} type="button" onClick={() => product && void toggleWishlist(product.product_id)}><HeartIcon size={20} />찜</button><button type="button" onClick={() => void handleAddToCart()}><ShoppingBagIcon size={20} />장바구니</button></div></aside>
      </section>
      <div className="naver-preview-floating"><button type="button" aria-label="맨 위로" onClick={() => window.scrollTo({ top: 0, behavior: 'smooth' })}>↑</button></div>
      <LoginRequiredDialog onOpenChange={setIsLoginDialogOpen} open={isLoginDialogOpen} redirectTo={`${window.location.pathname}${window.location.search}`} />
      <ActivityToast message={toastMessage} />
      </main>
    </>
  );
}

export default ProductDetailPreviewPage;
