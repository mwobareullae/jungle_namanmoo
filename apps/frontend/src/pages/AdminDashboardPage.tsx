const navItems = [
  "대시보드",
  "상품 조회",
  "상품 등록",
  "엑셀 대량 등록",
  "이미지 등록",
  "성분 매핑 검수",
  "재고·가격",
  "주문·결제"
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

function AdminDashboardPage() {
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
            <a className={item === "대시보드" ? "active" : ""} href="#admin-dashboard" key={item}>
              {item}
            </a>
          ))}
        </nav>
      </aside>

      <section className="admin-main" id="admin-dashboard">
        <header className="admin-topbar">
          <div>
            <div className="admin-title-row">
              <p>대시보드</p>
              <span>운영 확장</span>
            </div>
            <h1>상품 운영 관리자</h1>
          </div>
          <time dateTime="2026-07-06">2026-07-06 월</time>
        </header>

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

        <p className="admin-footnote">
          판매중·검수 필요·품절 임박·이미지 누락·주문·import 수치는 화면 검토용 예시값입니다.
          검색/추천 인덱스와 pending 수치는 현재 프로젝트 실측 기준을 반영했습니다.
        </p>
      </section>
    </main>
  );
}

export default AdminDashboardPage;
