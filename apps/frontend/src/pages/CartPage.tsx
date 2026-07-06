import { useEffect, useState } from "react";
import HomeHeader from "../components/HomeHeader";
import { getCart, updateCartItem } from "../lib/cartApi";
import type { CartResponse } from "../types/cart";

function CartPage() {
  const [cart, setCart] = useState<CartResponse | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [updatingItemId, setUpdatingItemId] = useState<number | null>(null);

  useEffect(() => {
    let isMounted = true;

    const loadCart = async () => {
      try {
        setIsLoading(true);
        setErrorMessage(null);

        const cartResponse = await getCart();

        if (isMounted) {
          setCart(cartResponse);
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
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : "수량 변경에 실패했습니다.");
    } finally {
      setUpdatingItemId(null);
    }
  };

  return (
    <>
      <HomeHeader />
      <main className="checkout-page">
        <section className="checkout-shell">
          <div className="checkout-title-row">
            <div>
              <h1>장바구니</h1>
              <p>담아둔 상품을 확인하고 주문서로 이동하는 화면입니다.</p>
            </div>
          </div>

          <div className="checkout-summary-card">
            {isLoading ? (
              <p>장바구니를 불러오는 중입니다.</p>
            ) : errorMessage ? (
              <p>{errorMessage}</p>
            ) : cart && cart.total_quantity === 0 ? (
              <p>장바구니가 비어 있습니다.</p>
            ) : cart ? (
              <p>장바구니를 불러왔습니다. 상품 {cart.total_quantity}개</p>
            ) : (
              <p>장바구니 정보가 없습니다.</p>
            )}
          </div>

          {cart && cart.total_quantity > 0 && (
            <>
              <div className="cart-page-list">
                {cart.items.map((item) => (
                  <article className="cart-page-item" key={item.id}>
                    <div className="cart-page-item-main">
                      <p className="cart-page-item-brand">{item.product.brand}</p>
                      <h2 className="cart-page-item-name">{item.product.name}</h2>
                    </div>

                    <div className="cart-page-item-meta">
                      <div className="cart-page-quantity-control" aria-label={`${item.product.name} 수량`}>
                        <button
                          disabled={updatingItemId === item.id || item.quantity <= 1}
                          type="button"
                          aria-label={`${item.product.name} 수량 감소`}
                          onClick={() => handleUpdateQuantity(item.id, item.quantity - 1)}
                        >
                          -
                        </button>
                        <span>{item.quantity}개</span>
                        <button
                          disabled={updatingItemId === item.id}
                          type="button"
                          aria-label={`${item.product.name} 수량 증가`}
                          onClick={() => handleUpdateQuantity(item.id, item.quantity + 1)}
                        >
                          +
                        </button>
                      </div>
                      <strong>{item.line_subtotal.toLocaleString()}원</strong>
                    </div>
                  </article>
                ))}
              </div>

              <div className="cart-page-total-card">
                <div>
                  <span>총 수량</span>
                  <strong>{cart.total_quantity}개</strong>
                </div>
                <div>
                  <span>상품 금액</span>
                  <strong>{cart.subtotal.toLocaleString()}원</strong>
                </div>
              </div>
            </>
          )}
        </section>
      </main>
    </>
  );
}

export default CartPage;
