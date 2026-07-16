import { Fragment, useContext, useEffect, useMemo, useState } from "react";
import type { CSSProperties, ReactNode } from "react";
import { Link, useLocation } from "react-router-dom";
import HomeHeader from "../../components/HomeHeader";
import { AuthContext, type AuthUser } from "../../contexts/authContextValue";
import { api } from "../../lib/api";
import { getOrderSummary } from "../../lib/orderApi";
import type { SkinProfileData } from "../../lib/profileApi";
import { useSkinProfileQuery } from "../../hooks/useSkinProfileQuery";
import { getSkinTestImageUrl } from "../../lib/skinTest";
import type { SkinTestResult } from "../../types/skinTest";

export type MypageEventContext = {
  page: "mypage" | "mypage_skin_profile" | "mypage_wishlist" | "mypage_recent";
  source?: string;
  sectionId?: string;
  productId?: string;
  rank?: number;
  recommendationId?: string;
  metadata?: Record<string, string | number | boolean | null>;
};

export type MypageUserSummary = {
  name: string;
  handle: string;
  email: string;
  skinTypeLabel: string;
  sensitivityLabel: string;
  concernLabels: string[];
  avoidIngredientLabels: string[];
  locationLabel: string;
  wishlistCount: number;
  reviewCount: number;
  eventContext?: MypageEventContext;
};

type MyPageShellProps = {
  children?: ReactNode;
  activePath?: "/mypage" | "/mypage/skin-profile" | "/mypage/wishlist" | "/mypage/recent" | "/mypage/reviews" | "/mypage/orders" | "/mypage/claims" | "/mypage/addresses" | "/mypage/settings";
  user?: MypageUserSummary;
};

type MyPageNavItem = {
  path: "/mypage" | "/mypage/skin-profile" | "/mypage/wishlist" | "/mypage/recent" | "/mypage/reviews" | "/mypage/orders" | "/mypage/claims" | "/mypage/addresses" | "/mypage/settings";
  label: string;
  group: 1 | 2 | 3;
};

let cachedSkinTestResult: SkinTestResult | null | undefined;

const navItems: MyPageNavItem[] = [
  { path: "/mypage", label: "마이페이지 홈", group: 1 },
  { path: "/mypage/skin-profile", label: "피부 프로필", group: 1 },
  { path: "/mypage/wishlist", label: "찜한 상품", group: 2 },
  { path: "/mypage/recent", label: "최근 본 상품", group: 2 },
  { path: "/mypage/reviews", label: "리뷰 관리", group: 2 },
  { path: "/mypage/orders", label: "주문/배송내역", group: 3 },
  { path: "/mypage/claims", label: "클레임 내역", group: 3 },
  { path: "/mypage/addresses", label: "배송지 관리", group: 3 },
  { path: "/mypage/settings", label: "개인정보 설정", group: 3 }
] as const;

const orderStatusItems = [
  { label: "주문접수", statuses: ["PENDING_PAYMENT"] },
  { label: "결제완료", statuses: ["PAID"] },
  { label: "배송준비중", statuses: ["PREPARING_SHIPMENT"] },
  { label: "배송중", statuses: ["SHIPPED"] },
  { label: "배송완료", statuses: ["DELIVERED"] }
] as const;

type OrderStatusSummaryItem = {
  label: string;
  count: number;
};

const buildOrderStatusSummary = (statusCounts: Record<string, number>): OrderStatusSummaryItem[] =>
  orderStatusItems.map((item) => ({
    label: item.label,
    count: item.statuses.reduce((total, status) => total + (statusCounts[status] ?? 0), 0)
  }));

const emptyOrderStatusSummary = buildOrderStatusSummary({});

const formatSensitivityLabel = (label: string) => (label === "미설정" ? "민감도 미설정" : `민감 ${label}`);

const formatSkinSummary = (skinTypeLabel: string, sensitivityLabel: string) =>
  `${skinTypeLabel} · ${formatSensitivityLabel(sensitivityLabel)}`;

