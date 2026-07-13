import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import HomeHeader from "../components/HomeHeader";
import HomeProductCard from "../components/HomeProductCard";
import Skeleton from "../components/ui/Skeleton";
import { api } from "../lib/api";
import { observeProductImpressions } from "../lib/appSignals/impressions";
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
  risk_flags: []
});

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
        <h1 className="category-page__title">{title}</h1>
        {subtitle ? <p className="new-products-page__description">{subtitle}</p> : null}
        <div className="product-grid">
          {isLoading ? (
            Array.from({ length: 8 }, (_, index) => (
              <article className="product-card product-card-loading" key={index} aria-hidden="true">
                <Skeleton className="product-img" />
                <div className="product-info">
                  <Skeleton className="skeleton-line skeleton-brand" />
                  <Skeleton className="skeleton-line skeleton-title" />
                  <Skeleton className="skeleton-price" />
                </div>
              </article>
            ))
          ) : errorMessage ? (
            <div className="search-empty">{errorMessage}</div>
          ) : products.length > 0 ? (
            products.map((product) => (
              <HomeProductCard
                eventContext={{
                  sectionId: config.source,
                  page: "recommendation_result",
                  source: config.source,
                  clickEvent: "search_result_click",
                  impressionEvent: "search_result_impression"
                }}
                key={product.product_id}
                product={product}
              />
            ))
          ) : (
            <div className="search-empty">표시할 상품이 없습니다.</div>
          )}
        </div>
      </main>
    </div>
  );
}

export default HomeSectionProductsPage;
