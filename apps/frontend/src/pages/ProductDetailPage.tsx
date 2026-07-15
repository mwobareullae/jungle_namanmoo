import Badge from "../components/Badge";
import type { ProductDetail } from "../types/recommendation";

type ProductDetailPageProps = {
  product: ProductDetail;
  onBack: () => void;
};

const confidenceLabel: Record<ProductDetail["content_confidence"], string> = {
  high: "높음",
  medium: "보통",
  low: "낮음",
  unknown: "확인 필요"
};

const formatPrice = (price: number | null) =>
  price === null ? "가격 정보 없음" : `${price.toLocaleString("ko-KR")}원`;

const scoreLabels = {
  ingredient_effect_score: "효능",
  ingredient_evidence_score: "근거",
  skin_type_match_score: "피부타입",
  price_value_score: "가격",
  keyword_score: "키워드",
  vector_score: "벡터",
  search_match_score: "검색매칭"
};

function ProductDetailPage({ product, onBack }: ProductDetailPageProps) {
  return (
    <section className="wrap detail-page">
      <button className="text-back" type="button" onClick={onBack}>
        ← 결과로 돌아가기
      </button>

      <div className="detail-hero">
        <div className="detail-media">
          {product.thumbnail_url ? (
            <img className="product-image" src={product.thumbnail_url} alt="" />
          ) : (
            <div className="product-thumb tone-1" aria-label="이미지 없음" />
          )}
          <div className="detail-images">
            {product.image_urls.length > 0 ? (
              product.image_urls.map((imageUrl) => <img src={imageUrl} alt="" key={imageUrl} />)
            ) : (
              <span>상세 이미지 준비 중</span>
            )}
          </div>
        </div>

        <div className="detail-info">
          <p className="eyebrow">{product.brand}</p>
          <h1 className="detail-title">{product.name}</h1>
          <p className="reason-summary large">{product.reason_summary}</p>

          <div className="detail-score">
            <strong className="score-xl">{product.total_score}</strong>
            <span>/ 100 추천점수</span>
          </div>

          <div className="badges">
            <Badge tone="notice">함량 신뢰도 {confidenceLabel[product.content_confidence]}</Badge>
            {product.risk_flags.length > 0 ? (
              <Badge tone="risk">주의 성분 있음</Badge>
            ) : (
              <Badge>주의 성분 없음</Badge>
            )}
            <Badge>{formatPrice(product.lowest_price)}</Badge>
          </div>

          {product.purchase_url ? (
            <a
              className="primary-button detail-buy"
              href={product.purchase_url}
              target="_blank"
              rel="noreferrer"
            >
              구매하러 가기
            </a>
          ) : (
            <button className="primary-button detail-buy" type="button" disabled>
              구매 URL 없음
            </button>
          )}
        </div>
      </div>

      {product.score_breakdown ? (
        <section className="detail-section">
          <p className="eyebrow">점수 구성</p>
          <div className="badges">
            {Object.entries(scoreLabels).map(([key, label]) => (
              <Badge key={key} tone="notice">
                {label} {product.score_breakdown?.[key as keyof typeof scoreLabels]}점
              </Badge>
            ))}
            {product.score_breakdown.risk_penalty < 0 ? (
              <Badge tone="risk">주의 항목 {Math.abs(product.score_breakdown.risk_penalty)}점</Badge>
            ) : null}
          </div>
        </section>
      ) : null}

      <section className="detail-section">
        <p className="eyebrow">추천 근거</p>
        {product.evidence.length === 0 ? (
          <p className="muted-copy">
            현재 표시 가능한 근거가 없습니다. 실제 API 연동 시 근거 데이터를 받아 표시합니다.
          </p>
        ) : (
          <div className="evidence-list">
            {product.evidence.map((evidence) => (
              <article
                className="evidence-item"
                key={`${evidence.ingredient_name}-${evidence.effect_name}`}
              >
                <h3 className="evidence-name">{evidence.ingredient_name}</h3>
                <p>{evidence.effect_name}</p>
                <p className="muted-copy">{evidence.evidence_text}</p>
                {evidence.source_title ? (
                  <p className="muted-copy">출처: {evidence.source_title}</p>
                ) : null}
                <Badge tone="notice">근거 {evidence.evidence_level ?? "등급 정보 없음"}</Badge>
              </article>
            ))}
          </div>
        )}
      </section>

      <section className="detail-section">
        <p className="eyebrow">관련 성분</p>
        <div className="badges">
          {product.related_ingredients.map((ingredient) => (
            <Badge key={ingredient}>{ingredient}</Badge>
          ))}
        </div>
      </section>

      {product.risk_flags.length > 0 ? (
        <section className="detail-section">
          <p className="eyebrow">주의 성분</p>
          <div className="evidence-list">
            {product.risk_flags.map((riskFlag) => (
              <article className="evidence-item" key={riskFlag}>
                <p className="muted-copy">{riskFlag}</p>
              </article>
            ))}
          </div>
        </section>
      ) : null}

      <section className="detail-section">
        <p className="eyebrow">구매처</p>
        {product.prices.length > 0 ? (
          <div className="evidence-list">
            {product.prices.map((price) => (
              <article className="evidence-item" key={`${price.mall_name}-${price.product_url}`}>
                <h3 className="evidence-name">{price.mall_name}</h3>
                <p>{formatPrice(price.price)}</p>
                {price.is_lowest ? <Badge tone="notice">최저가</Badge> : null}
                <a className="text-link" href={price.product_url} target="_blank" rel="noreferrer">
                  상품 보기
                </a>
              </article>
            ))}
          </div>
        ) : (
          <p className="muted-copy">구매처 정보가 없습니다.</p>
        )}
      </section>

      <section className="detail-section">
        <p className="eyebrow">근거 출처</p>
        {product.sources.length > 0 ? (
          <div className="evidence-list">
            {product.sources.map((source) => (
              <article className="evidence-item" key={`${source.title}-${source.url}`}>
                <h3 className="evidence-name">{source.title}</h3>
                <p className="muted-copy">{source.source_type}</p>
                <a className="text-link" href={source.url} target="_blank" rel="noreferrer">
                  출처 보기
                </a>
              </article>
            ))}
          </div>
        ) : (
          <p className="muted-copy">표시 가능한 출처가 없습니다.</p>
        )}
      </section>
    </section>
  );
}

export default ProductDetailPage;
