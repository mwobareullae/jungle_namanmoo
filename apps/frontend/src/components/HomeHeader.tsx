import { useEffect, useState, type MouseEvent } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { useLocation, useNavigate } from "react-router-dom";
import { useAuth } from "../contexts/useAuth";
import { cartQueryKey, useCartQuery } from "../hooks/useCartQuery";
import { navigateWithinApp } from "../lib/navigation";
import { callOriginal } from "../lib/originalRuntime";
import { getSavedSkinProfile } from "../lib/profileApi";
import type { RecommendationProfile } from "../types/recommendation";
import CategoryPanelOverlay from "./CategoryPanelOverlay";
import HeaderSearchPanel from "./HeaderSearchPanel";

function HomeHeader() {
  const location = useLocation();
  const navigate = useNavigate();
  const { user, logout } = useAuth();
  const queryClient = useQueryClient();
  const cartQuery = useCartQuery(user?.id ?? null);
  const cartCount = cartQuery.data?.total_quantity ?? 0;
  const [isCategoryMenuOpen, setIsCategoryMenuOpen] = useState(false);
  const [isHeaderSearchOpen, setIsHeaderSearchOpen] = useState(false);
  const [searchProfile, setSearchProfile] = useState<RecommendationProfile>({
    skin: "수부지",
    sensitivity: "보통",
    avoidIngredients: []
  });
  const currentPath = `${location.pathname}${location.search}${location.hash}`;
  const isPopularPage = location.pathname === "/products/popular";
  const isNewProductsPage = location.pathname === "/products/new";
  const isCatalogSearchPage = location.pathname === "/catalog-search";
  const isBrandsPage = location.pathname === "/brands";
  const isProductDetailPreviewPage = ["/product-detail", "/product-detail-preview"].includes(location.pathname);
  const isSkinTestPage = location.pathname.startsWith("/skin-test");
  const displayName = user?.nickname?.trim() || user?.email.split("@")[0] || "고객";
  const isCategoryHoverArea = (target: EventTarget | null) => {
    if (!(target instanceof Node)) return false;

    const panel = document.getElementById("categoryPanel");
    const header = document.querySelector("header.site-header");

    return Boolean(header?.contains(target) || panel?.contains(target));
  };
  const handleCategoryAreaLeave = (event: MouseEvent<HTMLElement>) => {
    if (!isCategoryMenuOpen) return;
    if (!isCategoryHoverArea(event.relatedTarget)) {
      callOriginal("closeCategoryMenu");
      setIsCategoryMenuOpen(false);
    }
  };
  const handleWishlistClick = () => {
    if (user) {
      navigate("/mypage/wishlist");
      return;
    }

    navigate("/login", {
      state: {
        from: currentPath
      }
    });
  };

  const handleInternalLinkClick = (event: MouseEvent<HTMLAnchorElement>, path: string) => {
    if (event.defaultPrevented || event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) {
      return;
    }

    event.preventDefault();
    navigate(path);
  };

  useEffect(() => {
    if (isProductDetailPreviewPage && document.body.classList.contains("category-menu-open")) {
      callOriginal("closeCategoryMenu");
      queueMicrotask(() => setIsCategoryMenuOpen(false));
    }
  }, [isProductDetailPreviewPage]);

  useEffect(() => {
    const handleCartUpdated = () => {
      void queryClient.invalidateQueries({ queryKey: cartQueryKey(user?.id ?? null) });
    };

    window.addEventListener("cart:updated", handleCartUpdated);

    return () => {
      window.removeEventListener("cart:updated", handleCartUpdated);
    };
  }, [queryClient, user?.id]);

  useEffect(() => {
    let isMounted = true;
    if (!user) {
      setSearchProfile({ skin: "수부지", sensitivity: "보통", avoidIngredients: [] });
      return () => {
        isMounted = false;
      };
    }

    getSavedSkinProfile().then((profile) => {
      if (isMounted && profile) setSearchProfile(profile);
    });

    return () => {
      isMounted = false;
    };
  }, [user]);

  useEffect(() => {
    setIsHeaderSearchOpen(false);
  }, [location.pathname, location.search]);

  const handleLogout = async () => {
    try {
      await logout();
      queryClient.removeQueries({ queryKey: cartQueryKey(user?.id ?? null) });
      callOriginal("showToast", "로그아웃되었습니다.");
    } catch {
      callOriginal("showToast", "로그아웃에 실패했습니다. 잠시 후 다시 시도해주세요.");
    } finally {
      await navigateWithinApp("/");
    }
  };

  return (
    <>
      <CategoryPanelOverlay onOpenChange={setIsCategoryMenuOpen} />
      <header className={`site-header${isHeaderSearchOpen ? " is-header-search-open" : ""}`} onMouseLeave={handleCategoryAreaLeave}>
        <div className={`header-inner${isHeaderSearchOpen ? " is-header-search-open" : ""}`}>
          <div className="header-brand">
            <button
              aria-controls="categoryPanel"
              aria-expanded={isCategoryMenuOpen}
              aria-label="카테고리 메뉴 열기"
              className="category-menu-btn"
              onClick={() => {
                callOriginal("openCategoryMenu");
                setIsCategoryMenuOpen(true);
              }}
              onMouseEnter={isProductDetailPreviewPage ? undefined : () => {
                callOriginal("openCategoryMenu");
                setIsCategoryMenuOpen(true);
              }}
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
            <a className="logo" data-agent-home-target href="/" onClick={(event) => handleInternalLinkClick(event, "/")}>
              뭐바를래
            </a>
          </div>
          <nav>
            <a className={isNewProductsPage ? "nav-active" : ""} href="/products/new" onClick={(event) => handleInternalLinkClick(event, "/products/new")}>신상품</a>
            <a className={isPopularPage ? "nav-active" : ""} href="/products/popular" onClick={(event) => handleInternalLinkClick(event, "/products/popular")}>베스트</a>
            <a className={isBrandsPage ? "nav-active" : ""} href="/brands" onClick={(event) => handleInternalLinkClick(event, "/brands")}>브랜드</a>
            <a className={isSkinTestPage ? "nav-ai" : ""} href="/skin-test" onClick={(event) => handleInternalLinkClick(event, "/skin-test")}>
              맞춤 추천
            </a>
          </nav>
          <div className={`header-search-slot${isHeaderSearchOpen ? " is-open" : ""}`}>
            {isHeaderSearchOpen ? <HeaderSearchPanel onClose={() => setIsHeaderSearchOpen(false)} profile={searchProfile} /> : null}
          </div>
          <div className="header-actions">
            <button
              aria-controls="header-search-panel"
              aria-expanded={isHeaderSearchOpen}
              aria-label={isHeaderSearchOpen ? "검색 닫기" : "검색 열기"}
              className={`icon-btn${isHeaderSearchOpen ? " is-search-open" : ""}${isCatalogSearchPage ? " nav-active" : ""}`}
              data-header-search-toggle
              onClick={() => setIsHeaderSearchOpen((isOpen) => !isOpen)}
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
                <circle cx="11" cy="11" r="8" />
                <path d="m21 21-4.35-4.35" />
              </svg>
            </button>
            <button
              aria-label="찜한 상품으로 이동"
              className="icon-btn"
              data-commerce-only
              onClick={handleWishlistClick}
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
              data-agent-cart-navigation-target
              data-commerce-only
              aria-label="장바구니로 이동"
              onClick={() => navigate("/cart")}
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
                {cartCount}
              </span>
            </button>
            {user ? (
              <>
                <a className="btn-login header-user-link" data-commerce-only href="/mypage" onClick={(event) => handleInternalLinkClick(event, "/mypage")}>
                  <span className="header-user-icon" aria-hidden="true">
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
                      <path d="M20 21a8 8 0 0 0-16 0" />
                      <circle cx="12" cy="7" r="4" />
                    </svg>
                  </span>
                  <span className="header-user-name">{displayName}님</span>
                </a>
                <span aria-hidden="true" className="header-action-divider">
                  |
                </span>
                <button
                  className="btn-login header-logout-button"
                  data-auth-state="authenticated"
                  data-commerce-only
                  onClick={handleLogout}
                  type="button"
                >
                  <span className="header-logout-icon" aria-hidden="true">
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
                      <path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4" />
                      <path d="M16 17l5-5-5-5" />
                      <path d="M21 12H9" />
                    </svg>
                  </span>
                  로그아웃
                </button>
              </>
            ) : (
              <a
                className="btn-login"
                data-agent-login-target
                data-auth-state="guest"
                data-commerce-only
                href="#"
                onClick={(event) => {
                  event.preventDefault();
                  navigate("/login", {
                    state: {
                      from: currentPath
                    }
                  });
                }}
              >
                로그인
              </a>
            )}
          </div>
        </div>
      </header>
    </>
  );
}

export default HomeHeader;