const getDisplayName = (user: AuthUser | null) =>
  user?.nickname?.trim() || user?.email.split("@")[0] || "고객";

const getHandle = (user: AuthUser | null) => {
  const baseHandle = user?.nickname?.trim() || user?.email.split("@")[0] || "guest";
  return `@${baseHandle.replace(/\s+/g, "_")}`;
};

const buildUserSummary = (authUser: AuthUser | null, skinProfile: SkinProfileData | null): MypageUserSummary => ({
  name: authUser ? getDisplayName(authUser) : "로그인이 필요해요",
  handle: authUser ? getHandle(authUser) : "@guest",
  email: authUser?.email ?? "-",
  skinTypeLabel: skinProfile?.skinType ?? "미설정",
  sensitivityLabel: skinProfile?.sensitivity ?? "미설정",
  concernLabels: skinProfile?.concerns ?? [],
  avoidIngredientLabels: skinProfile?.avoidIngredients ?? [],
  locationLabel: "대표 배송지 미설정",
  wishlistCount: 0,
  reviewCount: 0,
  eventContext: {
    page: "mypage",
    source: "mypage_shell"
  }
});

export function MyPageLayout({ children, activePath, user: userOverride }: MyPageShellProps) {
  const location = useLocation();
  const authContext = useContext(AuthContext);
  const authUser = authContext?.user ?? null;
  const skinProfileQuery = useSkinProfileQuery(authUser?.id ?? null, !userOverride);
  const skinProfile = userOverride ? null : (skinProfileQuery.data ?? null);
  const [skinTestResult, setSkinTestResult] = useState<SkinTestResult | null>(null);
  const [orderStatusSummary, setOrderStatusSummary] = useState<OrderStatusSummaryItem[]>(emptyOrderStatusSummary);
  const currentPath = activePath ?? (location.pathname as MyPageShellProps["activePath"]) ?? "/mypage";
  const authUserId = authUser?.id;
  const skinProfileUserId = skinProfile?.userId;
  const latestSkinTestResultId = skinProfile?.latestSkinTestResultId;
  const user = useMemo(
    () => userOverride ?? buildUserSummary(authUser, skinProfile),
    [authUser, skinProfile, userOverride]
  );

  useEffect(() => {
    if (!authUser) {
      const timerId = window.setTimeout(() => setOrderStatusSummary(emptyOrderStatusSummary), 0);
      return () => window.clearTimeout(timerId);
    }

    let isMounted = true;

    const loadOrderStatusSummary = async () => {
      try {
        const response = await getOrderSummary();

        if (isMounted) {
          setOrderStatusSummary(buildOrderStatusSummary(response.status_counts));
        }
      } catch {
        if (isMounted) {
          setOrderStatusSummary(emptyOrderStatusSummary);
        }
      }
    };

    void loadOrderStatusSummary();

    const refreshOrderStatusSummary = () => {
      void loadOrderStatusSummary();
    };
    window.addEventListener("orders:updated", refreshOrderStatusSummary);

    return () => {
      isMounted = false;
      window.removeEventListener("orders:updated", refreshOrderStatusSummary);
    };
  }, [authUser]);

  useEffect(() => {
    if (!authUserId || !skinProfileUserId || skinProfileUserId !== authUserId || !latestSkinTestResultId) {
      cachedSkinTestResult = null;
      const timerId = window.setTimeout(() => setSkinTestResult(null), 0);
      return () => window.clearTimeout(timerId);
    }

    let isMounted = true;
    const resultId = latestSkinTestResultId;

    if (cachedSkinTestResult?.result_id === resultId) {
      const timerId = window.setTimeout(() => {
        if (isMounted) {
          setSkinTestResult(cachedSkinTestResult ?? null);
        }
      }, 0);

      return () => {
        isMounted = false;
        window.clearTimeout(timerId);
      };
    }

    api.getSkinTestResult(resultId)
      .then(({ result }) => {
        cachedSkinTestResult = result;
        if (isMounted) {
          setSkinTestResult(result);
        }
      })
      .catch(() => {
        cachedSkinTestResult = null;
        if (isMounted) {
          setSkinTestResult(null);
        }
      });

    return () => {
      isMounted = false;
    };
  }, [authUserId, latestSkinTestResultId, skinProfileUserId]);

  return (
    <div style={styles.shell}>
      <HomeHeader />
      <nav
        aria-label="마이페이지 모바일 메뉴"
        className="mypage-mobile-nav gap-1 overflow-x-auto border-b border-[#e0e0e0]"
      >
        {navItems.filter((item) => item.path).map((item) => (
          <Link
            className={`inline-flex items-center whitespace-nowrap border-b-2 px-3.5 py-[11px] text-[13px] no-underline ${
              currentPath === item.path
                ? "border-[#0C1117] font-semibold text-[#0C1117]"
                : "border-transparent text-[#737b7a]"
            }`}
            key={item.label}
            to={item.path}
          >
            {item.label}
          </Link>
        ))}
      </nav>
      <main className="mypage-layout-main mx-auto grid w-[calc(100%-40px)] items-start gap-12 py-9 pb-[72px]">
        <aside aria-label="마이페이지 메뉴" className="mypage-sidebar sticky top-20">
          <section style={styles.userBlock}>
            <ProfileAvatar size="small" />
            <div>
              <strong style={styles.userName}>{user.name}</strong>
              <p style={styles.userMeta}>
                {formatSkinSummary(user.skinTypeLabel, user.sensitivityLabel)}
              </p>
            </div>
          </section>
          <nav className="mypage-sidebar-nav mt-3.5 overflow-hidden rounded-lg border border-[#e0e0e0]">
            {[1, 2, 3].map((group) => (
              <div
                className={group === 1 ? "py-7" : "border-t border-[#e0e0e0] py-7"}
                key={group}
              >
                {navItems.filter((item) => item.group === group).map((item) => (
                  item.path ? (
                    <Link
                      className={`block px-8 py-3 text-[17px] leading-[1.5] no-underline hover:bg-black/[0.04] ${
                        currentPath === item.path ? "font-semibold text-[#0C1117]" : "font-normal text-[#444444]"
                      }`}
                      key={item.label}
                      to={item.path}
                    >
                      {item.label}
                    </Link>
                  ) : (
                    <span
                      className="block px-8 py-3 text-[17px] font-normal leading-[1.5] text-[#444444]"
                      key={item.label}
                    >
                      {item.label}
                    </span>
                  )
                ))}
              </div>
            ))}
          </nav>
        </aside>
        <section className="min-w-0">
          {children ?? (
            <MyPageOverview
              orderStatusSummary={orderStatusSummary}
              skinTestResult={skinTestResult}
              user={user}
            />
          )}
        </section>
      </main>
    </div>
  );
}

