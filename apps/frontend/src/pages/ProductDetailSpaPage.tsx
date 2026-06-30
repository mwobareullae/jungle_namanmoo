import { useEffect, useState } from "react";
import HomeHeader from "../components/HomeHeader";
import HomeOverlays from "../components/HomeOverlays";
import { api } from "../lib/api";
import { installHomeRuntime } from "../lib/homeRuntime";
import type { ProductDetail } from "../types/recommendation";

const formatPrice = (price: number | null) =>
  price === null ? "가격 정보 없음" : `${price.toLocaleString("ko-KR")}원`;

const getDetailParams = () => {
  const params = new URLSearchParams(window.location.search);
  return {
    productId: params.get("id") ?? "",
    recommendationId: params.get("recommendation_id") ?? undefined,
  };
};

function ProductDetailSpaPage() {
  const [{ productId, recommendationId }] = useState(getDetailParams);
  const [product, setProduct] = useState<ProductDetail | null>(null);
  const [isLoading, setIsLoading] = useState(Boolean(productId));
  const [errorMessage, setErrorMessage] = useState("");

  useEffect(() => installHomeRuntime(), []);

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
        if (isMounted) setErrorMessage("상품 상세 정보를 불러오지 못했습니다.");
      })
      .finally(() => {
        if (isMounted) setIsLoading(false);
      });

    return () => {
      isMounted = false;
    };
  }, [productId, recommendationId]);

  return (
    <>
      <HomeOverlays />
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
                  {product.image_urls.slice(0, 4).map((imageUrl) => (
                    <img src={imageUrl} alt="" key={imageUrl} />
                  ))}
                </div>
              </div>

              <div className="detail-summary">
                <div className="detail-brand-row">
                  <div className="detail-brand" id="productBrand">{product.brand}</div>
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
                  {product.evidence_tags.map((tag) => <span key={tag}>{tag}</span>)}
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
                      <span>효능 {product.score_breakdown.ingredient_effect_score}점</span>
                      <span>근거 {product.score_breakdown.ingredient_evidence_score}점</span>
                      <span>피부 {product.score_breakdown.skin_type_match_score}점</span>
                      <span>가격 {product.score_breakdown.price_value_score}점</span>
                    </>
                  ) : null}
                </div>
              </div>
            </div>
          ) : null}
        </section>
      </main>
    </>
  );
}

export default ProductDetailSpaPage;
