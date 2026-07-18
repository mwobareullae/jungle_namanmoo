import type { CSSProperties } from "react";
import { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import ProductThumbnail from "../../components/ProductThumbnail";
import ProductSoldOutOverlay from "../../components/ProductSoldOutOverlay";
import LoginRequiredDialog from "../../components/LoginRequiredDialog";
import Skeleton from "../../components/ui/Skeleton";
import HeartIcon from "../../components/ui/HeartIcon";
import ActivityToast from "../../components/ui/ActivityToast";
import { ToggleGroup, ToggleGroupTabItem } from "../../components/ui/toggle-group";
import { useAuth } from "../../contexts/useAuth";
import {
  addMyWishlistItem,
  deleteMyRecentProduct,
  deleteMyWishlistItem,
  getMyRecentProducts,
  getMyWishlist,
  type ActivityProductItem
} from "../../lib/activityApi";
import { MyPageLayout, type MypageEventContext } from "./MyPageShell";
import { useActivityToast, wishlistToastMessage } from "../../hooks/useActivityToast";
import { api } from "../../lib/api";
import { isProductSoldOut } from "../../lib/productAvailability";
import type { HomeSectionProduct } from "../../types/recommendation";

type ProductListMode = "wishlist" | "recent";
type WishlistSort = "recent";

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
  salesStatus?: string;
  stockStatus?: string;
  availableQuantity?: number | null;
  inStock?: boolean;
  eventContext?: MypageEventContext;
};

type ProductListProps = {
  items?: MypageProductListItem[];
  mode?: ProductListMode;
  onOpenProduct?: (item: MypageProductListItem) => void;
  onRemoveItem?: (item: MypageProductListItem) => void;
  onSortChange?: (sort: WishlistSort) => void;
};

const sortTabs: { id: WishlistSort; label: string }[] = [
  { id: "recent", label: "최근순" }
];

const PAGE_SIZE = 10;

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
  salesStatus: item.salesStatus,
  stockStatus: item.stockStatus,
  availableQuantity: item.availableQuantity,
  inStock: item.inStock,
  eventContext: {
    page: mode === "wishlist" ? "mypage_wishlist" : "mypage_recent",
    source: mode === "wishlist" ? "wishlist" : "recent_products",
    sectionId: mode === "wishlist" ? "wishlist_list" : "recent_list",
    productId: item.productId,
    rank: index + 1
  }
});