function MyPageOverview({
  orderStatusSummary,
  skinTestResult,
  user
}: {
  orderStatusSummary: OrderStatusSummaryItem[];
  skinTestResult: SkinTestResult | null;
  user: MypageUserSummary;
}) {
  return (
    <div>
      <PageTitle title="마이페이지 홈" />
      <UserSummaryCard
        orderStatusSummary={orderStatusSummary}
        skinTestResult={skinTestResult}
        user={user}
      />
    </div>
  );
}

function UserSummaryCard({
  orderStatusSummary,
  skinTestResult,
  user
}: {
  orderStatusSummary: OrderStatusSummaryItem[];
  skinTestResult: SkinTestResult | null;
  user: MypageUserSummary;
}) {
  const concernTags = user.concernLabels.length > 0 ? user.concernLabels : ["피부 고민 미설정"];
  const avoidTags = user.avoidIngredientLabels;

  return (
    <section style={styles.summaryCard} aria-label="사용자 요약">
      <section style={styles.summarySection} aria-label="기본 프로필">
        <div style={styles.summarySectionHeader}>
          <h3 style={styles.summarySectionTitle}>기본 프로필</h3>
        </div>
        <div className="flex flex-wrap items-center justify-between gap-6">
          <div style={styles.summaryHeader}>
            <ProfileAvatar size="large" />
            <div>
              <h2 style={styles.profileName}>{user.name}</h2>
              <p style={styles.profileHandle}>{user.email}</p>
            </div>
          </div>
          <div style={styles.profileSideActions}>
            <Link
              className="min-h-[42px] min-w-[70px] rounded-full border border-[#e1e5e8] bg-white px-[22px] text-[15px] font-semibold text-[#333333] hover:bg-[#FAFAFA]"
              style={styles.profileSettingsLink}
              to="/mypage/settings"
            >
              설정
            </Link>
          </div>
        </div>
      </section>

      <section style={styles.summarySection} aria-label="주문 배송 조회">
        <div style={styles.summarySectionHeader}>
          <h3 style={styles.orderSectionTitle}>주문/배송내역</h3>
          <Link
            className="inline-flex items-center gap-[3px] text-[13px] font-semibold text-[#7b8794] no-underline hover:text-[#1A1A1A]"
            to="/mypage/orders"
          >
            전체보기 <span aria-hidden="true">›</span>
          </Link>
        </div>
        <section
          aria-label="주문 배송 단계"
          className="flex items-center gap-1 overflow-x-auto pt-3 pb-0.5 sm:justify-between sm:gap-0 sm:overflow-visible"
        >
          {orderStatusSummary.map((item, index) => {
            const isActive = item.count > 0;
            const statusContent = (
              <div className="flex min-w-[64px] shrink-0 flex-col items-center gap-2 sm:min-w-0 sm:flex-1">
                <strong
                  className={`whitespace-nowrap font-['GmarketSans',sans-serif] text-[20px] leading-none sm:text-[24px] ${isActive ? "text-[#1A1A1A]" : "text-[#d6dade]"}`}
                >
                  {item.count}
                </strong>
                <span
                  className={`text-center text-[11px] leading-tight font-semibold whitespace-nowrap sm:text-[13px] ${isActive ? "text-[#1A1A1A]" : "text-[#aeb4ba]"}`}
                >
                  {item.label}
                </span>
              </div>
            );

            return (
              <Fragment key={item.label}>
                {isActive ? (
                  <Link
                    aria-label={`${item.label} ${item.count}건 조회`}
                    className="flex min-w-[64px] shrink-0 flex-1 items-center justify-center no-underline transition-opacity hover:opacity-65 sm:min-w-0"
                    to="/mypage/orders"
                  >
                    {statusContent}
                  </Link>
                ) : statusContent}
                {index < orderStatusSummary.length - 1 ? (
                  <span aria-hidden="true" className="shrink-0 text-[16px] leading-none text-[#d7dce0] sm:text-[22px]">
                    ›
                  </span>
                ) : null}
              </Fragment>
            );
          })}
        </section>
      </section>

      <section style={styles.summarySection} aria-label="피부 관리 정보">
        <div style={styles.summarySectionHeader}>
          <h3 style={styles.summarySectionTitle}>피부 관리 정보</h3>
          <Link
            aria-label="피부 관리 정보 수정하기"
            className="inline-flex items-center gap-[3px] text-[13px] font-semibold text-[#7b8794] no-underline hover:text-[#1A1A1A]"
            to="/mypage/skin-profile"
          >
            수정하기 <span aria-hidden="true">›</span>
          </Link>
        </div>
        <div style={styles.skinInfoGroup}>
          <div>
            <h4 style={styles.skinInfoTitle}>피부 고민</h4>
            <div style={styles.tagRow}>
              {concernTags.map((label) => (
                <span key={label} style={styles.hashTag}>#{label}</span>
              ))}
            </div>
          </div>
          <div style={styles.skinInfoSubsection}>
            <h4 style={styles.skinInfoTitle}>피하고 싶은 성분</h4>
            <div style={styles.tagRow}>
              {avoidTags.length > 0 ? (
                avoidTags.map((label) => (
                  <span key={label} style={styles.avoidHashTag}>#{label}</span>
                ))
              ) : (
                <span style={styles.emptyTag}>등록된 성분 없음</span>
              )}
            </div>
          </div>
        </div>
      </section>

      <section style={styles.summarySectionLast} aria-label="맞춤 추천 테스트 결과 섹션">
        <div style={styles.summarySectionHeader}>
          <h3 style={styles.summarySectionTitle}>맞춤 추천 테스트 결과</h3>
          {skinTestResult ? (
            <Link
              aria-label="맞춤 추천 테스트 다시 검사하기"
              className="inline-flex items-center gap-[3px] text-[13px] font-semibold text-[#7b8794] no-underline hover:text-[#1A1A1A]"
              to="/skin-test"
            >
              다시 검사하기 <span aria-hidden="true">›</span>
            </Link>
          ) : null}
        </div>
        <BaumannResultPanel result={skinTestResult} />
      </section>
    </section>
  );
}

