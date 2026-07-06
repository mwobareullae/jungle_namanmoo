import type { CSSProperties } from "react";
import { useMemo, useState } from "react";
import EmptyState from "../../components/EmptyState";
import ProductThumbnail from "../../components/ProductThumbnail";
import { MyPageLayout, PageTitle, type MypageEventContext } from "./MyPageShell";

type WishlistSort = "all" | "recent" | "match";

export type WishlistProduct = {
  id: string;
  productId: string;
  brand: string;
  name: string;
  ingredients: string[];
  price: number;
  thumbnailUrl: string | null;
  badge?: {
    tone: "default" | "notice" | "risk";
    label: string;
  } | null;
  eventContext?: MypageEventContext;
};

type WishListProps = {
  items?: WishlistProduct[];
  onOpenProduct?: (item: WishlistProduct) => void;
  onRemoveItem?: (item: WishlistProduct) => void;
  onSortChange?: (sort: WishlistSort) => void;
};

const defaultItems: WishlistProduct[] = [
  {
    id: "1",
    productId: "prod_demo_1",
    brand: "이니스프리",
    name: "그린티 씨드 세럼",
    ingredients: ["나이아신아마이드", "녹차추출물", "판테놀"],
    price: 32000,
    thumbnailUrl: null,
    badge: { tone: "default", label: "피부타입 맞춤" },
    eventContext: { page: "mypage_wishlist", source: "wishlist", sectionId: "wishlist_grid", productId: "prod_demo_1", rank: 1 }
  },
  {
    id: "2",
    productId: "prod_demo_2",
    brand: "라네즈",
    name: "워터뱅크 블루 히알루로닉 크림",
    ingredients: ["히알루론산", "알로에베라", "베타인"],
    price: 48000,
    thumbnailUrl: null,
    badge: { tone: "notice", label: "성분 주의" },
    eventContext: { page: "mypage_wishlist", source: "wishlist", sectionId: "wishlist_grid", productId: "prod_demo_2", rank: 2 }
  },
  {
    id: "3",
    productId: "prod_demo_3",
    brand: "아누아",
    name: "어성초 77 토너 패드",
    ingredients: ["어성초추출물", "나이아신아마이드", "세라마이드"],
    price: 19800,
    thumbnailUrl: null,
    badge: null,
    eventContext: { page: "mypage_wishlist", source: "wishlist", sectionId: "wishlist_grid", productId: "prod_demo_3", rank: 3 }
  },
  {
    id: "4",
    productId: "prod_demo_4",
    brand: "닥터지",
    name: "레드 블레미쉬 클리어 수딩 크림",
    ingredients: ["병풀추출물", "알란토인", "녹차"],
    price: 24000,
    thumbnailUrl: null,
    badge: null,
    eventContext: { page: "mypage_wishlist", source: "wishlist", sectionId: "wishlist_grid", productId: "prod_demo_4", rank: 4 }
  },
  {
    id: "5",
    productId: "prod_demo_5",
    brand: "코스알엑스",
    name: "달팽이 뮤신 96 에센스",
    ingredients: ["달팽이분비물여과물", "판테놀", "나이아신아마이드"],
    price: 22500,
    thumbnailUrl: null,
    badge: { tone: "risk", label: "알코올 함유" },
    eventContext: { page: "mypage_wishlist", source: "wishlist", sectionId: "wishlist_grid", productId: "prod_demo_5", rank: 5 }
  }
];

const sortTabs: { id: WishlistSort; label: string }[] = [
  { id: "all", label: "전체" },
  { id: "recent", label: "최근 찜한 순" },
  { id: "match", label: "성분 매칭 순" }
];

const formatPrice = (price: number) => `${price.toLocaleString("ko-KR")}원`;

export default function WishList({
  items = defaultItems,
  onOpenProduct,
  onRemoveItem,
  onSortChange
}: WishListProps) {
  const [sort, setSort] = useState<WishlistSort>("all");
  const [wishlistItems, setWishlistItems] = useState(items);
  const displayItems = useMemo(() => {
    if (sort === "match") {
      return [...wishlistItems].sort((a, b) => a.ingredients.length - b.ingredients.length);
    }
    return wishlistItems;
  }, [sort, wishlistItems]);

  const updateSort = (nextSort: WishlistSort) => {
    setSort(nextSort);
    onSortChange?.(nextSort);
  };

  const removeItem = (item: WishlistProduct) => {
    setWishlistItems((prev) => prev.filter((candidate) => candidate.id !== item.id));
    onRemoveItem?.(item);
  };

  const openProduct = (item: WishlistProduct) => {
    onOpenProduct?.(item);
  };

  return (
    <MyPageLayout activePath="/mypage/wishlist">
      <style>{`
        .mypage-wishlist-thumbnail {
          display: block;
          width: 100%;
          height: 100%;
          object-fit: cover;
        }
      `}</style>
      <PageTitle
        title="찜한 상품"
        rightSlot={
          <div style={styles.sortTabs}>
            {sortTabs.map((tab) => (
              <button
                key={tab.id}
                onClick={() => updateSort(tab.id)}
                style={{
                  ...styles.sortTab,
                  ...(sort === tab.id ? styles.sortTabActive : {})
                }}
                type="button"
              >
                {tab.label}
              </button>
            ))}
          </div>
        }
      />
      {displayItems.length === 0 ? (
        <div style={styles.emptyWrap}>
          <EmptyState
            title="아직 찜한 상품이 없어요"
            description="피부 타입에 맞는 제품을 찾아 찜해보세요."
            actionLabel="제품 둘러보기"
            onAction={() => {
              window.location.href = "/";
            }}
          />
        </div>
      ) : (
        <section style={styles.grid} aria-label="찜한 상품 목록">
          {displayItems.map((item) => (
            <article key={item.id} style={styles.card}>
              <button type="button" onClick={() => openProduct(item)} style={styles.cardOpenButton}>
                <div style={styles.imageWrap}>
                  <ProductThumbnail
                    src={item.thumbnailUrl}
                    alt={`${item.brand} ${item.name}`}
                    className="mypage-wishlist-thumbnail"
                  />
                  {item.badge ? (
                    <span style={{ ...styles.badge, ...badgeToneStyles[item.badge.tone] }}>{item.badge.label}</span>
                  ) : null}
                </div>
                <span style={styles.body}>
                  <span style={styles.brand}>{item.brand}</span>
                  <strong style={styles.name}>{item.name}</strong>
                  <span style={styles.ingredients}>
                    {item.ingredients.slice(0, 3).map((ingredient) => (
                      <span key={ingredient} style={styles.ingredient}>{ingredient}</span>
                    ))}
                  </span>
                  <strong style={styles.price}>{formatPrice(item.price)}</strong>
                </span>
              </button>
              <button
                type="button"
                title="찜 해제"
                onClick={() => removeItem(item)}
                style={styles.removeButton}
              >
                ♥
              </button>
            </article>
          ))}
        </section>
      )}
    </MyPageLayout>
  );
}

