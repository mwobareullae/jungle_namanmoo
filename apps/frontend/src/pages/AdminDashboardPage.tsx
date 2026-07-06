import { useMemo, useState } from "react";

type AdminView = "dashboard" | "products" | "productForm";
type ProductStatus = "판매중" | "검수필요" | "품절임박" | "판매중지";
type ReviewStatus = "정상" | "성분 pending" | "이미지 누락" | "중복 확인";
type IndexStatus = "반영 완료" | "검색 문서 완료" | "임베딩 대기" | "미반영";
type BadgeTone = "success" | "warning" | "danger" | "neutral" | "review";

type ProductRow = {
  id: string;
  productCode: string;
  name: string;
  brand: string;
  price: number;
  stock: number;
  status: ProductStatus;
  reviewStatus: ReviewStatus;
  imageCount: number;
  ingredientState: string;
  indexStatus: IndexStatus;
  updatedAt: string;
};

const navItems: Array<{ label: string; view: AdminView | "excel" | "images" | "ingredients" | "stock" | "orders" }> = [
  { label: "대시보드", view: "dashboard" },
  { label: "상품 조회", view: "products" },
  { label: "상품 등록", view: "productForm" },
  { label: "엑셀 대량 등록", view: "excel" },
  { label: "이미지 등록", view: "images" },
  { label: "성분 매핑 검수", view: "ingredients" },
  { label: "재고·가격", view: "stock" },
  { label: "주문·결제", view: "orders" }
];

const stats = [
  { label: "전체 상품", value: "24,585" },
  { label: "추천 가능", value: "10,167" },
  { label: "판매중", value: "9,812" },
  { label: "검수 필요", value: "1,204" },
  { label: "품절 임박", value: "87" },
  { label: "이미지 누락", value: "342" },
  { label: "전성분 원문", value: "24,585" },
  { label: "인덱스 대기", value: "0" }
];

const initialProducts: ProductRow[] = [
  {
    id: "1",
    productCode: "prod_000245",
    name: "토리든 다이브인 저분자 히알루론산 세럼",
    brand: "토리든",
    price: 21800,
    stock: 142,
    status: "판매중",
    reviewStatus: "정상",
    imageCount: 5,
    ingredientState: "exact 38 / pending 0",
    indexStatus: "반영 완료",
    updatedAt: "2026-07-06 14:12"
  },
  {
    id: "2",
    productCode: "prod_bm_1021",
    name: "한율 달빛유자C 세럼",
    brand: "한율",
    price: 32000,
    stock: 18,
    status: "품절임박",
    reviewStatus: "성분 pending",
    imageCount: 4,
    ingredientState: "exact 34 / pending 2",
    indexStatus: "임베딩 대기",
    updatedAt: "2026-07-06 13:48"
  },
  {
    id: "3",
    productCode: "prod_001984",
    name: "차앤박 핑크토닝 딥인샷 앰플",
    brand: "CNP",
    price: 29800,
    stock: 64,
    status: "검수필요",
    reviewStatus: "성분 pending",
    imageCount: 3,
    ingredientState: "exact 29 / pending 3",
    indexStatus: "검색 문서 완료",
    updatedAt: "2026-07-06 12:02"
  },
  {
    id: "4",
    productCode: "prod_010014",
    name: "라운드랩 자작나무 수분 크림",
    brand: "라운드랩",
    price: 24000,
    stock: 0,
    status: "판매중지",
    reviewStatus: "이미지 누락",
    imageCount: 0,
    ingredientState: "exact 41 / pending 1",
    indexStatus: "미반영",
    updatedAt: "2026-07-05 19:22"
  },
  {
    id: "5",
    productCode: "prod_020771",
    name: "닥터지 레드 블레미쉬 클리어 수딩 크림",
    brand: "닥터지",
    price: 18900,
    stock: 203,
    status: "판매중",
    reviewStatus: "중복 확인",
    imageCount: 6,
    ingredientState: "exact 44 / pending 0",
    indexStatus: "반영 완료",
    updatedAt: "2026-07-05 18:41"
  }
];

