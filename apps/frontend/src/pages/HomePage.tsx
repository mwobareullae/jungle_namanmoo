import { useEffect, useState } from "react";
import ProductCard from "../components/ProductCard";
import { api } from "../lib/api";
import type { HomeSectionsResponse, ProductCardItem } from "../types/recommendation";

const popularConcerns = [
  "수부지인데 모공과 좁쌀이 같이 고민이에요",
  "민감해서 붉어지고 따가운 날이 많아요",
  "속건조가 심하고 화장이 들떠요",
  "피지가 많고 피부결이 거칠어 보여요",
  "자극 적은 진정 보습 제품을 찾고 있어요"
];

type HomePageProps = {
  onSearch: (concernText?: string) => void;
  onOpenProduct: (productId: string) => void;
};

function HomePage({ onSearch, onOpenProduct }: HomePageProps) {
  const [homeSections, setHomeSections] = useState<HomeSectionsResponse | null>(null);
  const [homeError, setHomeError] = useState<string | null>(null);

  useEffect(() => {
    let isActive = true;

    api
      .getHomeSections({ skinType: "수부지", sensitivity: "보통", limitPerSection: 8 })
      .then((response) => {
        if (!isActive) return;
        setHomeSections(response);
        setHomeError(null);
      })
      .catch(() => {
        if (!isActive) return;
        setHomeSections(null);
        setHomeError("추천 상품을 불러오지 못했습니다.");
      });

    return () => {
      isActive = false;
    };
  }, []);

  const primarySection = homeSections?.sections.find((section) => section.products.length > 0);
  const otherSections = homeSections?.sections.filter(
    (section) => section.products.length > 0 && section.section_id !== primarySection?.section_id
  );

  const renderProducts = (products: ProductCardItem[]) => (
    <div className="product-grid">
      {products.map((product) => (
        <ProductCard key={product.product_id} product={product} onOpen={onOpenProduct} />
      ))}
    </div>
  );

  return (
    <>
      <section className="home-page" aria-labelledby="home-title">
        <div className="home-inner">
          <p className="eyebrow home-eyebrow">AI skin recommendation</p>
          <h1 id="home-title" className="home-title">
            내 피부 고민에 맞는
            <span>최적의 화장품 추천</span>
          </h1>
          <p className="home-copy">
            피부 고민을 입력하면 성분 효능 근거를 바탕으로 지금 필요한 제품을 찾아드려요.
          </p>

          <button className="home-search" type="button" onClick={() => onSearch()}>
            <span>피부 고민을 입력해보세요</span>
            <span className="home-search-icon" aria-hidden="true" />
          </button>

          <div className="home-trends" aria-labelledby="home-trends-title">
            <p id="home-trends-title" className="home-trends-date">
              오늘 많이 찾는 고민
            </p>
            <ol className="home-trend-list">
              {popularConcerns.map((concern, index) => (
                <li key={concern}>
                  <button type="button" onClick={() => onSearch(concern)}>
                    <span>{index + 1}</span>
                    <strong>{concern}</strong>
                  </button>
                </li>
              ))}
            </ol>
          </div>
        </div>
      </section>

      <section className="wrap home-products" aria-labelledby="home-products-title">
        <div className="results-head">
          <div>
            <p className="eyebrow">{primarySection?.section_type ?? "Best Sellers"}</p>
            <h2 id="home-products-title" className="section-title">
              {primarySection?.title ?? "지금 인기있는 제품"}
            </h2>
            <p className="muted-copy">
              {primarySection?.subtitle ?? "성분 근거를 기준으로 추천한 제품을 불러오는 중입니다."}
            </p>
          </div>
        </div>

        {homeError ? <div className="empty-box">{homeError}</div> : null}
        {!homeError && !primarySection ? <div className="empty-box">추천 상품을 불러오는 중입니다.</div> : null}
        {primarySection ? renderProducts(primarySection.products) : null}
      </section>

      {otherSections?.map((section) => (
        <section className="wrap home-products" key={section.section_id}>
          <div className="results-head">
            <div>
              <p className="eyebrow">{section.section_type}</p>
              <h2 className="section-title">{section.title}</h2>
              <p className="muted-copy">{section.subtitle}</p>
            </div>
          </div>
          {renderProducts(section.products)}
        </section>
      ))}
    </>
  );
}

export default HomePage;
