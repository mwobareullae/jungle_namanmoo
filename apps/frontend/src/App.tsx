type ProductPreview = {
  brand: string;
  name: string;
  ingredients: string;
  score: number;
  grade: "A" | "B";
  tone: string;
  badges: string[];
};

const previewProducts: ProductPreview[] = [
  {
    brand: "MAISON CREME",
    name: "Hydra Veil Serum",
    ingredients: "히알루론산 · 판테놀 · 세라마이드",
    score: 94,
    grade: "A",
    tone: "tone-a",
    badges: ["성분 근거", "장벽 보습"]
  },
  {
    brand: "ATELIER N",
    name: "Pore Refining Essence",
    ingredients: "나이아신아마이드 · 아연 PCA",
    score: 88,
    grade: "B",
    tone: "tone-b",
    badges: ["피지 조절", "모공"]
  },
  {
    brand: "HERBARIUM",
    name: "Calming Centella Ampoule",
    ingredients: "마데카소사이드 · 알란토인",
    score: 91,
    grade: "A",
    tone: "tone-c",
    badges: ["진정", "주의 성분 없음"]
  }
];

function App() {
  const apiBaseUrl = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000/api";

  return (
    <main className="app-shell">
      <header className="site-header">
        <a className="brand-mark" href="/">
          뭐바를래
        </a>
        <nav className="header-actions" aria-label="개발 환경 확인">
          <a href={`${apiBaseUrl}/health`}>API</a>
          <span>DEV</span>
        </nav>
      </header>

      <section className="search-hero" aria-labelledby="hero-title">
        <p className="eyebrow">Evidence-led skincare</p>
        <h1 id="hero-title" className="serif hero-title">
          피부 고민을 쓰면 <br />
          성분 근거로 고릅니다
        </h1>
        <p className="hero-copy">
          수부지, 모공, 좁쌀, 진정처럼 복잡한 고민을 한 문장으로 남기면 필요한 효능과 성분을 먼저
          정리합니다.
        </p>

        <form className="search-form">
          <label className="field-label" htmlFor="concern">
            피부 고민
          </label>
          <div className="field-row">
            <input
              id="concern"
              className="concern-input"
              placeholder="수부지인데 모공 넓고 좁쌀 여드름이 있어요"
              maxLength={100}
            />
            <button className="primary-button" type="button">
              추천 시작
            </button>
          </div>
        </form>
      </section>

      <section className="preview-section" aria-labelledby="preview-title">
        <div className="section-heading">
          <p className="eyebrow">Recommendation preview</p>
          <h2 id="preview-title" className="serif section-title">
            결과는 이렇게 보여줄 예정입니다
          </h2>
        </div>

        <div className="product-grid">
          {previewProducts.map((product) => (
            <article className="product-card" key={product.name}>
              <div className={`product-thumb ${product.tone}`} aria-hidden="true" />
              <div className="product-body">
                <p className="eyebrow">{product.brand}</p>
                <h3 className="serif product-name">{product.name}</h3>
                <p className="ingredients">{product.ingredients}</p>
                <div className="badges">
                  {product.badges.map((badge) => (
                    <span className="badge" key={badge}>
                      {badge}
                    </span>
                  ))}
                </div>
                <div className="card-foot">
                  <div>
                    <span className="score-label">추천점수</span>
                    <strong className="serif score">{product.score}</strong>
                  </div>
                  <div className={`grade grade-${product.grade}`}>{product.grade}</div>
                </div>
              </div>
            </article>
          ))}
        </div>
      </section>
    </main>
  );
}

export default App;
