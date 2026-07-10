import type { CSSProperties } from "react";
import { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import ProductThumbnail from "../../components/ProductThumbnail";
import { ToggleGroup, ToggleGroupTabItem } from "../../components/ui/toggle-group";
import {
  deleteMyRecentProduct,
  deleteMyWishlistItem,
  getMyRecentProducts,
  getMyWishlist,
  type ActivityProductItem
} from "../../lib/activityApi";
import { MyPageLayout, type MypageEventContext } from "./MyPageShell";

type ProductListMode = "wishlist" | "recent";
type WishlistSort = "all" | "skin" | "recent";

export type MypageProductListItem = {
  id: string;
  productId: string;
  brand: string;
  name: string;
  price: number;
  originalPrice?: number;
  discountRate?: number;
  deliveryLabel?: string;
  thumbnailUrl: string | null;
  dateLabel?: string;
  addedAt?: string;
  tags?: string[];
  isWished?: boolean;
  eventContext?: MypageEventContext;
};

type ProductListProps = {
  items?: MypageProductListItem[];
  mode?: ProductListMode;
  onOpenProduct?: (item: MypageProductListItem) => void;
  onRemoveItem?: (item: MypageProductListItem) => void;
  onSortChange?: (sort: WishlistSort) => void;
};

const recommendedItems: MypageProductListItem[] = [
  {
    id: "wish-1",
    productId: "prod_wish_1",
    brand: "라운드랩",
    name: "1025 독도 토너 500ml",
    price: 19800,
    originalPrice: 30000,
    discountRate: 34,
    deliveryLabel: "무료배송",
    thumbnailUrl: null,
    tags: ["수분", "저자극"],
    isWished: true,
    eventContext: { page: "mypage_wishlist", source: "wishlist", sectionId: "wishlist_list", productId: "prod_wish_1", rank: 1 }
  },
  {
    id: "wish-2",
    productId: "prod_wish_2",
    brand: "아누아",
    name: "어성초 77 수딩 토너",
    price: 21900,
    originalPrice: 29000,
    discountRate: 24,
    deliveryLabel: "3,000원",
    thumbnailUrl: null,
    tags: ["진정", "피부결"],
    isWished: true,
    eventContext: { page: "mypage_wishlist", source: "wishlist", sectionId: "wishlist_list", productId: "prod_wish_2", rank: 2 }
  },
  {
    id: "wish-3",
    productId: "prod_wish_3",
    brand: "닥터지",
    name: "레드 블레미쉬 클리어 수딩 크림",
    price: 24000,
    originalPrice: 32000,
    discountRate: 25,
    deliveryLabel: "무료배송",
    thumbnailUrl: null,
    tags: ["장벽", "민감"],
    isWished: true,
    eventContext: { page: "mypage_wishlist", source: "wishlist", sectionId: "wishlist_list", productId: "prod_wish_3", rank: 3 }
  }
];

const sortTabs: { id: WishlistSort; label: string }[] = [
  { id: "all", label: "전체" },
  { id: "skin", label: "피부 맞춤" },
  { id: "recent", label: "최근순" }
];

const formatPrice = (price: number) => `${price.toLocaleString("ko-KR")}원`;

const mapActivityItem = (
  item: ActivityProductItem,
  mode: ProductListMode,
  index: number
): MypageProductListItem => ({
  id: item.id,
  productId: item.productId,
  brand: item.brand,
  name: item.name,
  price: item.price,
  thumbnailUrl: item.thumbnailUrl,
  dateLabel: item.dateLabel,
  addedAt: item.rawDate,
  tags: item.tags,
  isWished: item.isWished,
  eventContext: {
    page: mode === "wishlist" ? "mypage_wishlist" : "mypage_recent",
    source: mode === "wishlist" ? "wishlist" : "recent_products",
    sectionId: mode === "wishlist" ? "wishlist_list" : "recent_list",
    productId: item.productId,
    rank: index + 1
  }
});

const getTodayDateLabel = () => {
  const parts = new Intl.DateTimeFormat("ko-KR", {
    timeZone: "Asia/Seoul",
    year: "numeric",
    month: "2-digit",
    day: "2-digit"
  }).formatToParts(new Date());
  const year = parts.find((part) => part.type === "year")?.value ?? "";
  const month = parts.find((part) => part.type === "month")?.value ?? "";
  const day = parts.find((part) => part.type === "day")?.value ?? "";

  return `${year}.${month}.${day}.`;
};

export default function WishList(props: Omit<ProductListProps, "mode">) {
  return <MypageProductList mode="wishlist" {...props} />;
}

export function RecentProducts(props: Omit<ProductListProps, "mode">) {
  return <MypageProductList mode="recent" {...props} />;
}

function MypageProductList({
  items,
  mode = "wishlist",
  onOpenProduct,
  onRemoveItem,
  onSortChange
}: ProductListProps) {
  const navigate = useNavigate();
  const [sort, setSort] = useState<WishlistSort>("all");
  const isRecent = mode === "recent";
  const [listItems, setListItems] = useState<MypageProductListItem[]>(() =>
    items ?? []
  );
  const [isLoading, setIsLoading] = useState(!items);
  const [loadError, setLoadError] = useState<string | null>(null);
  const title = isRecent ? "최근 본 상품" : "찜한 상품";
  const activePath: "/mypage/recent" | "/mypage/wishlist" = isRecent ? "/mypage/recent" : "/mypage/wishlist";
  const guideText = isRecent ? "최근 2주간 최대 50개까지 유지" : "최근 1년간 찜한 내역 유지";
  const emptyTitle = isRecent ? "최근 본 상품이 없어요" : "아직 찜한 상품이 없어요";
  const emptyDescription = isRecent ? "상품을 둘러보면 최근 본 상품이 여기에 모여요." : "피부 타입에 맞는 제품을 찾아 찜해보세요.";
  const todayDateLabel = getTodayDateLabel();
  const displayItems = useMemo(() => {
    if (sort === "skin") {
      return [...listItems].sort((a, b) => (b.tags?.length ?? 0) - (a.tags?.length ?? 0));
    }

    if (sort === "recent") {
      return [...listItems].sort((a, b) => {
        const aTime = a.addedAt ? new Date(a.addedAt).getTime() : 0;
        const bTime = b.addedAt ? new Date(b.addedAt).getTime() : 0;
        return bTime - aTime;
      });
    }

    return listItems;
  }, [listItems, sort]);

  useEffect(() => {
    if (items) {
      const timerId = window.setTimeout(() => {
        setListItems(items);
        setIsLoading(false);
        setLoadError(null);
      }, 0);
      return () => window.clearTimeout(timerId);
    }

    let isMounted = true;
    const loadingTimerId = window.setTimeout(() => {
      if (isMounted) {
        setIsLoading(true);
        setLoadError(null);
      }
    }, 0);

    const request = mode === "wishlist" ? getMyWishlist() : getMyRecentProducts();
    request
      .then((activityItems) => {
        if (!isMounted) {
          return;
        }

        setListItems(activityItems.map((item, index) => mapActivityItem(item, mode, index)));
      })
      .catch(() => {
        if (!isMounted) {
          return;
        }

        setListItems([]);
        setLoadError(`${title}을 불러오지 못했습니다. 잠시 후 다시 시도해주세요.`);
      })
      .finally(() => {
        if (isMounted) {
          setIsLoading(false);
        }
      });

    return () => {
      isMounted = false;
      window.clearTimeout(loadingTimerId);
    };
  }, [items, mode, title]);

  const updateSort = (nextSort: WishlistSort) => {
    setSort(nextSort);
    onSortChange?.(nextSort);
  };

  const removeItem = async (item: MypageProductListItem) => {
    const previousItems = listItems;
    setListItems((prev) => prev.filter((candidate) => candidate.id !== item.id));

    try {
      if (isRecent) {
        await deleteMyRecentProduct(item.productId);
      } else {
        await deleteMyWishlistItem(item.productId);
      }
      onRemoveItem?.(item);
    } catch {
      setListItems(previousItems);
      setLoadError("삭제에 실패했습니다. 잠시 후 다시 시도해주세요.");
    }
  };

  const openProduct = (item: MypageProductListItem) => {
    onOpenProduct?.(item);
  };

  if (isLoading || (!loadError && displayItems.length === 0)) {
    return (
      <MyPageLayout activePath={activePath}>
        <style>{`
          .mypage-product-list-thumbnail {
            display: block;
            width: 100%;
            height: 100%;
            object-fit: cover;
          }
          .mypage-product-list-thumbnail.product-image-fallback {
            width: 100%;
            height: 100%;
            margin: 0;
            object-fit: cover;
          }
        `}</style>
        <header style={styles.singleTitleRow}>
          <h1 style={styles.singleTitle}>{title}</h1>
        </header>
        <section style={styles.emptyWishlistPanel} aria-label={`${title} 빈 상태`}>
          <div style={styles.emptyIconCircle} aria-hidden="true">
            <svg width="34" height="34" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8">
              {isRecent ? (
                <>
                  <circle cx="12" cy="12" r="9" />
                  <path d="M12 7v5l3 2" />
                </>
              ) : (
                <path d="M20.84 4.61a5.5 5.5 0 0 0-7.78 0L12 5.67l-1.06-1.06a5.5 5.5 0 0 0-7.78 7.78L12 21.23l8.84-8.84a5.5 5.5 0 0 0 0-7.78Z" />
              )}
            </svg>
          </div>
          {isLoading ? (
            <div style={styles.emptyLoadingSpacer} aria-label={`${title} 불러오는 중`} />
          ) : (
            <>
              <h2 style={styles.emptyTitle}>{emptyTitle}</h2>
              <p style={styles.emptyDescription}>{emptyDescription}</p>
              <button
                className="inline-flex min-h-[54px] min-w-[196px] items-center justify-center rounded-[10px] bg-[#0C1117] px-[26px] text-[15px] font-extrabold text-white hover:bg-[#1A1A1A]"
                onClick={() => navigate("/")}
                type="button"
              >
                상품 둘러보러 가기
              </button>
            </>
          )}
        </section>
        {!isLoading ? (
          <section style={styles.recommendSection} aria-label="추천 상품">
            <h2 style={styles.recommendTitle}>이런 상품은 어때요?</h2>
            <div style={styles.recommendGrid}>
              {recommendedItems.slice(0, 4).map((item) => (
                <RecommendedProductCard item={item} key={item.id} onOpenProduct={openProduct} />
              ))}
            </div>
          </section>
        ) : null}
      </MyPageLayout>
    );
  }

  return (
    <MyPageLayout activePath={activePath}>
      <style>{`
        .mypage-product-list-thumbnail {
          display: block;
          width: 100%;
          height: 100%;
          object-fit: cover;
        }
        .mypage-product-list-thumbnail.product-image-fallback {
          width: 100%;
          height: 100%;
          margin: 0;
          object-fit: cover;
        }
      `}</style>
      <header style={styles.singleTitleRow}>
        <h1 style={styles.singleTitle}>{title}</h1>
      </header>

      {!isRecent ? (
        <ToggleGroup
          aria-label="찜한 상품 필터"
          className="flex flex-wrap gap-[34px] border-b border-[#e6e6e6]"
          onValueChange={(value) => {
            if (value) {
              updateSort(value as WishlistSort);
            }
          }}
          type="single"
          value={sort}
        >
          {sortTabs.map((tab) => (
            <ToggleGroupTabItem key={tab.id} value={tab.id}>
              {tab.label}
            </ToggleGroupTabItem>
          ))}
        </ToggleGroup>
      ) : null}

      {isRecent ? (
        <div style={styles.countRow}>
          <strong>최근 본 상품 <span style={styles.countNumber}>{displayItems.length}</span></strong>
        </div>
      ) : null}

      {loadError ? <p style={styles.statusMessage}>{loadError}</p> : null}
      {isLoading ? (
        <div style={styles.emptyWrap}>
          <p style={styles.emptyDescription}>{title}을 불러오는 중입니다.</p>
        </div>
      ) : displayItems.length === 0 ? (
        <div style={styles.emptyWrap}>
          <h2 style={styles.emptyTitle}>{emptyTitle}</h2>
          <p style={styles.emptyDescription}>{emptyDescription}</p>
          <button
            className="inline-flex min-h-[54px] min-w-[196px] items-center justify-center rounded-[10px] bg-[#0C1117] px-[26px] text-[15px] font-extrabold text-white hover:bg-[#1A1A1A]"
            onClick={() => navigate("/")}
            type="button"
          >
            상품 둘러보기
          </button>
        </div>
      ) : (
        <section style={styles.list} aria-label={`${title} 목록`}>
          {displayItems.map((item, index) => {
            const shouldShowDate = isRecent && item.dateLabel && item.dateLabel !== displayItems[index - 1]?.dateLabel;
            const isTodayDivider = item.dateLabel === todayDateLabel;

            return (
              <div key={item.id}>
                {shouldShowDate ? (
                  <div style={isTodayDivider ? styles.dateDividerToday : styles.dateDivider}>{item.dateLabel}</div>
                ) : null}
                <article style={styles.row}>
                  <button
                    className="bg-transparent hover:bg-[#FAFAFA]"
                    onClick={() => openProduct(item)}
                    style={styles.rowButton}
                    type="button"
                  >
                    <div style={styles.imageWrap}>
                      <ProductThumbnail
                        src={item.thumbnailUrl}
                        alt={`${item.brand} ${item.name}`}
                        className="mypage-product-list-thumbnail"
                      />
                      <span style={item.isWished ? styles.heartBadgeActive : styles.heartBadge} aria-hidden="true">♥</span>
                    </div>
                    <span style={styles.body}>
                      <strong style={styles.name}>{item.name}</strong>
                      <span style={styles.priceLine}>
                        {item.discountRate ? <span style={styles.discount}>{item.discountRate}%</span> : null}
                        <strong style={styles.price}>{formatPrice(item.price)}</strong>
                      </span>
                      {item.originalPrice ? <span style={styles.originalPrice}>{formatPrice(item.originalPrice)}</span> : null}
                      {item.deliveryLabel ? <span style={styles.delivery}>배송비 {item.deliveryLabel}</span> : null}
                      <span style={styles.brand}>{item.brand}</span>
                      {item.tags?.length ? (
                        <span style={styles.tags}>
                          {item.tags.slice(0, 3).map((tag) => (
                            <span key={tag} style={styles.tag}>{tag}</span>
                          ))}
                        </span>
                      ) : null}
                    </span>
                  </button>
                  <button
                    aria-label={`${item.name} 목록에서 제거`}
                    className="text-[#c8cdd2] hover:text-[#4b5563]"
                    onClick={() => removeItem(item)}
                    style={styles.removeButton}
                    type="button"
                  >
                    ×
                  </button>
                </article>
              </div>
            );
          })}
        </section>
      )}
      <p style={styles.guideText}>{guideText}</p>
    </MyPageLayout>
  );
}

function RecommendedProductCard({
  item,
  onOpenProduct
}: {
  item: MypageProductListItem;
  onOpenProduct?: (item: MypageProductListItem) => void;
}) {
  return (
    <article
      className="border border-[#e0e0e0] transition-colors hover:border-[#94E0F8]"
      style={styles.recommendCard}
    >
      <button onClick={() => onOpenProduct?.(item)} style={styles.recommendCardButton} type="button">
        <div style={styles.recommendImageWrap}>
          <ProductThumbnail
            src={item.thumbnailUrl}
            alt={`${item.brand} ${item.name}`}
            className="mypage-product-list-thumbnail"
          />
          <span style={styles.recommendHeart} aria-hidden="true">♡</span>
        </div>
        <span style={styles.recommendBody}>
          <span style={styles.recommendBrand}>{item.brand}</span>
          <strong style={styles.recommendName}>{item.name}</strong>
          {item.tags?.length ? (
            <span style={styles.tags}>
              {item.tags.slice(0, 3).map((tag) => (
                <span key={tag} style={styles.tag}>{tag}</span>
              ))}
            </span>
          ) : null}
          <strong style={styles.recommendPrice}>{formatPrice(item.price)}</strong>
        </span>
      </button>
    </article>
  );
}

const styles: Record<string, CSSProperties> = {
  singleTitleRow: {
    paddingBottom: 14,
    marginBottom: 32,
    borderBottom: "2px solid #222222"
  },
  singleTitle: {
    margin: 0,
    color: "#222222",
    fontFamily: "'GmarketSans', sans-serif",
    fontSize: 24,
    fontWeight: 500
  },
  guideText: {
    margin: "18px 0 0",
    color: "#9ca3af",
    fontSize: 13,
    fontWeight: 600
  },
  countRow: {
    padding: "17px 0",
    borderBottom: "1px solid #eef0f2",
    color: "#222222",
    fontSize: 14,
    fontWeight: 700
  },
  countNumber: {
    color: "#2aa6d1"
  },
  statusMessage: {
    margin: "0 0 18px",
    padding: "12px 14px",
    borderRadius: 8,
    background: "rgba(148,224,248,0.12)",
    color: "#4b5563",
    fontSize: 13,
    fontWeight: 600
  },
  list: {
    display: "grid"
  },
  dateDivider: {
    padding: "6px 16px",
    background: "#f4f6f8",
    color: "#555555",
    fontSize: 14,
    fontWeight: 800
  },
  dateDividerToday: {
    padding: "6px 16px",
    background: "rgba(148,224,248,0.14)",
    color: "#2aa6d1",
    fontSize: 14,
    fontWeight: 800
  },
  row: {
    position: "relative",
    minHeight: 136,
    borderBottom: "1px solid #eef0f2",
    background: "#ffffff"
  },
  rowButton: {
    display: "grid",
    gridTemplateColumns: "92px minmax(0, 1fr)",
    gap: 16,
    width: "100%",
    minHeight: 136,
    padding: "18px 44px 18px 0",
    border: 0,
    color: "inherit",
    fontFamily: "inherit",
    textAlign: "left",
    cursor: "pointer"
  },
  imageWrap: {
    position: "relative",
    width: 92,
    height: 92,
    overflow: "hidden",
    borderRadius: 6,
    border: "1px solid #edf0f2",
    background: "#f4f9f9"
  },
  body: {
    display: "grid",
    alignContent: "start",
    gap: 5,
    minWidth: 0
  },
  name: {
    color: "#111111",
    fontSize: 15,
    fontWeight: 700,
    lineHeight: 1.35
  },
  priceLine: {
    display: "flex",
    alignItems: "baseline",
    gap: 5
  },
  discount: {
    color: "#e4003a",
    fontSize: 17,
    fontWeight: 800
  },
  price: {
    color: "#111111",
    fontSize: 18,
    fontWeight: 800
  },
  originalPrice: {
    color: "#9ca3af",
    fontSize: 13,
    fontWeight: 500,
    textDecoration: "line-through"
  },
  delivery: {
    color: "#8b929b",
    fontSize: 12,
    fontWeight: 600
  },
  brand: {
    color: "#7d858f",
    fontSize: 12,
    fontWeight: 600
  },
  tags: {
    display: "flex",
    flexWrap: "wrap",
    gap: 5,
    marginTop: 2
  },
  tag: {
    display: "inline-flex",
    alignItems: "center",
    minHeight: 20,
    padding: "0 7px",
    borderRadius: 999,
    border: "1px solid rgba(148,224,248,0.65)",
    background: "rgba(148,224,248,0.12)",
    color: "#2aa6d1",
    fontSize: 10,
    fontWeight: 600
  },
  heartBadge: {
    position: "absolute",
    right: 7,
    bottom: 7,
    display: "grid",
    placeItems: "center",
    width: 22,
    height: 22,
    borderRadius: "50%",
    background: "rgba(0,0,0,0.26)",
    color: "#ffffff",
    fontSize: 12
  },
  heartBadgeActive: {
    position: "absolute",
    right: 7,
    bottom: 7,
    display: "grid",
    placeItems: "center",
    width: 22,
    height: 22,
    borderRadius: "50%",
    background: "#94e0f8",
    color: "#ffffff",
    fontSize: 12
  },
  removeButton: {
    position: "absolute",
    top: 24,
    right: 4,
    width: 32,
    height: 32,
    border: 0,
    background: "transparent",
    fontFamily: "inherit",
    fontSize: 28,
    fontWeight: 300,
    lineHeight: 1,
    cursor: "pointer"
  },
  emptyWrap: {
    display: "grid",
    alignItems: "center",
    justifyContent: "center",
    minHeight: 280,
    padding: 40,
    textAlign: "center"
  },
  emptyWishlistPanel: {
    display: "grid",
    justifyItems: "center",
    padding: "52px 0 60px",
    borderBottom: "1px solid #e0e0e0",
    textAlign: "center"
  },
  emptyIconCircle: {
    display: "grid",
    placeItems: "center",
    width: 72,
    height: 72,
    marginBottom: 22,
    borderRadius: "50%",
    border: "1px solid rgba(148,224,248,0.55)",
    background: "rgba(148,224,248,0.10)",
    color: "#76ccea"
  },
  emptyLoadingSpacer: {
    minHeight: 120
  },
  emptyTitle: {
    margin: 0,
    color: "#222222",
    fontFamily: "'GmarketSans', sans-serif",
    fontSize: 25,
    fontWeight: 500,
    lineHeight: 1.35
  },
  emptyDescription: {
    margin: "16px 0 28px",
    color: "#777777",
    fontSize: 15,
    fontWeight: 500
  },
  recommendSection: {
    paddingTop: 38
  },
  recommendTitle: {
    margin: "0 0 24px",
    color: "#222222",
    fontSize: 18,
    fontWeight: 800
  },
  recommendGrid: {
    display: "grid",
    gridTemplateColumns: "repeat(3, minmax(0, 1fr))",
    gap: 18
  },
  recommendCard: {
    overflow: "hidden",
    borderRadius: 8,
    background: "#ffffff"
  },
  recommendCardButton: {
    display: "block",
    width: "100%",
    padding: 0,
    border: 0,
    background: "transparent",
    color: "inherit",
    fontFamily: "inherit",
    textAlign: "left",
    cursor: "pointer"
  },
  recommendImageWrap: {
    position: "relative",
    aspectRatio: "1.42 / 1",
    overflow: "hidden",
    background: "#f4f9f9"
  },
  recommendHeart: {
    position: "absolute",
    top: 12,
    right: 12,
    display: "grid",
    placeItems: "center",
    width: 36,
    height: 36,
    borderRadius: "50%",
    background: "rgba(255,255,255,0.92)",
    color: "#777777",
    fontSize: 24,
    lineHeight: 1
  },
  recommendBody: {
    display: "grid",
    gap: 9,
    padding: "18px 20px 20px"
  },
  recommendBrand: {
    color: "#888888",
    fontSize: 13,
    fontWeight: 600
  },
  recommendName: {
    minHeight: 44,
    color: "#222222",
    fontSize: 15,
    fontWeight: 500,
    lineHeight: 1.45
  },
  recommendPrice: {
    color: "#063445",
    fontSize: 18,
    fontWeight: 800
  }
};
