import { useEffect, useState } from "react";
import HomeHeader from "../components/HomeHeader";
import { getCart } from "../lib/cartApi";
import type { CartResponse } from "../types/cart";

function CartPage() {
  const [cart, setCart] = useState<CartResponse | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

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
        </section>
      </main>
    </>
  );
}

export default CartPage;
