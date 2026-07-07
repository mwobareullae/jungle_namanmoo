from __future__ import annotations

import math


POPULARITY_SCORE_VERSION = "behavior_popularity_v1"


def calculate_product_popularity_score(
    *,
    view_count: int = 0,
    wishlist_add_count: int = 0,
    cart_add_count: int = 0,
    checkout_start_count: int = 0,
    paid_order_count: int = 0,
    home_product_impression_count: int = 0,
    home_product_click_count: int = 0,
    search_result_impression_count: int = 0,
    search_result_click_count: int = 0,
) -> float:
    view_count = _non_negative(view_count)
    wishlist_add_count = _non_negative(wishlist_add_count)
    cart_add_count = _non_negative(cart_add_count)
    checkout_start_count = _non_negative(checkout_start_count)
    paid_order_count = _non_negative(paid_order_count)
    home_product_impression_count = _non_negative(home_product_impression_count)
    home_product_click_count = _non_negative(home_product_click_count)
    search_result_impression_count = _non_negative(search_result_impression_count)
    search_result_click_count = _non_negative(search_result_click_count)

    return (
        math.log1p(view_count) * 1.0
        + math.log1p(wishlist_add_count) * 2.5
        + math.log1p(cart_add_count) * 4.0
        + math.log1p(checkout_start_count) * 6.0
        + math.log1p(paid_order_count) * 10.0
        + _capped_rate(cart_add_count + 0.9, view_count + 30) * 30.0
        + _capped_rate(paid_order_count + 0.15, view_count + 30) * 60.0
        + _capped_rate(home_product_click_count + 1, home_product_impression_count + 50) * 20.0
        + _capped_rate(search_result_click_count + 1, search_result_impression_count + 50) * 15.0
    )


def _non_negative(value: int) -> int:
    return max(int(value or 0), 0)


def _capped_rate(numerator: float, denominator: float) -> float:
    if denominator <= 0:
        return 0.0
    return min(max(numerator / denominator, 0.0), 1.0)
