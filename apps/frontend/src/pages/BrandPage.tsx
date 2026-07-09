import { Link, useParams } from "react-router-dom";
import HomeHeader from "../components/HomeHeader";

const getBrandName = (value?: string) => {
  if (!value) {
    return "브랜드";
  }

  try {
    return decodeURIComponent(value);
  } catch {
    return value;
  }
};

function BrandPage() {
  const { brandName } = useParams();
  const decodedBrandName = getBrandName(brandName);

  return (
    <div className="brand-page">
      <HomeHeader />
      <main className="brand-page__main">
        <nav className="brand-page__breadcrumb" aria-label="브랜드 경로">
          <Link to="/">홈</Link>
          <span aria-hidden="true">&gt;</span>
          <span>{decodedBrandName}</span>
        </nav>
        <section className="brand-page__placeholder" aria-labelledby="brandPageTitle">
          <p className="brand-page__eyebrow">Brand</p>
          <h1 id="brandPageTitle">{decodedBrandName}</h1>
          <p>브랜드 페이지 준비 중입니다.</p>
        </section>
      </main>
    </div>
  );
}

export default BrandPage;
