import { useLocation, useNavigate } from "react-router-dom";
import { callOriginal } from "../lib/originalRuntime";

function HomeHeader() {
  const defaultSectionHref = "/#defaultSection";
  const location = useLocation();
  const navigate = useNavigate();
  const currentPath = `${location.pathname}${location.search}${location.hash}`;

  return (
    <header>
      <div className="header-inner">
        <div className="header-brand">
          <button
            aria-controls="categoryPanel"
            aria-expanded="false"
            aria-label="카테고리 메뉴 열기"
            className="category-menu-btn"
            onClick={() => callOriginal("toggleCategoryMenu")}
            type="button"
          >
            <svg
              fill="none"
              height="22"
              stroke="currentColor"
              strokeLinecap="round"
              strokeWidth="2"
              viewBox="0 0 24 24"
              width="22"
            >
              <path d="M4 7h16M4 12h16M4 17h16" />
            </svg>
          </button>
          <a className="logo" href="/">
            뭐바를래
          </a>
        </div>
        <nav>
          <a href={defaultSectionHref}>신상품</a>
          <a href={defaultSectionHref}>베스트</a>
          <a href={defaultSectionHref}>스킨케어</a>
          <a href={defaultSectionHref}>메이크업</a>
          <a href={defaultSectionHref}>헤어/바디</a>
          <a href={defaultSectionHref}>브랜드</a>
          <a className="nav-ai" href="/skin-test">
            맞춤 추천
          </a>
        </nav>
        <div className="header-actions">
          <button className="icon-btn" onClick={() => callOriginal("focusSearch")} type="button">
            <svg
              fill="none"
              height="18"
              stroke="currentColor"
              strokeLinecap="round"
              strokeLinejoin="round"
              strokeWidth="2"
              viewBox="0 0 24 24"
              width="18"
            >
              <circle cx="11" cy="11" r="8" />
              <path d="m21 21-4.35-4.35" />
            </svg>
          </button>
          <button
            className="icon-btn"
            data-commerce-only
            onClick={() => callOriginal("showToast", "찜 기능은 준비 중입니다")}
            type="button"
          >
            <svg
              fill="none"
              height="18"
              stroke="currentColor"
              strokeLinecap="round"
              strokeLinejoin="round"
              strokeWidth="2"
              viewBox="0 0 24 24"
              width="18"
            >
              <path d="M20.84 4.61a5.5 5.5 0 0 0-7.78 0L12 5.67l-1.06-1.06a5.5 5.5 0 0 0-7.78 7.78l1.06 1.06L12 21.23l7.78-7.78 1.06-1.06a5.5 5.5 0 0 0 0-7.78z" />
            </svg>
          </button>
          <button
            className="icon-btn"
            data-commerce-only
            onClick={() => callOriginal("toggleCart")}
            type="button"
          >
            <svg
              fill="none"
              height="18"
              stroke="currentColor"
              strokeLinecap="round"
              strokeLinejoin="round"
              strokeWidth="2"
              viewBox="0 0 24 24"
              width="18"
            >
              <path d="M6 2 3 6v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2V6l-3-4z" />
              <line x1="3" x2="21" y1="6" y2="6" />
              <path d="M16 10a4 4 0 0 1-8 0" />
            </svg>
            <span className="badge" id="headerCartBadge">
              0
            </span>
          </button>
          <a
            className="btn-login"
            data-commerce-only
            href="#"
            onClick={(event) => {
              event.preventDefault();
              navigate("/login", {
                state: {
                  from: currentPath,
                },
              });
            }}
          >
            로그인
          </a>
        </div>
      </div>
    </header>
  );
}

export default HomeHeader;
