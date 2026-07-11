const footerColumns = [
  ["고객 지원", "공지사항", "자주 묻는 질문", "1:1 문의", "교환/반품 안내", "배송 조회"],
  ["쇼핑", "신상품", "베스트", "세일", "브랜드", "맞춤 추천"],
  ["회사", "회사소개", "이용약관", "개인정보처리방침", "입점 문의", "채용"]
];

const communityFooterColumns = [
  ["서비스", "맞춤 추천", "성분 가이드", "자주 묻는 질문"],
  ["회사", "회사소개", "이용약관", "개인정보처리방침"]
];

function AppFooter() {
  const columns = import.meta.env.VITE_APP_MODE === "community" ? communityFooterColumns : footerColumns;

  return (
    <footer>
      <div className="footer-inner">
        <div className="footer-brand">
          <a className="logo" href="/">
            뭐바를래
          </a>
          <p className="footer-desc">
            피부 고민에서 시작해 최적의 성분과 제품까지.
            <br />
            뭐바를래는 성분 함량과 근거 데이터를 함께 보고
            <br />
            납득 가능한 선택지를 골라드립니다.
          </p>
        </div>
        {columns.map(([title, ...items]) => (
          <div className="footer-col" key={title}>
            <h5>{title}</h5>
            <ul>
              {items.map((item) => (
                <li key={item}>
                  <a href={item === "베스트" ? "/products/popular" : "/#defaultSection"}>{item}</a>
                </li>
              ))}
            </ul>
          </div>
        ))}
      </div>
      <div className="footer-bottom">
        <span>© 2026 뭐바를래. All rights reserved.</span>
      </div>
    </footer>
  );
}

export default AppFooter;