const emptyProduct: ProductRow = {
  id: "draft",
  productCode: "seller_sku_new",
  name: "",
  brand: "",
  price: 0,
  stock: 0,
  status: "검수필요",
  reviewStatus: "성분 pending",
  imageCount: 0,
  ingredientState: "exact 0 / pending 0",
  indexStatus: "미반영",
  updatedAt: "저장 전"
};

const pendingItems = [
  {
    label: "성분 매핑 검수 대기",
    note: "pending 27,243종 · 연결 665,304건",
    status: "검수 필요",
    tone: "warning"
  },
  {
    label: "상품명 중복 후보",
    note: "2,590그룹 · 6,450개 상품",
    status: "확인 대기",
    tone: "neutral"
  },
  {
    label: "import 실패 행",
    note: "products_0706.xlsx · 12행",
    status: "실패 파일",
    tone: "danger"
  },
  {
    label: "이미지 자동 연결 실패",
    note: "image_batch_01.zip · 4개 파일",
    status: "매칭 실패",
    tone: "warning"
  },
  {
    label: "임베딩 자동 반영",
    note: "서버 OPENAI_API_KEY 준비 전 일배치",
    status: "키 대기",
    tone: "neutral"
  }
];

const importRows = [
  {
    time: "14:02",
    file: "products_0706.xlsx",
    success: 118,
    failed: 12,
    status: "부분 실패",
    tone: "danger"
  },
  {
    time: "10:31",
    file: "brand_a_products.xlsx",
    success: 42,
    failed: 0,
    status: "완료",
    tone: "success"
  },
  {
    time: "어제",
    file: "image_batch_01.zip",
    success: 310,
    failed: 4,
    status: "매칭 실패",
    tone: "warning"
  }
];

const orderSummary = [
  { label: "신규 주문", value: "36" },
  { label: "결제 완료", value: "31" },
  { label: "결제 대기", value: "5" },
  { label: "취소", value: "0" }
];

const indexSummary = [
  { label: "조인 문서", value: "24,585" },
  { label: "임베딩 반영", value: "24,585 / 24,585" },
  { label: "마지막 rebuild", value: "09:12 · 13.3초" }
];

const workflowCards = [
  {
    label: "엑셀 업로드",
    title: "상품 기본정보 자동 등록",
    detail: "성공 행 커밋 · 실패 행 결과 파일",
    status: "필수 포함",
    tone: "success"
  },
  {
    label: "이미지 업로드",
    title: "파일명/매핑표 자동 연결",
    detail: "OCR 자동 확정 금지 · 검수 보조",
    status: "가능",
    tone: "success"
  },
  {
    label: "성분",
    title: "전성분 원문 전체 저장",
    detail: "ingredients.csv 정규화 exact만 자동 연결",
    status: "보수 확정",
    tone: "warning"
  },
  {
    label: "검색 반영",
    title: "검색 문서 rebuild 자동 job",
    detail: "임베딩은 서버 키 준비 후 즉시 승격",
    status: "2단",
    tone: "neutral"
  }
];

const rebuildSteps = [
  {
    label: "검색 문서",
    value: "즉시 job",
    detail: "idx_prod_join_* 갱신",
    tone: "success"
  },
  {
    label: "임베딩",
    value: "키 대기",
    detail: "서버 키 준비 전 일배치/운영자 실행",
    tone: "warning"
  },
  {
    label: "최근 full 반영",
    value: "24,585 / 24,585",
    detail: "변경분만 재임베딩 확인",
    tone: "success"
  }
];

const ingredientPolicy = [
  { label: "저장", value: "전성분 원문 전체" },
  { label: "자동 연결", value: "정규화 exact match" },
  { label: "보류", value: "부분일치·OCR·복합 원료" }
];

function formatCurrency(value: number) {
  return `${value.toLocaleString("ko-KR")}원`;
}

