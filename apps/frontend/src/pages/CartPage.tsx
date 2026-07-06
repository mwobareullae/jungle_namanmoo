import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import CommercePageHeader from "../components/CommercePageHeader";
import HomeHeader from "../components/HomeHeader";
import { useAuth } from "../contexts/useAuth";
import { deleteCartItem, getCart, updateCartItem } from "../lib/cartApi";
import { getProductImageUrl } from "../lib/imageUrls";
import { navigateWithinApp } from "../lib/navigation";
import type { CartResponse } from "../types/cart";
import type { CartItem } from "../types/cart";

const TOTAL_DISCOUNT_AMOUNT = 0;
const FREE_SHIPPING_THRESHOLD = 30000;
const DEFAULT_SHIPPING_FEE = 3000;
const unavailableStockStatuses = new Set(["LOW_STOCK", "OUT_OF_STOCK", "SOLD_OUT", "UNAVAILABLE"]);
const unavailableSalesStatuses = new Set([
  "INACTIVE",
  "STOPPED",
  "SUSPENDED",
  "DISCONTINUED",
  "DELETED",
  "UNAVAILABLE",
  "NOT_FOR_SALE",
  "OUT_OF_SALE",
]);

const cartCategoryLabels: Record<string, string> = {
  serum: "세럼",
  toner: "토너",
  cream: "크림",
  mask: "마스크팩",
  cleanser: "클렌저",
  sunscreen: "선케어",
  makeup: "메이크업",
  skincare: "스킨케어",
};

const formatStockStatus = (stockStatus: string) => {
  switch (stockStatus) {
    case "IN_STOCK":
      return "재고 있음";
    case "LOW_STOCK":
      return "재고 부족";
    case "OUT_OF_STOCK":
    case "SOLD_OUT":
      return "품절";
    case "UNAVAILABLE":
      return "구매 불가";
    default:
      return "재고 확인 필요";
  }
};

const isPurchasableCartItem = (item: CartItem) =>
  !unavailableStockStatuses.has(item.product.stock_status) &&
  !unavailableSalesStatuses.has(item.product.sales_status);

const getStockStatusClassName = (stockStatus: string) => {
  if (unavailableStockStatuses.has(stockStatus)) {
    return " out";
  }

  if (stockStatus === "LOW_STOCK") {
    return " low";
  }

  if (stockStatus !== "IN_STOCK") {
    return " unknown";
  }

  return "";
};

const getCartCategoryLabel = (categoryName: string | null | undefined, categoryCode: string | null | undefined) => {
  if (categoryName) {
    return cartCategoryLabels[categoryName.toLowerCase()] ?? categoryName;
  }

  if (!categoryCode) {
    return "상품 정보";
  }

  return cartCategoryLabels[categoryCode.toLowerCase()] ?? "상품 정보";
};

