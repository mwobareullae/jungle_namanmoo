import { callOriginal } from "../lib/originalRuntime";

const categories = ["스킨케어", "메이크업/네일", "뷰티소품", "향수/디퓨저", "헤어케어", "바디케어"];

function HomeOverlays() {
  return (
    <>
      <div
        className="cart-overlay"
        data-commerce-only
        id="cartOverlay"
        onClick={() => callOriginal("toggleCart")}
      />

      <div className="cart-sidebar" data-commerce-only id="cartSidebar">
        <div className="cart-header">
          <h3>
            장바구니{" "}
            <span id="cartCount" style={{ color: "var(--accent-text)" }}>
              (0)
            </span>
          </h3>
          <button className="close-btn" onClick={() => callOriginal("toggleCart")} type="button">
            ✕
          </button>
        </div>
        <div className="cart-items">
          <div className="cart-empty">담긴 상품이 없습니다.</div>
        </div>
        <div className="cart-footer">
          <div
            style={{
              color: "var(--faint)",
              display: "flex",
              fontSize: 13,
              justifyContent: "space-between",
              marginBottom: 10,
            }}
          >
            <span>상품 0개</span>
            <span style={{ color: "var(--accent-text)", fontWeight: 500 }}>배송비 없음</span>
          </div>
          <div className="cart-total-row">
            <span className="cart-total-label">총 결제금액</span>
            <span className="cart-total-price">0원</span>
          </div>
          <button className="checkout-btn" disabled type="button">
            구매하기
          </button>
        </div>
      </div>

      <div className="toast" id="toast">
        <span className="toast-dot" />
        <span id="toastMsg">알림</span>
      </div>

      <div
        className="category-panel-backdrop"
        id="categoryPanelBackdrop"
        onClick={() => callOriginal("closeCategoryMenu")}
      />
      <aside aria-label="카테고리 메뉴" className="category-panel" id="categoryPanel">
        {categories.map((category) => (
          <a href="#" key={category}>
            {category}
          </a>
        ))}
      </aside>
    </>
  );
}

export default HomeOverlays;