const styles: Record<string, CSSProperties> = {
  sortTabs: {
    display: "flex",
    gap: 6,
    flexWrap: "wrap"
  },
  sortTab: {
    padding: "6px 13px",
    borderRadius: 999,
    border: "1px solid #e8eef1",
    background: "#ffffff",
    color: "#55585d",
    fontFamily: "inherit",
    fontSize: 12,
    fontWeight: 400,
    cursor: "pointer"
  },
  sortTabActive: {
    border: "1px solid rgba(148,224,248,0.5)",
    background: "rgba(148,224,248,0.18)",
    color: "#063445",
    fontWeight: 700
  },
  grid: {
    display: "grid",
    gridTemplateColumns: "repeat(3, minmax(0, 1fr))",
    gap: 14
  },
  card: {
    position: "relative",
    overflow: "hidden",
    border: "1px solid #e0e0e0",
    borderRadius: 10,
    background: "#ffffff"
  },
  cardOpenButton: {
    display: "block",
    width: "100%",
    border: 0,
    background: "transparent",
    padding: 0,
    color: "inherit",
    fontFamily: "inherit",
    cursor: "pointer",
    textAlign: "left"
  },
  imageWrap: {
    position: "relative",
    aspectRatio: "1.42 / 1",
    overflow: "hidden",
    background: "#f2f6f7"
  },
  badge: {
    position: "absolute",
    bottom: 9,
    left: 9,
    display: "inline-flex",
    alignItems: "center",
    minHeight: 20,
    padding: "0 7px",
    borderRadius: 999,
    fontSize: 11,
    fontWeight: 700,
    lineHeight: 1,
    whiteSpace: "nowrap"
  },
  body: {
    display: "flex",
    flexDirection: "column",
    gap: 5,
    padding: "12px 14px"
  },
  brand: {
    color: "#888888",
    fontSize: 11,
    fontWeight: 500,
    letterSpacing: "0.02em"
  },
  name: {
    display: "-webkit-box",
    minHeight: 39,
    overflow: "hidden",
    color: "#222222",
    fontSize: 13,
    fontWeight: 400,
    lineHeight: 1.5,
    WebkitBoxOrient: "vertical",
    WebkitLineClamp: 2
  },
  ingredients: {
    display: "flex",
    flexWrap: "wrap",
    gap: 4,
    minHeight: 20
  },
  ingredient: {
    display: "inline-flex",
    alignItems: "center",
    minHeight: 20,
    padding: "0 6px",
    border: "1px solid rgba(148,224,248,0.65)",
    borderRadius: 999,
    color: "#2aa6d1",
    fontSize: 10,
    fontWeight: 500,
    whiteSpace: "nowrap"
  },
  price: {
    marginTop: 4,
    color: "#063445",
    fontSize: 15,
    fontWeight: 700
  },
  removeButton: {
    position: "absolute",
    top: 9,
    right: 9,
    zIndex: 1,
    width: 30,
    height: 30,
    borderRadius: "50%",
    border: "1px solid rgba(255,255,255,0.85)",
    background: "rgba(255,255,255,0.9)",
    color: "#e86f5b",
    cursor: "pointer"
  },
  emptyWrap: {
    display: "flex",
    alignItems: "center",
    justifyContent: "center",
    minHeight: 280,
    padding: 40,
    textAlign: "center"
  }
};

const badgeToneStyles: Record<NonNullable<WishlistProduct["badge"]>["tone"], CSSProperties> = {
  default: {
    background: "rgba(148,224,248,0.18)",
    border: "1px solid rgba(148,224,248,0.5)",
    color: "#063445"
  },
  notice: {
    background: "rgba(245,158,11,0.12)",
    border: "1px solid rgba(245,158,11,0.35)",
    color: "#92400e"
  },
  risk: {
    background: "rgba(232,111,91,0.1)",
    border: "1px solid rgba(232,111,91,0.35)",
    color: "#b91c1c"
  }
};