function CartPage() {
  const navigate = useNavigate();
  const { isAuthLoading, user } = useAuth();
  const [cart, setCart] = useState<CartResponse | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [updatingItemId, setUpdatingItemId] = useState<number | null>(null);
  const [deletingItemId, setDeletingItemId] = useState<number | null>(null);
  const [isDeletingSelected, setIsDeletingSelected] = useState(false);
  const [isDeletingUnavailable, setIsDeletingUnavailable] = useState(false);
  const [selectedItemIds, setSelectedItemIds] = useState<number[]>([]);

  useEffect(() => {
    let isMounted = true;

    const loadCart = async () => {
      try {
        setIsLoading(true);
        setErrorMessage(null);

        const cartResponse = await getCart();

        if (isMounted) {
          setCart(cartResponse);
          setSelectedItemIds(cartResponse.items.filter(isPurchasableCartItem).map((item) => item.id));
        }
      } catch (error) {
        if (isMounted) {
          setErrorMessage(error instanceof Error ? error.message : "장바구니를 불러오지 못했습니다.");
        }
      } finally {
        if (isMounted) {
          setIsLoading(false);
        }
      }
    };

    void loadCart();

    return () => {
      isMounted = false;
    };
  }, []);

  const handleUpdateQuantity = async (itemId: number, nextQuantity: number) => {
    if (nextQuantity < 1) {
      return;
    }

    setUpdatingItemId(itemId);
    setErrorMessage(null);

    try {
      const updatedCart = await updateCartItem(itemId, { quantity: nextQuantity });
      setCart(updatedCart);
      setSelectedItemIds((currentIds) =>
        currentIds.filter((id) => updatedCart.items.some((item) => item.id === id && isPurchasableCartItem(item))),
      );
      window.dispatchEvent(new Event("cart:updated"));
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : "수량 변경에 실패했습니다.");
    } finally {
      setUpdatingItemId(null);
    }
  };

  const handleDeleteItem = async (itemId: number) => {
    setDeletingItemId(itemId);
    setErrorMessage(null);

    try {
      const response = await deleteCartItem(itemId);
      setCart(response.cart);
      setSelectedItemIds((currentIds) => currentIds.filter((id) => id !== itemId));
      window.dispatchEvent(new Event("cart:updated"));
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : "상품 삭제에 실패했습니다.");
    } finally {
      setDeletingItemId(null);
    }
  };

  const hasCartItems = Boolean(cart && cart.total_quantity > 0);
  const purchasableItemIds = cart ? cart.items.filter(isPurchasableCartItem).map((item) => item.id) : [];
  const allItemsSelected = Boolean(
    purchasableItemIds.length > 0 && selectedItemIds.length === purchasableItemIds.length,
  );
  const selectedItemIdSet = new Set(selectedItemIds);
  const selectedItems = cart ? cart.items.filter((item) => selectedItemIdSet.has(item.id) && isPurchasableCartItem(item)) : [];
  const selectedTotalQuantity = selectedItems.reduce((sum, item) => sum + item.quantity, 0);
  const selectedSubtotal = selectedItems.reduce((sum, item) => sum + item.line_subtotal, 0);
  const selectedShippingFee = selectedSubtotal <= 0
    ? 0
    : selectedSubtotal >= FREE_SHIPPING_THRESHOLD
      ? 0
      : DEFAULT_SHIPPING_FEE;
  const selectedShippingFeeLabel = selectedShippingFee === 0 ? "무료" : `${selectedShippingFee.toLocaleString()}원`;
  const unavailableItemIds = cart
    ? cart.items
        .filter((item) => !isPurchasableCartItem(item))
        .map((item) => item.id)
    : [];
  const hasUnavailableItems = unavailableItemIds.length > 0;

  const handleGoToCheckout = () => {
    if (selectedItems.length === 0) {
      return;
    }

    if (!user) {
      navigate("/login", { state: { from: "/cart" } });
      return;
    }

    const params = new URLSearchParams();
    selectedItems.forEach((item) => {
      params.append("cart_item_ids", String(item.id));
    });

    navigateWithinApp(`/checkout?${params.toString()}`);
  };

  const handleToggleSelectAll = () => {
    if (!cart) {
      return;
    }

    setSelectedItemIds(allItemsSelected ? [] : purchasableItemIds);
  };

  const handleToggleSelectItem = (item: CartItem) => {
    if (!isPurchasableCartItem(item)) {
      return;
    }

    setSelectedItemIds((currentIds) =>
      currentIds.includes(item.id)
        ? currentIds.filter((id) => id !== item.id)
        : [...currentIds, item.id],
    );
  };

  const handleDeleteSelected = async () => {
    if (selectedItemIds.length === 0) {
      return;
    }

    setIsDeletingSelected(true);
    setErrorMessage(null);

    try {
      let latestCart: CartResponse | null = null;

      for (const itemId of selectedItemIds) {
        const response = await deleteCartItem(itemId);
        latestCart = response.cart;
      }

      if (latestCart) {
        setCart(latestCart);
      }

      setSelectedItemIds([]);
      window.dispatchEvent(new Event("cart:updated"));
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : "선택한 상품 삭제에 실패했습니다.");
    } finally {
      setIsDeletingSelected(false);
    }
  };

  const handleDeleteUnavailableItems = async () => {
    if (unavailableItemIds.length === 0) {
      return;
    }

    setIsDeletingUnavailable(true);
    setErrorMessage(null);

    try {
      let latestCart: CartResponse | null = null;

      for (const itemId of unavailableItemIds) {
        const response = await deleteCartItem(itemId);
        latestCart = response.cart;
      }

      if (latestCart) {
        setCart(latestCart);
        setSelectedItemIds((currentIds) =>
          currentIds.filter((id) => latestCart?.items.some((item) => item.id === id && isPurchasableCartItem(item))),
        );
      }

      window.dispatchEvent(new Event("cart:updated"));
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : "구매 불가 상품 삭제에 실패했습니다.");
    } finally {
      setIsDeletingUnavailable(false);
    }
  };

  return (
    <>
      <HomeHeader />
      <main className="checkout-page cart-page">
        <section className="checkout-shell">
          <CommercePageHeader
            currentStep="cart"
            description="담아둔 상품을 확인하고 주문서로 이동해주세요."
            title="장바구니"
          />

          {isLoading && (
            <div className="cart-page-layout" aria-label="장바구니 로딩 중">
              <section className="cart-page-list-section">
                <div className="cart-page-section-head">
                  <div>
                    <span className="cart-skeleton cart-skeleton-label" />
                    <span className="cart-skeleton cart-skeleton-title" />
                  </div>
                  <span className="cart-skeleton cart-skeleton-count" />
                </div>

                <div className="cart-page-list">
                  <article className="cart-page-item">
                    <span className="cart-skeleton cart-skeleton-check" />
                    <div className="cart-page-item-main">
                      <span className="cart-skeleton cart-skeleton-brand" />
                      <span className="cart-skeleton cart-skeleton-name" />
                    </div>
                    <div className="cart-page-item-meta">
                      <span className="cart-skeleton cart-skeleton-quantity" />
                      <span className="cart-skeleton cart-skeleton-price" />
                    </div>
                  </article>
                </div>
              </section>

              <aside className="cart-page-summary-card">
                <span className="cart-skeleton cart-skeleton-summary-title" />
                <div>
                  <span>총 수량</span>
                  <span className="cart-skeleton cart-skeleton-summary-value" />
                </div>
                <div>
                  <span>상품 금액</span>
                  <span className="cart-skeleton cart-skeleton-summary-value" />
                </div>
                <button className="checkout-btn-main" disabled type="button">
                  구매하기
                </button>
              </aside>
            </div>
          )}

          {!isLoading && (errorMessage || !cart) && (
            <div className="cart-page-status-card">
              {errorMessage ? (
                <p>{errorMessage}</p>
              ) : (
                <p>장바구니 정보가 없습니다.</p>
              )}
            </div>
          )}

          {!isLoading && !errorMessage && cart && cart.total_quantity === 0 && (
            <div className="cart-page-empty-state">
              <h2>장바구니가 비어 있습니다.</h2>
              <p>마음에 드는 상품을 담으면 여기에서 수량과 주문 금액을 확인할 수 있습니다.</p>
              <button type="button" onClick={() => navigateWithinApp("/")}>
                상품 보러가기
              </button>
            </div>
          )}

          {cart && cart.warnings.length > 0 && (
            <div className="cart-page-warning-list">
              {cart.warnings.map((warning) => (
                <div
                  className={`cart-page-warning${warning.severity === "BLOCKING" ? " blocking" : ""}`}
                  key={`${warning.code}-${warning.item_id ?? warning.product_id ?? warning.message}`}
                >
                  <strong>{warning.severity === "BLOCKING" ? "구매 불가" : "확인 필요"}</strong>
                  <p>{warning.message}</p>
                </div>
              ))}
            </div>
          )}

          {cart && hasCartItems && (
            <div className="cart-page-layout">
              <section className="cart-page-list-section">
                <div className="cart-page-section-head">
                  <div>
                    <h2>구매할 상품을 확인해주세요</h2>
                  </div>
                </div>

                <div className="cart-page-selection-bar">
                  <label className="cart-page-select-all">
                    <input checked={allItemsSelected} onChange={handleToggleSelectAll} type="checkbox" />
                    <span>전체선택</span>
                  </label>
                  <div className="cart-page-selection-actions">
                    <button
                      disabled={selectedItemIds.length === 0 || isDeletingSelected}
                      onClick={handleDeleteSelected}
                      type="button"
                    >
                      선택상품 삭제
                    </button>
                    <button
                      disabled={!hasUnavailableItems || isDeletingUnavailable}
                      onClick={handleDeleteUnavailableItems}
                      type="button"
                    >
                      구매불가상품 삭제
                    </button>
                  </div>
                </div>

                <div className="cart-page-list">
                  {cart.items.map((item) => {
                    const imageUrl = getProductImageUrl(item.product.thumbnail_url, "w400");
                    const categoryLabel = getCartCategoryLabel(item.product.category_name, item.product.category_code);
                    const isUnavailableItem = !isPurchasableCartItem(item);
                    const stockStatusClassName = getStockStatusClassName(item.product.stock_status);

                    return (
                      <article className={`cart-page-item${isUnavailableItem ? " unavailable" : ""}`} key={item.id}>
                        <label className="cart-page-item-check">
                          <input
                            checked={selectedItemIdSet.has(item.id)}
                            disabled={isUnavailableItem}
                            onChange={() => handleToggleSelectItem(item)}
                            type="checkbox"
                          />
                          <span className="sr-only">{item.product.name} 선택</span>
                        </label>

                        <div className="cart-page-item-thumb">
                          {imageUrl ? (
                            <img alt={item.product.name} src={imageUrl} />
                          ) : (
                            <span>이미지 준비중</span>
                          )}
                        </div>

                        <div className="cart-page-item-main">
                          <p className="cart-page-item-brand">{item.product.brand}</p>
                          <h2 className="cart-page-item-name">{item.product.name}</h2>
                          <div className="cart-page-item-details">
                            <span>{categoryLabel}</span>
                            <span className={`cart-page-stock-badge${stockStatusClassName}`}>
                              {formatStockStatus(item.product.stock_status)}
                            </span>
                          </div>
                          <p className="cart-page-item-sub">
                            {categoryLabel} · {formatStockStatus(item.product.stock_status)}
                          </p>
                        </div>

                        <div className="cart-page-item-meta">
                          <div className="cart-page-quantity-control" aria-label={`${item.product.name} 수량`}>
                            <button
                              aria-label={`${item.product.name} 수량 감소`}
                              disabled={isUnavailableItem || updatingItemId === item.id || item.quantity <= 1}
                              onClick={() => handleUpdateQuantity(item.id, item.quantity - 1)}
                              type="button"
                            >
                              -
                            </button>
                            <span>{item.quantity}개</span>
                            <button
                              aria-label={`${item.product.name} 수량 증가`}
                              disabled={isUnavailableItem || updatingItemId === item.id}
                              onClick={() => handleUpdateQuantity(item.id, item.quantity + 1)}
                              type="button"
                            >
                              +
                            </button>
                          </div>
                          <div className="cart-page-item-price">
                            <span>상품 금액</span>
                            <strong>{item.line_subtotal.toLocaleString()}원</strong>
                          </div>
                          <button
                            className="cart-page-remove-button"
                            disabled={deletingItemId === item.id || updatingItemId === item.id}
                            onClick={() => handleDeleteItem(item.id)}
                            type="button"
                          >
                            삭제
                          </button>
                        </div>
                      </article>
                    );
                  })}
                </div>
              </section>

              <aside className="cart-page-summary-card">
                <h2>주문 요약</h2>
                <div>
                  <span>상품 수량</span>
                  <strong>{selectedTotalQuantity}개</strong>
                </div>
                <div>
                  <span>상품 금액</span>
                  <strong>{selectedSubtotal.toLocaleString()}원</strong>
                </div>
                <div>
                  <span>총 할인 금액</span>
                  <strong>{TOTAL_DISCOUNT_AMOUNT.toLocaleString()}원</strong>
                </div>
                <div>
                  <span>배송비</span>
                  <strong>{selectedItems.length === 0 ? "0원" : selectedShippingFeeLabel}</strong>
                </div>
                <button
                  className="checkout-btn-main"
                  disabled={selectedItems.length === 0 || isAuthLoading}
                  type="button"
                  onClick={handleGoToCheckout}
                >
                  구매하기
                </button>
              </aside>
            </div>
          )}
        </section>
      </main>
    </>
  );
}

export default CartPage;