const mapRecommendedItem = (item: HomeSectionProduct, index: number): MypageProductListItem => ({
  id: `recommendation-${item.product_id}`,
  productId: item.product_id,
  brand: item.brand,
  name: item.name,
  price: item.lowest_price ?? 0,
  originalPrice: item.original_price ?? undefined,
  discountRate: item.discount_rate ?? undefined,
  deliveryLabel: "무료배송",
  thumbnailUrl: item.thumbnail_url,
  tags: item.tags,
  isWished: false,
  salesStatus: item.sales_status,
  stockStatus: item.stock_status,
  availableQuantity: item.available_quantity,
  inStock: item.in_stock,
  eventContext: {
    page: "mypage_wishlist",
    source: "personalized_recommendation",
    sectionId: "mypage_personalized_recommendations",
    productId: item.product_id,
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
  const { user } = useAuth();
  const [sort, setSort] = useState<WishlistSort>("recent");
  const isRecent = mode === "recent";
  const [listItems, setListItems] = useState<MypageProductListItem[]>(() =>
    items ?? []
  );
  const [isLoading, setIsLoading] = useState(!items);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [pendingWishlistProductIds, setPendingWishlistProductIds] = useState<Set<string>>(() => new Set());
  const [isLoginDialogOpen, setIsLoginDialogOpen] = useState(false);
  const [recommendedItems, setRecommendedItems] = useState<MypageProductListItem[]>([]);
  const { message: toastMessage, showToast } = useActivityToast();
  const [pageState, setPageState] = useState<{ mode: ProductListMode; currentPage: number }>(() => ({
    mode,
    currentPage: 1
  }));
  const title = isRecent ? "최근 본 상품" : "찜한 상품";
  const activePath: "/mypage/recent" | "/mypage/wishlist" = isRecent ? "/mypage/recent" : "/mypage/wishlist";
  const guideText = isRecent ? "최근 한 달간 최대 50개까지 유지" : "최근 1년간 찜한 내역 유지";
  const emptyTitle = isRecent ? "최근 본 상품이 없어요" : "아직 찜한 상품이 없어요";
  const emptyDescription = isRecent ? "상품을 둘러보면 최근 본 상품이 여기에 모여요." : "피부 타입에 맞는 제품을 찾아 찜해보세요.";
  const todayDateLabel = getTodayDateLabel();

  useEffect(() => {
    let isMounted = true;
    void api.getForYou({ limit: 3 })
      .then(async (section) => {
        let wishedProductIds = new Set<string>();
        try {
          const wishlistItems = await getMyWishlist(50, user?.id);
          wishedProductIds = new Set(wishlistItems.map((item) => item.productId));
        } catch {
          // 추천 상품은 찜 상태 조회가 실패해도 계속 노출한다.
        }
        if (isMounted) {
          setRecommendedItems(section.products.map((item, index) => ({
            ...mapRecommendedItem(item, index),
            isWished: wishedProductIds.has(item.product_id)
          })));
        }
      })
      .catch(() => {
        if (isMounted) setRecommendedItems([]);
      });
    return () => {
      isMounted = false;
    };
  }, [user?.id]);
  const displayItems = useMemo(() => {
    return [...listItems].sort((a, b) => {
      const aTime = a.addedAt ? new Date(a.addedAt).getTime() : 0;
      const bTime = b.addedAt ? new Date(b.addedAt).getTime() : 0;
      return bTime - aTime;
    });
  }, [listItems]);
  const totalPages = Math.max(1, Math.ceil(displayItems.length / PAGE_SIZE));
  const currentPage = pageState.mode === mode ? Math.min(pageState.currentPage, totalPages) : 1;
  const pageStartIndex = (currentPage - 1) * PAGE_SIZE;
  const paginatedItems = useMemo(
    () => displayItems.slice(pageStartIndex, pageStartIndex + PAGE_SIZE),
    [displayItems, pageStartIndex]
  );

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
    const loadingStartedAt = Date.now();
    const minimumLoadingDuration = 600;
    const loadingTimerId = window.setTimeout(() => {
      if (isMounted) {
        setIsLoading(true);
        setLoadError(null);
      }
    }, 0);

    const request = mode === "wishlist"
      ? getMyWishlist(50, user?.id).then((wishlistItems) => wishlistItems)
      : Promise.all([getMyRecentProducts(), getMyWishlist(50, user?.id)]).then(([recentItems, wishlistItems]) => {
          const wishedProductIds = new Set(wishlistItems.map((item) => item.productId));
          return recentItems.map((item) => ({ ...item, isWished: wishedProductIds.has(item.productId) }));
        });
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
        setLoadError(null);
      })
      .finally(() => {
        const remainingDuration = Math.max(0, minimumLoadingDuration - (Date.now() - loadingStartedAt));
        window.setTimeout(() => {
          if (isMounted) setIsLoading(false);
        }, remainingDuration);
      });

    return () => {
      isMounted = false;
      window.clearTimeout(loadingTimerId);
    };
  }, [isRecent, items, mode, title, user?.id]);

  const updateSort = (nextSort: WishlistSort) => {
    setSort(nextSort);
    setPageState({ mode, currentPage: 1 });
    onSortChange?.(nextSort);
  };

  const changePage = (nextPage: number) => {
    setPageState({ mode, currentPage: Math.min(Math.max(nextPage, 1), totalPages) });
  };

  const removeItem = async (item: MypageProductListItem) => {
    const previousItems = listItems;
    setListItems((prev) => prev.filter((candidate) => candidate.id !== item.id));

    try {
      if (isRecent) {
        await deleteMyRecentProduct(item.productId);
      } else {
        await deleteMyWishlistItem(item.productId, user?.id);
      }
      onRemoveItem?.(item);
    } catch {
      setListItems(previousItems);
      setLoadError("삭제에 실패했습니다. 잠시 후 다시 시도해주세요.");
    }
  };

  const toggleWishlist = async (item: MypageProductListItem) => {
    if (!user) {
      setIsLoginDialogOpen(true);
      return;
    }

    if (pendingWishlistProductIds.has(item.productId)) return;

    const previousItems = listItems;
    const previousRecommendedItems = recommendedItems;
    setPendingWishlistProductIds((previous) => new Set(previous).add(item.productId));
    setListItems((previous) => previous.map((candidate) => (
      candidate.productId === item.productId ? { ...candidate, isWished: !candidate.isWished } : candidate
    )));
    setRecommendedItems((previous) => previous.map((candidate) => (
      candidate.productId === item.productId ? { ...candidate, isWished: !candidate.isWished } : candidate
    )));

    try {
      if (item.isWished) {
        await deleteMyWishlistItem(item.productId, user.id);
        showToast(wishlistToastMessage.removed);
      } else {
        const addedItem = await addMyWishlistItem(item.productId, user.id);
        if (!isRecent) {
          setListItems((previous) => (
            previous.some((candidate) => candidate.productId === addedItem.productId)
              ? previous
              : [mapActivityItem(addedItem, mode, 0), ...previous]
          ));
        }
        showToast(wishlistToastMessage.added);
      }
    } catch {
      setListItems(previousItems);
      setRecommendedItems(previousRecommendedItems);
      setLoadError("찜 상태를 변경하지 못했습니다. 잠시 후 다시 시도해주세요.");
      showToast(wishlistToastMessage.failed);
    } finally {
      setPendingWishlistProductIds((previous) => {
        const next = new Set(previous);
        next.delete(item.productId);
        return next;
      });
    }
  };

  const openProduct = (item: MypageProductListItem) => {
    if (onOpenProduct) {
      onOpenProduct(item);
      return;
    }

    navigate(`/product-detail?id=${encodeURIComponent(item.productId)}`);
  };

  if (!isLoading && (!loadError && displayItems.length === 0)) {
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
          {!isLoading ? <div style={styles.emptyIconCircle} aria-hidden="true">
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
          </div> : null}
          {isLoading ? (
            <div style={styles.loadingList} aria-label={`${title} 불러오는 중`}>
              {Array.from({ length: 5 }, (_, index) => (
                <div aria-hidden="true" key={index} style={styles.loadingRow}>
                  <span style={styles.loadingImage} />
                  <span style={styles.loadingBody}>
                    <span style={styles.loadingLineWide} />
                    <span style={styles.loadingLineMedium} />
                    <span style={styles.loadingLineShort} />
                    <span style={styles.loadingLineShort} />
                  </span>
                </div>
              ))}
            </div>
          ) : (
            <>
              <h2 style={styles.emptyTitle}>{emptyTitle}</h2>
              <p style={styles.emptyDescription}>{emptyDescription}</p>
              <button
                className="inline-flex min-h-[54px] min-w-[196px] items-center justify-center rounded-[10px] bg-[#0C1117] px-[26px] text-[15px] font-semibold text-white hover:bg-[#1A1A1A]"
                onClick={() => navigate("/products/popular")}
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
              {recommendedItems.slice(0, 3).map((item) => (
                <RecommendedProductCard
                  item={item}
                  key={item.id}
                  onOpenProduct={openProduct}
                  onToggleWishlist={toggleWishlist}
                  wishlistPending={pendingWishlistProductIds.has(item.productId)}
                />
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

      <p style={styles.guideText}>{guideText}</p>

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

      {loadError ? <p style={styles.statusMessage}>{loadError}</p> : null}
      {isLoading ? (
        <section style={styles.loadingList} aria-label={`${title} 불러오는 중`}>
          {isRecent ? <Skeleton className="mypage-loading-date" style={styles.loadingDateBlock} /> : null}
          {Array.from({ length: 5 }, (_, index) => (
            <div aria-hidden="true" key={index} style={styles.loadingRow}>
              <Skeleton className="mypage-loading-image" style={styles.loadingImage} />
              <span style={styles.loadingBody}>
                <Skeleton className="mypage-loading-line" style={styles.loadingLineWide} />
                <Skeleton className="mypage-loading-line" style={styles.loadingLineMedium} />
                <Skeleton className="mypage-loading-line" style={styles.loadingLineShort} />
              </span>
            </div>
          ))}
        </section>
      ) : displayItems.length === 0 ? (
        <div style={styles.emptyWrap}>
          <h2 style={styles.emptyTitle}>{emptyTitle}</h2>
          <p style={styles.emptyDescription}>{emptyDescription}</p>
          <button
            className="inline-flex min-h-[54px] min-w-[196px] items-center justify-center rounded-[10px] bg-[#0C1117] px-[26px] text-[15px] font-semibold text-white hover:bg-[#1A1A1A]"
            onClick={() => navigate("/")}
            type="button"
          >
            상품 둘러보기
          </button>
        </div>
      ) : (
        <section style={styles.list} aria-label={`${title} 목록`}>
          {paginatedItems.map((item, index) => {
            const previousItem = index === 0 ? null : paginatedItems[index - 1];
            const shouldShowDate = isRecent && item.dateLabel && item.dateLabel !== previousItem?.dateLabel;
            const isTodayDivider = item.dateLabel === todayDateLabel;
            const isSoldOut = isProductSoldOut({
              sales_status: item.salesStatus,
              stock_status: item.stockStatus,
              available_quantity: item.availableQuantity,
              in_stock: item.inStock
            });

            return (
              <div key={item.id}>
                {shouldShowDate ? (
                  <div style={isTodayDivider ? styles.dateDividerToday : styles.dateDivider}>{item.dateLabel}</div>
                ) : null}
                <article data-agent-product-id={item.productId} style={styles.row}>
                  <div
                    className="mypage-product-list-row-button bg-transparent"
                    onClick={() => openProduct(item)}
                    onKeyDown={(event) => {
                      if (event.key === "Enter" || event.key === " ") {
                        event.preventDefault();
                        openProduct(item);
                      }
                    }}
                    role="button"
                    style={styles.rowButton}
                    tabIndex={0}
                  >
                    <div style={styles.imageWrap}>
                      <ProductThumbnail
                        src={item.thumbnailUrl}
                        alt={`${item.brand} ${item.name}`}
                        className="mypage-product-list-thumbnail"
                      />
                      {isSoldOut ? <ProductSoldOutOverlay /> : null}
                      {isRecent ? (
                        <button
                          aria-label={item.isWished ? `${item.name} 찜 해제` : `${item.name} 찜하기`}
                          className={`mypage-product-list-heart-button${item.isWished ? " is-wished" : ""}`}
                          disabled={pendingWishlistProductIds.has(item.productId)}
                          onClick={(event) => {
                            event.stopPropagation();
                            void toggleWishlist(item);
                          }}
                          type="button"
                        >
                          <HeartIcon size={12} />
                        </button>
                      ) : null}
                    </div>
                    <span style={styles.body}>
                      <strong style={styles.name}>{item.name}</strong>
                      <span style={styles.priceLine}>
                        {item.discountRate ? <span style={styles.discount}>{item.discountRate}%</span> : null}
                        <strong className={isSoldOut ? "product-price--sold-out" : ""} style={styles.price}>{formatPrice(item.price)}</strong>
                      </span>
                      {item.originalPrice ? <span style={styles.originalPrice}>{formatPrice(item.originalPrice)}</span> : null}
                      {item.deliveryLabel ? <span style={styles.delivery}>배송비 {item.deliveryLabel}</span> : null}
                      <span style={styles.brand}>{item.brand}</span>
                    </span>
                  </div>
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
      <LoginRequiredDialog
        onOpenChange={setIsLoginDialogOpen}
        open={isLoginDialogOpen}
        redirectTo={`${window.location.pathname}${window.location.search}`}
      />
      <ActivityToast message={toastMessage} />
      {displayItems.length > PAGE_SIZE ? (
        <nav aria-label={`${title} 페이지`} style={styles.pagination}>
          <button
            aria-label="이전 페이지"
            disabled={currentPage === 1}
            onClick={() => changePage(currentPage - 1)}
            style={currentPage === 1 ? styles.paginationButtonDisabled : styles.paginationButton}
            type="button"
          >
            이전
          </button>
          {Array.from({ length: totalPages }, (_, index) => {
            const pageNumber = index + 1;
            const isActive = pageNumber === currentPage;

            return (
              <button
                aria-current={isActive ? "page" : undefined}
                aria-label={`${pageNumber} 페이지`}
                key={pageNumber}
                onClick={() => changePage(pageNumber)}
                style={isActive ? styles.paginationButtonActive : styles.paginationButton}
                type="button"
              >
                {pageNumber}
              </button>
            );
          })}
          <button
            aria-label="다음 페이지"
            disabled={currentPage === totalPages}
            onClick={() => changePage(currentPage + 1)}
            style={currentPage === totalPages ? styles.paginationButtonDisabled : styles.paginationButton}
            type="button"
          >
            다음
          </button>
        </nav>
      ) : null}
    </MyPageLayout>
  );
}

function RecommendedProductCard({
  item,
  onOpenProduct,
  onToggleWishlist,
  wishlistPending
}: {
  item: MypageProductListItem;
  onOpenProduct?: (item: MypageProductListItem) => void;
  onToggleWishlist?: (item: MypageProductListItem) => void;
  wishlistPending?: boolean;
}) {
  const isSoldOut = isProductSoldOut({
    sales_status: item.salesStatus,
    stock_status: item.stockStatus,
    available_quantity: item.availableQuantity,
    in_stock: item.inStock
  });
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
          {isSoldOut ? <ProductSoldOutOverlay /> : null}
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
          <strong className={isSoldOut ? "product-price--sold-out" : ""} style={styles.recommendPrice}>{formatPrice(item.price)}</strong>
        </span>
      </button>
      <button
        aria-label={item.isWished ? `${item.name} 찜 해제` : `${item.name} 찜하기`}
        aria-pressed={item.isWished}
        disabled={wishlistPending}
        onClick={() => onToggleWishlist?.(item)}
        style={{
          ...styles.recommendHeart,
          color: item.isWished ? "#ff3521" : "#777777",
          cursor: wishlistPending ? "wait" : "pointer"
        }}
        type="button"
      >
        <HeartIcon filled={item.isWished} size={24} />
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
    margin: "18px 0",
    color: "#9ca3af",
    fontSize: 13,
    fontWeight: 500
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
  pagination: {
    display: "flex",
    flexWrap: "wrap",
    alignItems: "center",
    justifyContent: "center",
    gap: 8,
    marginTop: 28
  },
  paginationButton: {
    minWidth: 38,
    height: 38,
    padding: "0 12px",
    border: "1px solid #e1e5e8",
    borderRadius: 999,
    background: "#ffffff",
    color: "#3d3d3d",
    fontFamily: "inherit",
    fontSize: 13,
    fontWeight: 600,
    cursor: "pointer"
  },
  paginationButtonActive: {
    minWidth: 38,
    height: 38,
    padding: "0 12px",
    border: "1px solid #0C1117",
    borderRadius: 999,
    background: "#0C1117",
    color: "#ffffff",
    fontFamily: "inherit",
    fontSize: 13,
    fontWeight: 600,
    cursor: "pointer"
  },
  paginationButtonDisabled: {
    minWidth: 38,
    height: 38,
    padding: "0 12px",
    border: "1px solid #edf0f2",
    borderRadius: 999,
    background: "#fafafa",
    color: "#9ca3af",
    fontFamily: "inherit",
    fontSize: 13,
    fontWeight: 600,
    cursor: "not-allowed"
  },
  dateDivider: {
    padding: "6px 16px",
    background: "#f4f6f8",
    color: "#555555",
    fontSize: 16,
    fontWeight: 700
  },
  dateDividerToday: {
    padding: "6px 16px",
    background: "#f4f6f8",
    color: "#555555",
    fontSize: 16,
    fontWeight: 700
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
    fontWeight: 500,
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
    fontWeight: 700
  },
  price: {
    color: "#111111",
    fontSize: 18,
    fontWeight: 700
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
    fontWeight: 400
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
  loadingList: {
    display: "grid",
    width: "100%",
    gap: 0,
    textAlign: "left"
  },
  loadingRow: {
    position: "relative",
    display: "grid",
    gridTemplateColumns: "92px minmax(0, 1fr)",
    gap: 16,
    minHeight: 136,
    padding: "18px 0",
    borderBottom: "1px solid #eef0f2"
  },
  loadingImage: {
    display: "block",
    width: 92,
    height: 92,
    borderRadius: 6,
  },
  loadingDateBlock: {
    display: "block",
    width: "100%",
    height: 42,
    marginBottom: 0,
    borderRadius: 0,
  },
  loadingBody: {
    display: "grid",
    alignContent: "start",
    gap: 7,
    paddingTop: 2
  },
  loadingLineWide: {
    display: "block",
    width: "100%",
    height: 15,
    borderRadius: 5,
  },
  loadingLineMedium: {
    display: "block",
    width: "82%",
    height: 15,
    borderRadius: 5,
  },
  loadingLineShort: {
    display: "block",
    width: 220,
    maxWidth: "60%",
    height: 15,
    borderRadius: 5,
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
    fontWeight: 700
  },
  recommendGrid: {
    display: "grid",
    gridTemplateColumns: "repeat(3, minmax(0, 1fr))",
    gap: 18
  },
  recommendCard: {
    position: "relative",
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
    padding: 0,
    border: 0,
    borderRadius: "50%",
    background: "rgba(255,255,255,0.92)",
    color: "#777777",
    lineHeight: 1,
    zIndex: 1
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
    fontWeight: 700
  }
};