function BaumannResultPanel({ result }: { result: SkinTestResult | null }) {
  const imageUrl = resolveMypageSkinTestImageUrl(getSkinTestImageUrl(result?.image_storage_key));
  const [imageFailed, setImageFailed] = useState(false);
  const [accentColor, setAccentColor] = useState("rgba(255, 154, 49, 0.12)");
  const typeCode = result?.type_code ?? "TYPE";
  const title = result?.title ?? "맞춤 추천 테스트 결과";
  const subtitle = result?.subtitle ?? "최근 피부 타입 테스트 결과를 불러오고 있어요.";
  const concernTags = result?.concern_tags ?? result?.avoid_hint ?? [];
  const effectTags = result?.recommended_effects ?? [];

  useEffect(() => {
    const timerId = window.setTimeout(() => setImageFailed(false), 0);
    return () => window.clearTimeout(timerId);
  }, [imageUrl]);

  if (!result) {
    return (
      <section
        style={styles.skinTestEmptyPanel}
        aria-label="저장된 맞춤 추천 테스트 결과 없음"
      >
        <div style={styles.skinTestEmptyContent}>
          <h3 style={styles.skinTestEmptyTitle}>아직 저장된 테스트 결과가 없어요</h3>
          <Link
            className="inline-flex min-h-[38px] items-center justify-center gap-1 rounded-full bg-[#0C1117] px-4 text-[13px] font-semibold text-white no-underline hover:bg-[#1A1A1A]"
            to="/skin-test"
          >
            피부 테스트 시작하기 <span aria-hidden="true">›</span>
          </Link>
        </div>
      </section>
    );
  }

  return (
    <section
      aria-label="맞춤 추천 테스트 결과"
      className="grid grid-cols-1 items-center gap-6 rounded-[14px] border border-[#e6e9ee] p-7 lg:grid-cols-[minmax(0,1fr)_210px]"
      style={{
        background: `linear-gradient(135deg, #ffffff 0%, #ffffff 54%, ${accentColor} 100%)`
      }}
    >
      <div style={styles.baumannContent}>
        <strong style={styles.baumannCode}>{typeCode}</strong>
        <h3 style={styles.baumannTitle}>{title}</h3>
        <p style={styles.baumannDescription}>{subtitle}</p>
        {concernTags.length > 0 ? (
          <div style={styles.baumannTagRow}>
            {concernTags.map((tag) => <span key={tag} style={styles.baumannTag}>{tag}</span>)}
          </div>
        ) : null}
        {effectTags.length > 0 ? (
          <div style={styles.baumannEffectRow}>
            {effectTags.slice(0, 3).map((effect) => <span key={effect} style={styles.baumannEffectTag}>{effect}</span>)}
          </div>
        ) : null}
        <Link
          className="mt-5 inline-flex min-h-[42px] items-center justify-center gap-1 rounded-full bg-[#0C1117] px-5 text-[13px] font-bold text-white no-underline transition-colors hover:bg-[#1A1A1A]"
          onClick={() => window.scrollTo({ top: 0, behavior: "auto" })}
          to={`/skin-test/recommendations?result_id=${encodeURIComponent(result.result_id)}`}
        >
          맞춤 추천 결과 보러가기 <span aria-hidden="true">›</span>
        </Link>
      </div>
      {imageUrl && !imageFailed ? (
        <div aria-hidden="true" className="justify-self-center lg:justify-self-end" style={styles.baumannImageWrap}>
          <img
            src={imageUrl}
            alt=""
            style={styles.baumannImage}
            onError={() => setImageFailed(true)}
            onLoad={(event) => {
              const extractedColor = getImageAccentColor(event.currentTarget);
              if (extractedColor) {
                setAccentColor(extractedColor);
              }
            }}
          />
        </div>
      ) : (
        <div aria-hidden="true" className="justify-self-center lg:justify-self-end" style={styles.baumannImageWrap}>
          <span style={styles.baumannImageFallback}>{typeCode}</span>
        </div>
      )}
    </section>
  );
}

