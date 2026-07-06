const productRows = [
  {
    id: "P-24585",
    name: "토리든 다이브인 저분자 히알루론산 세럼",
    brand: "토리든",
    status: "판매중",
    inventory: 124,
    price: "24,000",
    updatedAt: "10분 전"
  },
  {
    id: "P-23911",
    name: "라운드랩 1025 독도 토너",
    brand: "라운드랩",
    status: "검수필요",
    inventory: 18,
    price: "15,000",
    updatedAt: "32분 전"
  },
  {
    id: "P-23104",
    name: "아누아 어성초 77 수딩 토너",
    brand: "아누아",
    status: "품절임박",
    inventory: 6,
    price: "22,000",
    updatedAt: "1시간 전"
  },
  {
    id: "P-22087",
    name: "에스트라 아토베리어365 크림",
    brand: "에스트라",
    status: "판매중",
    inventory: 73,
    price: "33,000",
    updatedAt: "오늘"
  }
];

const queueItems = [
  { label: "상품 검수 대기", count: 18, note: "성분 매핑 확인 필요" },
  { label: "재고 임계치 이하", count: 42, note: "10개 미만 상품" },
  { label: "이미지 누락", count: 7, note: "대표 이미지 필요" },
  { label: "가격 미확정", count: 12, note: "판매가 검증 필요" }
];

const stats = [
  { label: "전체 상품", value: "24,585", helper: "현재 로직 대상" },
  { label: "추천 가능", value: "10,167", helper: "is_recommendable" },
  { label: "오늘 주문", value: "128", helper: "mock 결제 포함" },
  { label: "처리 필요", value: "79", helper: "검수/재고/이미지" }
];

const navItems = [
  "대시보드",
  "상품 조회",
  "상품 등록",
  "재고 관리",
  "주문 관리",
  "QA 리포트",
  "검색/추천"
];

function AdminDashboardPage() {
  return (
    <main className="admin-shell">
      <aside className="admin-sidebar" aria-label="관리자 메뉴">
        <a className="admin-brand" href="/">
          <span className="admin-brand-mark">뭐</span>
          <span>
            <strong>뭐바를래</strong>
            <small>Admin</small>
          </span>
        </a>
        <nav className="admin-nav">
          {navItems.map((item) => (
            <a className={item === "대시보드" ? "active" : ""} href="#admin-dashboard" key={item}>
              {item}
            </a>
          ))}
        </nav>
        <div className="admin-sidebar-status">
          <span>dev</span>
          <strong>운영 점검 모드</strong>
        </div>
      </aside>

      <section className="admin-main" id="admin-dashboard">
        <header className="admin-topbar">
          <div>
            <p>상품 운영</p>
            <h1>관리자 대시보드</h1>
          </div>
          <div className="admin-topbar-actions">
            <button className="admin-secondary-button" type="button">
              CSV 업로드
            </button>
            <button className="admin-primary-button" type="button">
              상품 등록
            </button>
          </div>
        </header>

        <section className="admin-stats" aria-label="운영 지표">
          {stats.map((item) => (
            <article className="admin-stat" key={item.label}>
              <span>{item.label}</span>
              <strong>{item.value}</strong>
              <small>{item.helper}</small>
            </article>
          ))}
        </section>

        <section className="admin-workspace">
          <div className="admin-panel admin-product-panel">
            <div className="admin-panel-header">
              <div>
                <p>상품 관리</p>
                <h2>상품 조회</h2>
              </div>
              <div className="admin-filter-row" role="search">
                <input aria-label="상품 검색" placeholder="상품명, 브랜드, 상품 ID 검색" type="search" />
                <select aria-label="상품 상태">
                  <option>전체 상태</option>
                  <option>판매중</option>
                  <option>검수필요</option>
                  <option>품절임박</option>
                </select>
                <button className="admin-secondary-button" type="button">
                  검색
                </button>
              </div>
            </div>

            <div className="admin-table-wrap">
              <table className="admin-table">
                <thead>
                  <tr>
                    <th scope="col">상품 ID</th>
                    <th scope="col">상품명</th>
                    <th scope="col">브랜드</th>
                    <th scope="col">상태</th>
                    <th scope="col">재고</th>
                    <th scope="col">판매가</th>
                    <th scope="col">수정</th>
                  </tr>
                </thead>
                <tbody>
                  {productRows.map((product) => (
                    <tr key={product.id}>
                      <td>{product.id}</td>
                      <td className="admin-product-name">{product.name}</td>
                      <td>{product.brand}</td>
                      <td>
                        <span className={`admin-status ${statusClass(product.status)}`}>{product.status}</span>
                      </td>
                      <td>{product.inventory}</td>
                      <td>{product.price}원</td>
                      <td>{product.updatedAt}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>

          <aside className="admin-side-panels">
            <section className="admin-panel">
              <div className="admin-panel-header compact">
                <div>
                  <p>처리 대기</p>
                  <h2>오늘 할 일</h2>
                </div>
              </div>
              <div className="admin-queue-list">
                {queueItems.map((item) => (
                  <button className="admin-queue-item" key={item.label} type="button">
                    <span>
                      <strong>{item.label}</strong>
                      <small>{item.note}</small>
                    </span>
                    <b>{item.count}</b>
                  </button>
                ))}
              </div>
            </section>

            <section className="admin-panel">
              <div className="admin-panel-header compact">
                <div>
                  <p>검색/추천</p>
                  <h2>데이터 상태</h2>
                </div>
              </div>
              <dl className="admin-health-list">
                <div>
                  <dt>검색 조인 문서</dt>
                  <dd>24,585</dd>
                </div>
                <div>
                  <dt>임베딩 완료</dt>
                  <dd>24,585</dd>
                </div>
                <div>
                  <dt>alias 후보</dt>
                  <dd>CSV 산출 대기</dd>
                </div>
              </dl>
            </section>
          </aside>
        </section>
      </section>
    </main>
  );
}

function statusClass(status: string) {
  if (status === "판매중") {
    return "success";
  }
  if (status === "품절임박") {
    return "warning";
  }
  return "review";
}

export default AdminDashboardPage;
