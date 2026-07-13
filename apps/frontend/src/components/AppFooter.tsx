const shoppingLinks = [
  ["신상품", "/products/new"],
  ["베스트", "/products/popular"],
  ["상품 검색", "/catalog-search"],
  ["맞춤 추천", "/skin-test"]
] as const;

const accountLinks = [
  ["마이페이지", "/mypage"],
  ["찜한 상품", "/mypage/wishlist"],
  ["최근 본 상품", "/mypage/recent"],
  ["주문/배송내역", "/mypage/orders"],
  ["반품·교환·환불", "/returns"],
  ["이용약관", "/terms"],
  ["개인정보처리방침", "/privacy"]
] as const;

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
        <div className="footer-col">
          <h5>쇼핑</h5>
          <ul>
            {shoppingLinks.map(([label, href]) => (
              <li key={label}>
                <a href={href}>{label}</a>
              </li>
            ))}
          </ul>
        </div>

        <div className="footer-col">
          <h5>내 정보·약관</h5>
          <ul>
            {accountLinks.map(([label, href]) => (
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
