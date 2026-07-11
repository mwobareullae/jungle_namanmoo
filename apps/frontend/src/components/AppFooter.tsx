const footerUtilityLinks = ["회사소개", "이용약관", "개인정보처리방침"];

const supportLinks = [
  ["주문배송", "/mypage/orders"],
  ["교환반품 안내", "/#defaultSection"],
  ["1:1 문의", "/#defaultSection"]
] as const;

function AppFooter() {
  return (
    <footer>
      <nav className="footer-utility" aria-label="푸터 주요 링크">
        <div className="footer-utility-inner">
          {footerUtilityLinks.map((item) => (
            <a href="/#defaultSection" key={item}>
              {item}
            </a>
          ))}
        </div>
      </nav>

      <div className="footer-inner">
        <div className="footer-brand">
          <a className="logo" href="/">
            뭐바를래
          </a>
          <p className="footer-desc">
            피부 고민에서 시작해 성분 근거와 피부 데이터로
            <br />
            더 나은 선택을 돕습니다.
          </p>
        </div>
        <div className="footer-col footer-support">
          <h5>고객지원</h5>
          <ul>
            {supportLinks.map(([label, href]) => (
              <li key={label}>
                <a href={href}>{label}</a>
              </li>
            ))}
          </ul>
        </div>

        <div className="footer-company" aria-label="회사 안내">
          <strong>뭐바를래</strong>
          <p>성분 근거 기반 뷰티 커머스</p>
          <p>피부 고민에 맞는 제품을 찾아보세요.</p>
        </div>
      </div>

      <div className="footer-bottom">
        <span>© 2026 뭐바를래. All rights reserved.</span>
      </div>
    </footer>
  );
}

export default AppFooter;
