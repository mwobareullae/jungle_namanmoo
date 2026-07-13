const serviceLinks = [
  ["신상품", "/products/new"],
  ["베스트", "/products/popular"],
  ["AI 검색", "/catalog-search"]
] as const;
const policyLinks = [
  ["이용안내", "/terms"],
  ["이용약관", "/terms"],
  ["개인정보취급방침", "/privacy"]
] as const;

type AppFooterProps = {
  variant?: "default" | "home";
};

function AppFooter({ variant = "default" }: AppFooterProps) {
  return (
    <footer className={variant === "home" ? "app-footer app-footer--home" : "app-footer"}>
      <div className="footer-inner">
        <div className="footer-brand">
          <a className="logo" href="/">
            뭐바를래
          </a>
          <p className="footer-company">
            피부 고민에서 시작해 성분 근거와 피부 데이터로
            <br />
            더 나은 화장품 선택을 돕습니다.
          </p>
        </div>
        <div className="footer-col footer-service">
          <h5>Service</h5>
          <ul>
            {serviceLinks.map(([label, href]) => (
              <li key={label}>
                <a href={href}>{label}</a>
              </li>
            ))}
          </ul>
        </div>
        <div className="footer-col footer-policy">
          <h5>Link</h5>
          <ul>
            {policyLinks.map(([label, href]) => (
              <li key={label}>
                <a href={href}>{label}</a>
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
