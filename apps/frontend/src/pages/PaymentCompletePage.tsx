import { useEffect, useState } from "react";
import HomeHeader from "../components/HomeHeader";
import { api } from "../lib/api";
import type { ProductDetail } from "../types/recommendation";

type CompleteProduct = {
  id: string;
  brand: string;
  name: string;
  image: string;
};

const fallbackProducts: Record<string, CompleteProduct> = {
  "10": {
    id: "10",
    brand: "라로슈포제",
    name: "라로슈포제 시카플라스트 밤 B5+ 100ml 기획 (+3ml 추가증정)",
    image: "",
  },
  "12": {
    id: "12",
    brand: "웰라쥬",
    name: "[속건조필수템] 웰라쥬 리얼 히알루로닉 블루 100 앰플 75ml 2입 기획",
    image: "",
  },
  "15": {
    id: "15",
    brand: "라운드랩",
    name: "[6월올영픽/총200ml] 라운드랩 자작나무 수분 크림 80ml+80ml 더블 기획 (+40ml)",
    image: "",
  },
};

const formatWon = (value: number) =>
  value > 0 ? `${value.toLocaleString("ko-KR")}원` : "결제금액 확인 중";
const getCompleteParams = () => {
  const params = new URLSearchParams(window.location.search);
  return {
    id: params.get("id") ?? "10",
    total: Number(params.get("total") ?? 0),
    count: Number(params.get("count") ?? 1),
    recommendationId: params.get("recommendation_id") ?? undefined,
    skinType: params.get("skin_type") ?? "",
    sensitivity: params.get("sensitivity") ?? "",
  };
};

const mapDetailToCompleteProduct = (product: ProductDetail): CompleteProduct => ({
  id: product.product_id,
  brand: product.brand,
  name: product.name,
  image: product.thumbnail_url ?? product.image_urls[0] ?? "",
});

function PaymentCompletePage() {
  const [{ id, total, count, recommendationId, skinType, sensitivity }] = useState(getCompleteParams);
  const [apiProduct, setApiProduct] = useState<CompleteProduct | null>(null);
  const [orderNo] = useState(() => `MWB-${String(Date.now()).slice(-8)}`);

  useEffect(() => {
    let isMounted = true;
    api.getProduct(id, recommendationId)
      .then((product) => {
        if (isMounted) setApiProduct(mapDetailToCompleteProduct(product));
      })
      .catch(() => {
        if (isMounted) setApiProduct(null);
      });

    return () => {
      isMounted = false;
    };
  }, [id, recommendationId]);

  const product = apiProduct ?? fallbackProducts[id] ?? fallbackProducts["10"];
  const productName = count > 1 ? `${product.name} 외 ${count - 1}개` : product.name;
  const detailParams = new URLSearchParams({ id: product.id });
  if (recommendationId) detailParams.set("recommendation_id", recommendationId);
  if (skinType) detailParams.set("skin_type", skinType);
  if (sensitivity) detailParams.set("sensitivity", sensitivity);

  return (
    <>
      <HomeHeader />
      <main className="complete-page">
        <section className="complete-shell">
          <div className="complete-hero">
            <div className="complete-mark">
              <svg width="34" height="34" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round">
                <path d="M20 6 9 17l-5-5" />
              </svg>
            </div>
            <h1>결제가 완료되었습니다</h1>
            <p>피부 고민에 맞춰 고른 상품 주문이 접수되었어요. 주문 정보와 배송 진행 상황은 마이페이지에서 확인할 수 있습니다.</p>
          </div>

          <div className="complete-grid">
            <section className="complete-card">
              <h2>주문 정보</h2>
              <div className="complete-row">
                <span>주문번호</span>
                <strong id="orderNo">{orderNo}</strong>
              </div>
              <div className="complete-row">
                <span>결제금액</span>
                <strong id="paidTotal">{formatWon(total)}</strong>
              </div>
              <div className="complete-row">
                <span>결제수단</span>
                <strong>간편결제</strong>
              </div>
              <div className="complete-row">
                <span>배송 예정</span>
                <strong>내일 출고 예정</strong>
              </div>
            </section>

            <section className="complete-card">
              <h2>주문 상품</h2>
              <div className="complete-product">
                {product.image ? (
                  <img
                    id="productImage"
                    src={product.image}
                    alt={`${product.brand} ${product.name}`}
                  />
                ) : (
                  <div className="complete-image-empty" id="productImage">
                    이미지 준비중
                  </div>
                )}
                <div>
                  <div className="complete-brand" id="productBrand">{product.brand}</div>
                  <div className="complete-name" id="productName">{productName}</div>
                </div>
              </div>
            </section>
          </div>

          <div className="complete-actions">
            <a className="complete-btn" href="/">쇼핑 계속하기</a>
            <a className="complete-btn primary" href={`/product-detail?${detailParams.toString()}`}>상품 다시 보기</a>
          </div>
        </section>
      </main>
    </>
  );
}

export default PaymentCompletePage;
