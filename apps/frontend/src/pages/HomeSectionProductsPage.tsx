import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import HomeHeader from "../components/HomeHeader";
import ProductThumbnail from "../components/ProductThumbnail";
import ProductSoldOutOverlay from "../components/ProductSoldOutOverlay";
import Skeleton from "../components/ui/Skeleton";
import { api } from "../lib/api";
import { trackEvent } from "../lib/appSignals/client";
import { observeProductImpressions } from "../lib/appSignals/impressions";
import { navigateWithinApp } from "../lib/navigation";
import { isProductSoldOut } from "../lib/productAvailability";
import type { HomeSectionProduct, ProductCardItem } from "../types/recommendation";

type HomeSectionProductsPageProps = {
  sectionType: "evidence-picks" | "for-you";
};

const pageConfig = {
  "evidence-picks": {
    fallbackTitle: "성분 근거가 좋은 제품",
    source: "evidence_picks"
  },
  "for-you": {
    fallbackTitle: "나를 위한 맞춤 추천",
    source: "for_you"
  }
} as const;

const mapHomeProductToCard = (product: HomeSectionProduct, index: number): ProductCardItem => ({
  product_id: product.product_id,
  rank: index + 1,
  total_score: product.display_score,
  reason_summary: product.reason_summary,
  brand: product.brand,
  name: product.name,
  thumbnail_url: product.thumbnail_url,
  lowest_price: product.lowest_price,
  evidence_tags: product.tags,
  key_ingredients: product.tags,
  risk_flags: [],
  sales_status: product.sales_status,
  stock_status: product.stock_status,
  available_quantity: product.available_quantity,
  in_stock: product.in_stock
});

const formatPrice = (price: number | null) =>
  price === null ? "가격 정보 없음" : `${price.toLocaleString("ko-KR")}원`;

function DealCard({ product, source }: { product: ProductCardItem; source: string }) {
  const isSoldOut = isProductSoldOut(product);
  const openDetail = () => {
    trackEvent("search_result_click", {
      productId: product.product_id,
      rank: product.rank,
      source,
      page: "recommendation_result",
      metadata: { section_id: source }
    });
    void navigateWithinApp(`/product-detail?id=${encodeURIComponent(product.product_id)}`);
  };

  return (
    <article
      aria-label={`${product.brand} ${product.name} 상세 보기`}
      className={`home-deal-card${isSoldOut ? " is-sold-out" : ""}`}
      data-event-page="recommendation_result"
      data-event-source={source}
      data-impression-event="search_result_impression"
      data-product-id={product.product_id}
      data-rank={product.rank}
      data-section-id={source}
      onClick={openDetail}
      onKeyDown={(event) => {
        if (event.key === "Enter" || event.key === " ") {
          event.preventDefault();
          openDetail();
        }
      }}
      role="link"
      tabIndex={0}
    >
      <div className="home-deal-media">
        <ProductThumbnail src={product.thumbnail_url} alt={`${product.brand} ${product.name}`} />
        {isSoldOut ? <ProductSoldOutOverlay /> : null}
      </div>
      <div className="home-deal-body">
        <div className="home-ranking-brand">{product.brand}</div>
        <div className="home-deal-name">{product.name}</div>
        <div className="home-deal-tags">
          {product.key_ingredients.slice(0, 2).map((tag) => (
            <span key={tag}>{tag}</span>
          ))}
        </div>
        <div className={`home-deal-price${isSoldOut ? " product-price--sold-out" : ""}`}>{formatPrice(product.lowest_price)}</div>
      </div>
    </article>
  );
}

function DealSkeletons() {
  return Array.from({ length: 8 }, (_, index) => (
    <article className="home-deal-card home-deal-loading-card" key={index} aria-hidden="true">
      <Skeleton className="home-deal-media" />
      <div className="home-deal-body">
        <Skeleton className="home-ranking-brand" />
        <Skeleton className="home-deal-name" />
        <div className="home-deal-tags">
          <Skeleton as="span" />
          <Skeleton as="span" />
        </div>
        <Skeleton className="home-deal-price" />
      </div>
    </article>
  ));
}

function HomeSectionProductsPage({ sectionType }: HomeSectionProductsPageProps) {
  const config = pageConfig[sectionType];
  const [title, setTitle] = useState<string>(config.fallbackTitle);
  const [subtitle, setSubtitle] = useState("");
  const [products, setProducts] = useState<ProductCardItem[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [errorMessage, setErrorMessage] = useState("");

  useEffect(() => {
    let isMounted = true;
    const request = sectionType === "evidence-picks"
      ? api.getEvidencePicks({ limit: 20 })
      : api.getForYou({ limit: 20 });

    queueMicrotask(() => {
      if (isMounted) setIsLoading(true);
    });
    request
      .then((section) => {
        if (!isMounted) return;
        setTitle(section.title || config.fallbackTitle);
        setSubtitle(section.subtitle || "");
        setProducts(section.products.map(mapHomeProductToCard));
        setErrorMessage("");
      })
      .catch(() => {
        if (!isMounted) return;
        setProducts([]);
        setErrorMessage("상품을 불러오지 못했습니다.");
      })
      .finally(() => {
        if (isMounted) setIsLoading(false);
      });

    return () => {
      isMounted = false;
    };
  }, [config.fallbackTitle, sectionType]);

  useEffect(() => observeProductImpressions(), [products]);

  return (
    <div className="category-page home-section-products-page">
      <HomeHeader />
      <main className="category-page__main">
        <nav className="category-page__breadcrumb" aria-label={`${title} 경로`}>
          <Link to="/">홈</Link>
          <span aria-hidden="true">&gt;</span>
          <span>{title}</span>
        </nav>
        <div className="home-section-kicker">{sectionType === "evidence-picks" ? "성분 근거 기준 큐레이션" : "피부 조건 기준 큐레이션"}</div>
        <h1 className="category-page__title">{title}</h1>
        {subtitle ? <p className="new-products-page__description" style={{ textAlign: "left" }}>{subtitle}</p> : null}
        {sectionType === "for-you" ? (
          <section className="home-api-section home-deal-section home-section-products-page__section">
            <div className="home-deal-grid">
              {isLoading ? (
                <DealSkeletons />
              ) : errorMessage ? (
                <div className="search-empty">{errorMessage}</div>
              ) : products.length > 0 ? (
                products.map((product) => (
                  <DealCard key={product.product_id} product={product} source={config.source} />
                ))
              ) : (
                <div className="search-empty">표시할 상품이 없습니다.</div>
              )}
            </div>
          </section>
        ) : (
          <section className="home-api-section home-deal-section home-section-products-page__section">
            <div className="home-deal-grid">
              {isLoading ? (
                <DealSkeletons />
              ) : errorMessage ? (
                <div className="search-empty">{errorMessage}</div>
              ) : products.length > 0 ? (
                products.map((product) => <DealCard key={product.product_id} product={product} source={config.source} />)
              ) : (
                <div className="search-empty">표시할 상품이 없습니다.</div>
              )}
            </div>
          </section>
        )}
      </main>
    </div>
  );
}

export default HomeSectionProductsPage;