function resolveMypageSkinTestImageUrl(url: string) {
  if (!url) {
    return "";
  }

  if (/^[a-z][a-z\d+.-]*:\/\//i.test(url) || url.startsWith("/")) {
    return url;
  }

  return `/${url}`;
}

function getImageAccentColor(image: HTMLImageElement) {
  try {
    const canvas = document.createElement("canvas");
    const context = canvas.getContext("2d");
    if (!context) {
      return null;
    }

    canvas.width = 1;
    canvas.height = 1;
    context.drawImage(image, 0, 0, 1, 1);
    const [red, green, blue] = context.getImageData(0, 0, 1, 1).data;
    return `rgba(${red}, ${green}, ${blue}, 0.14)`;
  } catch {
    return null;
  }
}

function ProfileAvatar({ size }: { size: "small" | "large" }) {
  const isLarge = size === "large";

  return (
    <div style={isLarge ? styles.avatarLarge : styles.avatarSmall} aria-hidden="true">
      <img
        alt=""
        src="/mypage-profile-rabbit.png"
        style={{ width: "100%", height: "100%", borderRadius: "50%", objectFit: "cover" }}
      />
    </div>
  );
}

export function PageTitle({ title, rightSlot }: { title: string; rightSlot?: ReactNode }) {
  return (
    <header style={styles.titleRow}>
      <h1 style={styles.title}>{title}</h1>
      {rightSlot}
    </header>
  );
}

