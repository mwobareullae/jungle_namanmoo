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

const getStringField = (source: unknown, keys: string[]) => {
  if (!source || typeof source !== "object") {
    return null;
  }

  const record = source as Record<string, unknown>;

  for (const key of keys) {
    const value = record[key];
    if (typeof value === "string" && value.trim()) {
      return value.trim();
    }
  }

  return null;
};

const getCartItemOptionLabel = (item: CartItem) => {
  const directOption = getStringField(item, [
    "option_label",
    "option_text",
    "selected_option",
    "variant_label",
    "variant_name",
    "option_name",
  ]);

  if (directOption) {
    return directOption;
  }

  const productOption = getStringField(item.product, [
    "option_label",
    "option_text",
    "variant_label",
    "variant_name",
  ]);

  if (productOption) {
    return productOption;
  }

  const volume = getStringField(item, ["volume_text", "capacity_text", "size_text"]) ??
    getStringField(item.product, ["volume_text", "capacity_text", "size_text"]);
  const unit = getStringField(item, ["unit_text", "packaging_text", "option_value"]);
  const parts = [volume, unit].filter(Boolean);

  return parts.length > 0 ? parts.join(" · ") : null;
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
  const selectedSubtotal = selectedItems.reduce((sum, item) => sum + item.line_subtotal, 0);
  const selectedShippingFee = selectedSubtotal <= 0
    ? 0
    : selectedSubtotal >= FREE_SHIPPING_THRESHOLD
      ? 0
      : DEFAULT_SHIPPING_FEE;
  const selectedShippingFeeLabel = selectedShippingFee === 0 ? "무료" : `${selectedShippingFee.toLocaleString()}원`;
  const selectedPaymentTotal = Math.max(0, selectedSubtotal - TOTAL_DISCOUNT_AMOUNT + selectedShippingFee);
  const expectedPointAmount = Math.round(selectedSubtotal * 0.01);
  const remainingFreeShippingAmount = Math.max(0, FREE_SHIPPING_THRESHOLD - selectedSubtotal);
  const freeShippingProgress = Math.min(100, Math.round((selectedSubtotal / FREE_SHIPPING_THRESHOLD) * 100));
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
          <CommercePageHeader currentStep="cart" title="장바구니" />

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
                    <span className="cart-skeleton cart-skeleton-thumb" />
                    <div className="cart-page-item-main">
                      <span className="cart-skeleton cart-skeleton-brand" />
                      <span className="cart-skeleton cart-skeleton-name" />
                      <span className="cart-skeleton cart-skeleton-option" />
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

          {!isLoading && !errorMessage && cart && !isAuthLoading && !user && (
            <section className="cart-page-login-banner" aria-label="비로그인 장바구니 안내">
              <div className="cart-page-login-banner-copy">
                <span className="cart-page-login-banner-icon" aria-hidden="true">
                  ✦
                </span>
                <div>
                  <h2>로그인하고 적립 혜택을 받아보세요</h2>
                  <p>구매 금액의 최대 1% 적립과 주문내역 저장을 이용할 수 있습니다.</p>
                </div>
              </div>
              <button type="button" onClick={() => navigate("/login", { state: { from: "/cart" } })}>
                로그인
              </button>
            </section>
          )}

          {!isLoading && !errorMessage && cart && !isAuthLoading && user && (
            <div className="cart-page-login-banner-spacer" aria-hidden="true" />
          )}

          {!isLoading && !errorMessage && cart && cart.total_quantity === 0 && (
            <div className="cart-page-empty-state">
              <span className="cart-page-empty-icon" aria-hidden="true">
                EMPTY
              </span>
              <h2>{user ? `${user.nickname ?? "회원"}님의 장바구니가 비어 있어요` : "장바구니가 비어 있어요"}</h2>
              <p>추천받은 뷰티 상품을 담아보세요.</p>
              <div className="cart-page-empty-actions">
                <button type="button" onClick={() => navigateWithinApp("/search")}>
                  추천 상품 보러가기
                </button>
                {!user && (
                  <button
                    className="cart-page-empty-secondary"
                    type="button"
                    onClick={() => navigate("/login", { state: { from: "/cart" } })}
                  >
                    로그인하고 이전 장바구니 복원하기
                  </button>
                )}
                {user && (
                  <button className="cart-page-empty-link" type="button">
                    최근 본 상품 보기
                  </button>
                )}
              </div>
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
                <div className="cart-page-selection-bar">
                  <label className="cart-page-select-all">
                    <input checked={allItemsSelected} onChange={handleToggleSelectAll} type="checkbox" />
                    <span>전체선택</span>
                    <em>
                      ({selectedItems.length}/{purchasableItemIds.length})
                    </em>
                  </label>
                  <div className="cart-page-selection-actions">
                    <button
                      disabled={selectedItemIds.length === 0 || isDeletingSelected}
                      onClick={handleDeleteSelected}
                      type="button"
                    >
                      선택삭제
                    </button>
                    {hasUnavailableItems && (
                      <button
                        disabled={isDeletingUnavailable}
                        onClick={handleDeleteUnavailableItems}
                        type="button"
                      >
                        구매불가 삭제
                      </button>
                    )}
                  </div>
                </div>

                <div className="cart-page-delivery-group">
                  <strong>일반배송</strong>
                  <span>30,000원 이상 무료배송</span>
                </div>

                <div className="cart-page-list">
                  {cart.items.map((item) => {
                    const imageUrl = getProductImageUrl(item.product.thumbnail_url, "w400");
                    const optionLabel = getCartItemOptionLabel(item);
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
                          {optionLabel && <p className="cart-page-item-option">{optionLabel}</p>}
                          <p className={`cart-page-stock-text${stockStatusClassName}`}>
                            {formatStockStatus(item.product.stock_status)}
                          </p>
                        </div>

                        <div className="cart-page-item-meta">
                          <button
                            className="cart-page-remove-button"
                            aria-label={`${item.product.name} 삭제`}
                            disabled={deletingItemId === item.id || updatingItemId === item.id}
                            onClick={() => handleDeleteItem(item.id)}
                            type="button"
                          >
                            ×
                          </button>
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
                        </div>
                      </article>
                    );
                  })}
                </div>
              </section>

              <aside className="cart-page-summary-card">
                <h2>결제금액</h2>
                <div>
                  <span>상품금액</span>
                  <strong>{selectedSubtotal.toLocaleString()}원</strong>
                </div>
                <div>
                  <span>상품할인금액</span>
                  <strong>{TOTAL_DISCOUNT_AMOUNT.toLocaleString()}원</strong>
                </div>
                <div>
                  <span>배송비</span>
                  <strong>{selectedItems.length === 0 ? "0원" : selectedShippingFeeLabel}</strong>
                </div>
                <div className="cart-page-summary-total">
                  <span>결제예정금액</span>
                  <strong>{selectedPaymentTotal.toLocaleString()}원</strong>
                </div>
                <p className="cart-page-point-note">
                  {selectedItems.length === 0
                    ? "구매할 상품을 선택해 주세요."
                    : user
                      ? `결제 시 ${expectedPointAmount.toLocaleString()}원 적립 예정`
                      : `로그인하면 최대 ${expectedPointAmount.toLocaleString()}원 적립`}
                </p>
                <button
                  className="checkout-btn-main"
                  disabled={selectedItems.length === 0 || isAuthLoading}
                  type="button"
                  onClick={handleGoToCheckout}
                >
                  {user ? "결제하기" : "로그인하고 결제하기"}
                </button>
                <div className="cart-page-free-shipping">
                  <span>
                    <i style={{ width: `${freeShippingProgress}%` }} />
                  </span>
                  <p>
                    {selectedItems.length === 0
                      ? "구매할 상품을 선택해 주세요."
                      : selectedShippingFee === 0
                        ? "🎉 무료배송 조건을 충족했어요."
                        : `🚚 ${remainingFreeShippingAmount.toLocaleString()}원 더 담으면 무료배송이에요.`}
                  </p>
                </div>
              </aside>
            </div>
          )}
        </section>
      </main>
    </>
  );
}

export default CartPage;