function getStatusTone(status: ProductStatus | ReviewStatus | IndexStatus): BadgeTone {
  if (status === "판매중" || status === "정상" || status === "반영 완료" || status === "검색 문서 완료") {
    return "success";
  }

  if (status === "검수필요" || status === "성분 pending" || status === "품절임박" || status === "임베딩 대기") {
    return "warning";
  }

  if (status === "판매중지" || status === "이미지 누락" || status === "미반영") {
    return "danger";
  }

  return "neutral";
}

function AdminDashboardPage() {
  const [activeView, setActiveView] = useState<AdminView>("dashboard");
  const [products, setProducts] = useState<ProductRow[]>(initialProducts);
  const [selectedProductId, setSelectedProductId] = useState(initialProducts[0]?.id ?? "draft");
  const [query, setQuery] = useState("");
  const [statusFilter, setStatusFilter] = useState<ProductStatus | "전체">("전체");
  const [draftProduct, setDraftProduct] = useState<ProductRow>(initialProducts[0] ?? emptyProduct);

  const filteredProducts = useMemo(() => {
    const normalizedQuery = query.trim().toLowerCase();

    return products.filter((product) => {
      const matchesQuery = normalizedQuery
        ? [product.name, product.brand, product.productCode].some((value) =>
            value.toLowerCase().includes(normalizedQuery),
          )
        : true;
      const matchesStatus = statusFilter === "전체" ? true : product.status === statusFilter;

      return matchesQuery && matchesStatus;
    });
  }, [products, query, statusFilter]);

  const selectedProduct = products.find((product) => product.id === selectedProductId) ?? products[0] ?? emptyProduct;

  const handleOpenProductForm = (product: ProductRow) => {
    setSelectedProductId(product.id);
    setDraftProduct(product);
    setActiveView("productForm");
  };

  const handleNewProduct = () => {
    setSelectedProductId("draft");
    setDraftProduct({
      ...emptyProduct,
      productCode: `seller_sku_${products.length + 1}`,
      updatedAt: "저장 전"
    });
    setActiveView("productForm");
  };

  const handleSaveProduct = () => {
    const savedProduct: ProductRow = {
      ...draftProduct,
      id: draftProduct.id === "draft" ? `local_${Date.now()}` : draftProduct.id,
      imageCount: Number(draftProduct.imageCount) || 0,
      price: Number(draftProduct.price) || 0,
      stock: Number(draftProduct.stock) || 0,
      updatedAt: "로컬 미리보기 저장"
    };

    setProducts((currentProducts) => {
      if (draftProduct.id === "draft") {
        return [savedProduct, ...currentProducts];
      }

      return currentProducts.map((product) => (product.id === draftProduct.id ? savedProduct : product));
    });
    setSelectedProductId(savedProduct.id);
    setDraftProduct(savedProduct);
  };

  const renderDashboard = () => (
    <>
      <section className="admin-stats" aria-label="운영 지표">
        {stats.map((item) => (
          <article className="admin-stat" key={item.label}>
            <span>{item.label}</span>
            <strong>{item.value}</strong>
          </article>
        ))}
      </section>

      <section className="admin-grid">
        <section className="admin-panel admin-pending-panel">
          <div className="admin-panel-header">
            <div>
              <p>처리 대기</p>
              <h2>오늘 확인할 일</h2>
            </div>
          </div>
          <div className="admin-pending-list">
            {pendingItems.map((item) => (
              <button className="admin-pending-item" key={item.label} type="button">
                <span>
                  <strong>{item.label}</strong>
                  <small>{item.note}</small>
                </span>
                <b className={`admin-badge ${item.tone}`}>{item.status}</b>
              </button>
            ))}
          </div>
        </section>

        <section className="admin-panel admin-import-panel">
          <div className="admin-panel-header">
            <div>
              <p>최근 import job</p>
              <h2>엑셀·이미지 업로드 결과</h2>
            </div>
            <button className="admin-secondary-button" type="button">
              실패 파일
            </button>
          </div>
          <div className="admin-table-wrap">
            <table className="admin-table compact">
              <thead>
                <tr>
                  <th scope="col">시간</th>
                  <th scope="col">파일</th>
                  <th scope="col">성공</th>
                  <th scope="col">실패</th>
                  <th scope="col">상태</th>
                </tr>
              </thead>
              <tbody>
                {importRows.map((row) => (
                  <tr key={`${row.time}-${row.file}`}>
                    <td>{row.time}</td>
                    <td className="admin-file-name">{row.file}</td>
                    <td>{row.success}</td>
                    <td className={row.failed > 0 ? "admin-danger-text" : undefined}>{row.failed}</td>
                    <td>
                      <span className={`admin-badge ${row.tone}`}>{row.status}</span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>

        <section className="admin-panel">
          <div className="admin-panel-header compact">
            <div>
              <p>주문·결제</p>
              <h2>오늘 요약</h2>
            </div>
          </div>
          <dl className="admin-metric-list">
            {orderSummary.map((item) => (
              <div key={item.label}>
                <dt>{item.label}</dt>
                <dd>{item.value}</dd>
              </div>
            ))}
          </dl>
        </section>

        <section className="admin-panel">
          <div className="admin-panel-header compact">
            <div>
              <p>검색·추천</p>
              <h2>인덱스 상태</h2>
            </div>
            <span className="admin-badge success">정상</span>
          </div>
          <dl className="admin-metric-list">
            {indexSummary.map((item) => (
              <div key={item.label}>
                <dt>{item.label}</dt>
                <dd>{item.value}</dd>
              </div>
            ))}
          </dl>
        </section>

        <section className="admin-panel admin-workflow-panel">
          <div className="admin-panel-header compact">
            <div>
              <p>필수 기능 범위</p>
              <h2>자동 등록 운영 흐름</h2>
            </div>
            <span className="admin-badge success">팀장 확인</span>
          </div>
          <div className="admin-workflow-grid">
            {workflowCards.map((item) => (
              <article className="admin-workflow-card" key={item.label}>
                <div>
                  <span>{item.label}</span>
                  <strong>{item.title}</strong>
                  <small>{item.detail}</small>
                </div>
                <b className={`admin-badge ${item.tone}`}>{item.status}</b>
              </article>
            ))}
          </div>
        </section>

        <section className="admin-panel">
          <div className="admin-panel-header compact">
            <div>
              <p>자동 rebuild</p>
              <h2>검색·임베딩 반영</h2>
            </div>
          </div>
          <ol className="admin-rebuild-list">
            {rebuildSteps.map((item) => (
              <li key={item.label}>
                <span className={`admin-rebuild-dot ${item.tone}`} />
                <div>
                  <strong>{item.label}</strong>
                  <small>{item.detail}</small>
                </div>
                <b>{item.value}</b>
              </li>
            ))}
          </ol>
        </section>

        <section className="admin-panel">
          <div className="admin-panel-header compact">
            <div>
              <p>성분 정책</p>
              <h2>전성분 입력 기준</h2>
            </div>
            <span className="admin-badge warning">검수 병행</span>
          </div>
          <dl className="admin-metric-list">
            {ingredientPolicy.map((item) => (
              <div key={item.label}>
                <dt>{item.label}</dt>
                <dd>{item.value}</dd>
              </div>
            ))}
          </dl>
        </section>
      </section>
    </>
  );

  const renderProductList = () => (
    <section className="admin-panel admin-product-panel">
      <div className="admin-panel-header admin-product-header">
        <div>
          <p>상품 조회/상태 확인</p>
          <h2>상품 운영 목록</h2>
        </div>
        <div className="admin-filter-row">
          <input
            aria-label="상품 검색"
            onChange={(event) => setQuery(event.target.value)}
            placeholder="상품명, 브랜드, product_code"
            type="search"
            value={query}
          />
          <select
            aria-label="판매 상태 필터"
            onChange={(event) => setStatusFilter(event.target.value as ProductStatus | "전체")}
            value={statusFilter}
          >
            <option>전체</option>
            <option>판매중</option>
            <option>검수필요</option>
            <option>품절임박</option>
            <option>판매중지</option>
          </select>
          <button className="admin-primary-button" onClick={handleNewProduct} type="button">
            상품 등록
          </button>
        </div>
      </div>

      <div className="admin-table-wrap">
        <table className="admin-table admin-product-table">
          <thead>
            <tr>
              <th scope="col">상품</th>
              <th scope="col">가격/재고</th>
              <th scope="col">판매</th>
              <th scope="col">검수</th>
              <th scope="col">이미지</th>
              <th scope="col">성분</th>
              <th scope="col">인덱스</th>
              <th scope="col">수정</th>
            </tr>
          </thead>
          <tbody>
            {filteredProducts.map((product) => (
              <tr key={product.id}>
                <td>
                  <strong className="admin-product-name">{product.name}</strong>
                  <small className="admin-product-code">{product.brand} · {product.productCode}</small>
                </td>
                <td>
                  <strong>{formatCurrency(product.price)}</strong>
                  <small className={product.stock < 20 ? "admin-danger-text" : "admin-product-code"}>
                    재고 {product.stock.toLocaleString("ko-KR")}
                  </small>
                </td>
                <td>
                  <span className={`admin-badge ${getStatusTone(product.status)}`}>{product.status}</span>
                </td>
                <td>
                  <span className={`admin-badge ${getStatusTone(product.reviewStatus)}`}>
                    {product.reviewStatus}
                  </span>
                </td>
                <td>{product.imageCount}개</td>
                <td>{product.ingredientState}</td>
                <td>
                  <span className={`admin-badge ${getStatusTone(product.indexStatus)}`}>
                    {product.indexStatus}
                  </span>
                </td>
                <td>
                  <button
                    className="admin-text-button"
                    onClick={() => handleOpenProductForm(product)}
                    type="button"
                  >
                    열기
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="admin-list-summary">
        <span>표시 {filteredProducts.length}건</span>
        <span>API 연결 전 mock 데이터</span>
      </div>
    </section>
  );

  const renderProductForm = () => (
    <section className="admin-product-layout">
      <form className="admin-panel admin-product-form" onSubmit={(event) => event.preventDefault()}>
        <div className="admin-panel-header admin-product-header">
          <div>
            <p>상품 등록/수정</p>
            <h2>{draftProduct.id === "draft" ? "새 상품 등록" : "상품 기본정보 수정"}</h2>
          </div>
          <div className="admin-filter-row">
            <button className="admin-secondary-button" onClick={() => handleOpenProductForm(selectedProduct)} type="button">
              선택 상품 불러오기
            </button>
            <button className="admin-primary-button" onClick={handleSaveProduct} type="button">
              로컬 저장
            </button>
          </div>
        </div>

        <div className="admin-form-grid">
          <label>
            상품명
            <input
              onChange={(event) => setDraftProduct((product) => ({ ...product, name: event.target.value }))}
              placeholder="상품명을 입력하세요"
              value={draftProduct.name}
            />
          </label>
          <label>
            브랜드
            <input
              onChange={(event) => setDraftProduct((product) => ({ ...product, brand: event.target.value }))}
              placeholder="브랜드"
              value={draftProduct.brand}
            />
          </label>
          <label>
            product_code / seller SKU
            <input
              onChange={(event) => setDraftProduct((product) => ({ ...product, productCode: event.target.value }))}
              value={draftProduct.productCode}
            />
          </label>
          <label>
            판매가
            <input
              min="0"
              onChange={(event) => setDraftProduct((product) => ({ ...product, price: Number(event.target.value) }))}
              type="number"
              value={draftProduct.price}
            />
          </label>
          <label>
            재고
            <input
              min="0"
              onChange={(event) => setDraftProduct((product) => ({ ...product, stock: Number(event.target.value) }))}
              type="number"
              value={draftProduct.stock}
            />
          </label>
          <label>
            판매 상태
            <select
              onChange={(event) => setDraftProduct((product) => ({ ...product, status: event.target.value as ProductStatus }))}
              value={draftProduct.status}
            >
              <option>판매중</option>
              <option>검수필요</option>
              <option>품절임박</option>
              <option>판매중지</option>
            </select>
          </label>
          <label>
            이미지 파일명
            <input placeholder="product_code_main.jpg, product_code_01.jpg" />
          </label>
          <label>
            추천 가능 여부
            <select defaultValue="true">
              <option value="true">추천 가능</option>
              <option value="false">추천 제외</option>
            </select>
          </label>
          <label className="admin-form-wide">
            전성분 원문
            <textarea
              defaultValue="정제수, 부틸렌글라이콜, 나이아신아마이드, 판테놀, 소듐하이알루로네이트"
              rows={5}
            />
          </label>
        </div>
      </form>

      <aside className="admin-panel admin-form-aside">
        <div className="admin-panel-header compact">
          <div>
            <p>검수 상태</p>
            <h2>저장 전 확인</h2>
          </div>
        </div>
        <dl className="admin-metric-list">
          <div>
            <dt>성분 자동 연결</dt>
            <dd>정규화 exact만</dd>
          </div>
          <div>
            <dt>미확정 성분</dt>
            <dd>pending 보관</dd>
          </div>
          <div>
            <dt>이미지 연결</dt>
            <dd>파일명/매핑표</dd>
          </div>
          <div>
            <dt>검색 반영</dt>
            <dd>rebuild job 대기</dd>
          </div>
        </dl>
        <div className="admin-form-note">
          API 연결 전에는 로컬 미리보기 저장만 동작합니다. 실제 저장 시에는 상품 수정 API, 이미지 업로드 API,
          search document rebuild job이 필요합니다.
        </div>
      </aside>
    </section>
  );

  const viewTitle = activeView === "dashboard" ? "대시보드" : activeView === "products" ? "상품 조회" : "상품 등록";

  return (
    <main className="admin-shell">
      <aside className="admin-sidebar" aria-label="관리자 메뉴">
        <a className="admin-brand" href="/">
          <span className="admin-brand-mark">뭐</span>
          <span>
            <strong>뭐바를래</strong>
            <small>관리자</small>
          </span>
        </a>

        <nav className="admin-nav">
          {navItems.map((item) => (
            <button
              className={item.view === activeView ? "active" : ""}
              disabled={!["dashboard", "products", "productForm"].includes(item.view)}
              key={item.label}
              onClick={() => {
                if (item.view === "dashboard" || item.view === "products" || item.view === "productForm") {
                  if (item.view === "productForm" && selectedProductId !== "draft") {
                    setDraftProduct(selectedProduct);
                  }
                  setActiveView(item.view);
                }
              }}
              type="button"
            >
              {item.label}
            </button>
          ))}
        </nav>
      </aside>

      <section className="admin-main" id="admin-dashboard">
        <header className="admin-topbar">
          <div>
            <div className="admin-title-row">
              <p>{viewTitle}</p>
              <span>운영 확장</span>
            </div>
            <h1>상품 운영 관리자</h1>
          </div>
          <time dateTime="2026-07-06">2026-07-06 월</time>
        </header>

        {activeView === "dashboard" && renderDashboard()}
        {activeView === "products" && renderProductList()}
        {activeView === "productForm" && renderProductForm()}

        <p className="admin-footnote">
          판매중·검수 필요·품절 임박·이미지 누락·주문·import 수치는 화면 검토용 예시값입니다.
          검색/추천 인덱스와 pending 수치는 현재 프로젝트 실측 기준을 반영했습니다.
        </p>
      </section>
    </main>
  );
}

export default AdminDashboardPage;