const styles: Record<string, CSSProperties> = {
  shell: {
    minHeight: "100vh",
    background: "#ffffff",
    color: "#222222",
    fontFamily: "'Pretendard Variable', 'Pretendard', 'Noto Sans KR', sans-serif"
  },
  userBlock: {
    display: "flex",
    alignItems: "center",
    gap: 12,
    padding: "16px 18px",
    marginBottom: 18,
    borderRadius: 14,
    background: "#ffffff",
    border: "1px solid rgba(148, 224, 248, 0.4)"
  },
  avatarSmall: {
    width: 42,
    height: 42,
    borderRadius: "50%",
    background: "#94e0f8",
    color: "#0c6f8f",
    display: "flex",
    alignItems: "center",
    justifyContent: "center",
    flex: "0 0 auto"
  },
  userName: {
    display: "block",
    fontSize: 15,
    fontWeight: 700,
    color: "#0C1117"
  },
  userMeta: {
    margin: "3px 0 0",
    fontSize: 12,
    fontWeight: 600,
    color: "#2aa6d1"
  },
  titleRow: {
    display: "flex",
    alignItems: "flex-end",
    justifyContent: "space-between",
    gap: 16,
    flexWrap: "wrap",
    paddingBottom: 14,
    marginBottom: 28,
    borderBottom: "2px solid #222222"
  },
  title: {
    margin: 0,
    color: "#222222",
    fontFamily: "'GmarketSans', sans-serif",
    fontSize: 24,
    fontWeight: 500
  },
  summaryCard: {
    background: "#ffffff",
    padding: "0 0 4px",
    marginBottom: 0
  },
  summarySection: {
    padding: "0 0 30px",
    marginBottom: 30,
    borderBottom: "1px solid #e6e6e6"
  },
  summarySectionLast: {
    padding: 0,
    marginBottom: 0
  },
  summarySectionHeader: {
    display: "flex",
    alignItems: "center",
    justifyContent: "space-between",
    gap: 12,
    marginBottom: 18
  },
  summarySectionTitle: {
    margin: 0,
    color: "#222222",
    fontSize: 15,
    fontWeight: 700,
    lineHeight: 1.35
  },
  skinInfoGroup: {
    display: "grid",
    gap: 22
  },
  skinInfoSubsection: {
    paddingTop: 22,
    borderTop: "1px solid #f0f2f4"
  },
  skinInfoTitle: {
    margin: "0 0 12px",
    color: "#6b7280",
    fontSize: 13,
    fontWeight: 700,
    lineHeight: 1.35
  },
  profileSideActions: {
    display: "flex",
    flexDirection: "row",
    alignItems: "flex-end",
    gap: 8,
    flex: "0 0 auto"
  },
  profileSettingsLink: {
    display: "inline-flex",
    alignItems: "center",
    justifyContent: "center",
    textDecoration: "none"
  },
  summaryHeader: {
    display: "flex",
    alignItems: "center",
    gap: 18,
    marginBottom: 0
  },
  heroRow: {
    display: "flex",
    alignItems: "center",
    gap: 20,
    paddingBottom: 24,
    marginBottom: 24,
    borderBottom: "1px solid #e0e0e0"
  },
  avatarLarge: {
    width: 60,
    height: 60,
    borderRadius: "50%",
    background: "#94e0f8",
    color: "#0c6f8f",
    display: "flex",
    alignItems: "center",
    justifyContent: "center",
    flex: "0 0 auto"
  },
  profileName: {
    margin: "0 0 3px",
    color: "#222222",
    fontFamily: "'GmarketSans', sans-serif",
    fontSize: 20,
    fontWeight: 500
  },
  profileHandle: {
    margin: "4px 0 0",
    color: "#888888",
    fontSize: 13,
    fontWeight: 500
  },
  tagRow: {
    display: "flex",
    gap: "10px 8px",
    flexWrap: "wrap",
    marginBottom: 0
  },
  hashTag: {
    display: "inline-flex",
    alignItems: "center",
    minHeight: 34,
    padding: "0 14px",
    borderRadius: 999,
    border: "1px solid #f1f1f1",
    background: "#f7f7f7",
    color: "#6b7280",
    fontSize: 13,
    fontWeight: 600
  },
  avoidHashTag: {
    display: "inline-flex",
    alignItems: "center",
    minHeight: 34,
    padding: "0 14px",
    borderRadius: 999,
    border: "1px solid #ffd6df",
    background: "#fff1f4",
    color: "#b44b62",
    fontSize: 13,
    fontWeight: 600,
    lineHeight: 1.45,
    whiteSpace: "normal"
  },
  emptyTag: {
    display: "inline-flex",
    alignItems: "center",
    minHeight: 34,
    padding: "0 14px",
    borderRadius: 999,
    border: "1px solid #eeeeee",
    background: "#fafafa",
    color: "#9ca3af",
    fontSize: 13,
    fontWeight: 500
  },
  infoList: {
    display: "grid",
    gap: 16,
    marginBottom: 24
  },
  skinTestEmptyPanel: {
    display: "grid",
    alignItems: "center",
    justifyItems: "center",
    minHeight: 168,
    padding: "28px 30px",
    border: "1px solid #e6e9ee",
    borderRadius: 14,
    background: "#fbfcfd",
    color: "#222222"
  },
  skinTestEmptyContent: {
    display: "grid",
    justifyItems: "center",
    minWidth: 0,
    textAlign: "center"
  },
  skinTestEmptyTitle: {
    margin: "0 0 16px",
    color: "#0d2231",
    fontFamily: "'GmarketSans', sans-serif",
    fontSize: 19,
    fontWeight: 500,
    lineHeight: 1.35
  },
  baumannContent: {
    maxWidth: 560
  },
  baumannCode: {
    display: "inline-flex",
    alignItems: "center",
    minHeight: 34,
    marginBottom: 12,
    padding: "0 13px",
    borderRadius: 10,
    background: "rgba(12,35,49,0.88)",
    color: "#ffffff",
    fontSize: 13,
    fontWeight: 700
  },
  baumannTitle: {
    margin: "0 0 10px",
    color: "#0d2231",
    fontFamily: "'GmarketSans', sans-serif",
    fontSize: 22,
    fontWeight: 500
  },
  baumannDescription: {
    margin: "0 0 20px",
    color: "#6b7280",
    fontSize: 14,
    fontWeight: 500
  },
  baumannTagRow: {
    display: "flex",
    flexWrap: "wrap",
    gap: 8,
    marginBottom: 10
  },
  baumannTag: {
    display: "inline-flex",
    alignItems: "center",
    minHeight: 30,
    padding: "0 12px",
    borderRadius: 999,
    background: "#f1f3f5",
    color: "#243241",
    fontSize: 12,
    fontWeight: 700
  },
  baumannEffectRow: {
    display: "flex",
    flexWrap: "wrap",
    gap: 8
  },
  baumannEffectTag: {
    display: "inline-flex",
    alignItems: "center",
    minHeight: 30,
    padding: "0 12px",
    borderRadius: 999,
    border: "1px solid rgba(148,224,248,0.72)",
    background: "#edfbff",
    color: "#063445",
    fontSize: 12,
    fontWeight: 700
  },
  baumannImageWrap: {
    width: 190,
    height: 190,
    borderRadius: "50%",
    background: "#ffffff",
    border: "1px solid #eef0f3",
    boxShadow: "0 12px 28px rgba(15,23,42,0.08)",
    display: "flex",
    alignItems: "center",
    justifyContent: "center",
    overflow: "hidden"
  },
  baumannImage: {
    width: "100%",
    height: "100%",
    objectFit: "cover"
  },
  baumannImageFallback: {
    color: "#0d2231",
    fontSize: 28,
    fontWeight: 700
  },
  iconInfoRow: {
    display: "flex",
    alignItems: "center",
    gap: 13,
    minWidth: 0
  },
  infoIcon: {
    width: 20,
    height: 20,
    flex: "0 0 auto",
    color: "#9ca3af"
  },
  iconInfoText: {
    color: "#333333",
    fontSize: 14,
    fontWeight: 600,
    lineHeight: 1.45,
    overflowWrap: "anywhere"
  },
  cardDivider: {
    height: 1,
    margin: "0 0 0",
    background: "#e0e0e0"
  },
  orderSectionTitle: {
    margin: 0,
    color: "#222222",
    fontSize: 15,
    fontWeight: 700,
    lineHeight: 1.35
  },
  quickGrid: {
    display: "grid",
    gridTemplateColumns: "1fr 1fr",
    gap: 10,
    marginBottom: 32
  },
  quickLink: {
    display: "flex",
    alignItems: "center",
    justifyContent: "space-between",
    minHeight: 46,
    padding: "0 14px 0 16px",
    borderRadius: 10,
    border: "1px solid #e0e0e0",
    background: "#fafafa",
    color: "#222222",
    fontSize: 13,
    fontWeight: 500,
    textDecoration: "none"
  },
  quickArrow: {
    color: "#94e0f8",
    fontSize: 22,
    lineHeight: 1
  },
  profileTable: {
    paddingTop: 24,
    borderTop: "1px solid #e0e0e0"
  },
  sectionEyebrow: {
    margin: "0 0 16px",
    color: "#999999",
    fontSize: 11,
    fontWeight: 700,
    letterSpacing: "0.09em",
    textTransform: "uppercase"
  },
  infoRow: {
    display: "flex",
    minHeight: 24,
    fontSize: 14
  },
  infoLabel: {
    minWidth: 110,
    color: "#888888"
  },
  infoValue: {
    color: "#222222",
    fontWeight: 600,
    lineHeight: 1.65
  }
};

export default function MyPageShell() {
  return <MyPageLayout activePath="/mypage" />;
}
