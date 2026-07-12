const supportLinks = [
  ["Q&A", "/#defaultSection"],
  ["교환·반품 안내", "/#defaultSection"]
] as const;

const policyLinks = ["이용약관", "개인정보처리방침"];

function AppFooter() {
  return (
    <footer>
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

        <div className="footer-col">
          <h5>약관·정보</h5>
          <ul>
            {policyLinks.map((label) => (
              <li key={label}>
                <a href="/#defaultSection">{label}</a>
              </li>
            ))}
          </ul>
        </div>
      </div>

      <div className="footer-bottom">
        <span>© 2026 뭐바를래. All rights reserved.</span>
      </div>
    </footer>
  );
}

export default AppFooter;
