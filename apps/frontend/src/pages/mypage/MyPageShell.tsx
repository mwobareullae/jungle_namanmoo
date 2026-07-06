import { useContext, useEffect, useMemo, useState } from "react";
import type { CSSProperties, ReactNode } from "react";
import { Link, useLocation } from "react-router-dom";
import HomeHeader from "../../components/HomeHeader";
import { AuthContext, type AuthUser } from "../../contexts/authContextValue";
import { api } from "../../lib/api";
import { getMySkinProfile, type SkinProfileData } from "../../lib/profileApi";
import {
  getLatestSkinTestResult,
  getSkinTestImageUrl,
  saveLatestSkinTestResult
} from "../../lib/skinTest";
import type { SkinTestResult } from "../../types/skinTest";

export type MypageEventContext = {
  page: "mypage" | "mypage_skin_profile" | "mypage_wishlist";
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

type MypageToast = {
  id: number;
  message: string;
};

type MyPageShellProps = {
  children?: ReactNode;
  activePath?: "/mypage" | "/mypage/skin-profile" | "/mypage/wishlist";
  user?: MypageUserSummary;
};

type MyPageNavItem = {
  path: "/mypage" | "/mypage/skin-profile" | "";
  label: string;
  group: 1 | 2;
  disabled?: boolean;
};

let cachedSkinProfile: SkinProfileData | null | undefined;
let cachedSkinTestResult: SkinTestResult | null | undefined;

const FALLBACK_SKIN_TEST_RESULT_ID = 1;

const navItems: MyPageNavItem[] = [
  { path: "/mypage", label: "마이페이지 홈", group: 1 },
  { path: "/mypage/skin-profile", label: "피부 프로필 관리", group: 1 },
  { path: "", label: "최근 본 상품", group: 2, disabled: true },
  { path: "", label: "배송지 관리", group: 2, disabled: true }
] as const;

const orderStatusItems = [
  { label: "주문접수", count: 0 },
  { label: "결제완료", count: 0 },
  { label: "배송준비중", count: 0 },
  { label: "배송중", count: 0 },
  { label: "배송완료", count: 0 }
] as const;

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
  const [skinProfile, setSkinProfile] = useState<SkinProfileData | null>(() => cachedSkinProfile ?? null);
  const [skinTestResult, setSkinTestResult] = useState<SkinTestResult | null>(() => {
    const latestResult = getLatestSkinTestResult();
    return cachedSkinTestResult ?? latestResult;
  });
  const [toast, setToast] = useState<MypageToast | null>(null);
  const [hoveredNavLabel, setHoveredNavLabel] = useState<string | null>(null);
  const currentPath = activePath ?? (location.pathname as MyPageShellProps["activePath"]) ?? "/mypage";
  const user = useMemo(
    () => userOverride ?? buildUserSummary(authUser, skinProfile),
    [authUser, skinProfile, userOverride]
  );

  const showMypageToast = (message: string) => {
    setToast({ id: Date.now(), message });
  };

  useEffect(() => {
    if (!toast) {
      return;
    }

    const timerId = window.setTimeout(() => setToast(null), 2500);
    return () => window.clearTimeout(timerId);
  }, [toast]);

  useEffect(() => {
    if (userOverride || !authUser) {
      setSkinProfile(null);
      return;
    }

    let isMounted = true;
    const hasCachedProfile = cachedSkinProfile !== undefined;

    if (hasCachedProfile) {
      setSkinProfile(cachedSkinProfile ?? null);
    }

    getMySkinProfile()
      .then((profile) => {
        cachedSkinProfile = profile;
        if (isMounted) {
          setSkinProfile(profile);
        }
      })
      .catch(() => {
        cachedSkinProfile = null;
        if (isMounted) {
          setSkinProfile(null);
        }
      });

    return () => {
      isMounted = false;
    };
  }, [authUser, userOverride]);

  useEffect(() => {
    let isMounted = true;
    const latestResult = cachedSkinTestResult ?? getLatestSkinTestResult();
    const resultId = latestResult?.result_id ?? FALLBACK_SKIN_TEST_RESULT_ID;

    if (latestResult) {
      setSkinTestResult(latestResult);
    }

    api.getSkinTestResult(resultId)
      .then(({ result }) => {
        cachedSkinTestResult = result;
        saveLatestSkinTestResult(result);
        if (isMounted) {
          setSkinTestResult(result);
        }
      })
      .catch(() => {
        cachedSkinTestResult = latestResult ?? null;
        if (isMounted && latestResult) {
          setSkinTestResult(latestResult);
        }
      });

    return () => {
      isMounted = false;
    };
  }, []);

  return (
    <div style={styles.shell}>
      <HomeHeader />
      <nav style={styles.mobileTabs} aria-label="마이페이지 모바일 메뉴">
        {navItems.filter((item) => !item.disabled).map((item) => (
          <Link
            key={item.label}
            to={item.path}
            style={{
              ...styles.mobileTab,
              ...(currentPath === item.path ? styles.mobileTabActive : {})
            }}
          >
            {item.label}
          </Link>
        ))}
      </nav>
      <main style={styles.page}>
        <aside style={styles.sidebar} aria-label="마이페이지 메뉴">
          <section style={styles.userBlock}>
            <ProfileAvatar size="small" />
            <div>
              <strong style={styles.userName}>{user.name}</strong>
              <p style={styles.userMeta}>
                {formatSkinSummary(user.skinTypeLabel, user.sensitivityLabel)}
              </p>
            </div>
          </section>
          <nav style={styles.sidebarNav}>
            {[1, 2].map((group) => (
              <div key={group} style={group === 2 ? styles.navGroupWithLine : styles.navGroup}>
                {navItems.filter((item) => item.group === group).map((item) => (
                  item.disabled ? (
                    <span key={item.label} style={styles.navDisabled}>{item.label}</span>
                  ) : (
                    <Link
                      key={item.label}
                      to={item.path}
                      onMouseEnter={() => setHoveredNavLabel(item.label)}
                      onMouseLeave={() => setHoveredNavLabel(null)}
                      style={{
                        ...styles.navItem,
                        ...(hoveredNavLabel === item.label ? styles.navItemHover : {}),
                        ...(currentPath === item.path ? styles.navItemActive : {})
                      }}
                    >
                      {item.label}
                    </Link>
                  )
                ))}
              </div>
            ))}
          </nav>
        </aside>
        <section style={styles.content}>
          {children ?? <MyPageOverview onToast={showMypageToast} skinTestResult={skinTestResult} user={user} />}
        </section>
      </main>
      {toast ? <MypageToastMessage key={toast.id} message={toast.message} /> : null}
    </div>
  );
}

function MyPageOverview({
  onToast,
  skinTestResult,
  user
}: {
  onToast: (message: string) => void;
  skinTestResult: SkinTestResult | null;
  user: MypageUserSummary;
}) {
  return (
    <div>
      <PageTitle title="마이페이지 홈" />
      <UserSummaryCard onToast={onToast} skinTestResult={skinTestResult} user={user} />
    </div>
  );
}

function UserSummaryCard({
  onToast,
  skinTestResult,
  user
}: {
  onToast: (message: string) => void;
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
        <div style={styles.profileContentRow}>
          <div style={styles.summaryHeader}>
            <ProfileAvatar size="large" />
            <div>
              <h2 style={styles.profileName}>{user.name}</h2>
              <p style={styles.profileHandle}>{user.email}</p>
            </div>
          </div>
          <div style={styles.profileSideActions}>
            <button
              type="button"
              style={styles.profileEditButton}
              onClick={() => onToast("준비중입니다.")}
            >
              설정
            </button>
          </div>
        </div>
      </section>

      <section style={styles.summarySection} aria-label="주문 배송 조회">
        <div style={styles.summarySectionHeader}>
          <h3 style={styles.orderSectionTitle}>주문/배송 조회</h3>
          <button
            type="button"
            style={styles.orderViewAllButton}
            onClick={() => onToast("준비중입니다.")}
          >
            전체보기 <span aria-hidden="true">›</span>
          </button>
        </div>
        <section style={styles.orderStatusGrid} aria-label="주문 배송 단계">
          {orderStatusItems.map((item, index) => (
            <div key={item.label} style={styles.orderStatusItem}>
              <strong style={styles.orderStatusCount}>{item.count}</strong>
              <span style={styles.orderStatusLabel}>{item.label}</span>
              {index < orderStatusItems.length - 1 ? <span style={styles.orderStatusArrow}>›</span> : null}
            </div>
          ))}
        </section>
      </section>

      <section style={styles.summarySection} aria-label="피부 관리 정보">
        <div style={styles.summarySectionHeader}>
          <h3 style={styles.summarySectionTitle}>피부 관리 정보</h3>
          <Link to="/mypage/skin-profile" style={styles.sectionAction} aria-label="피부 관리 정보 수정하기">
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
          <Link to="/skin-test" style={styles.sectionAction} aria-label="맞춤 추천 테스트 다시 검사하기">
            다시 검사하기 <span aria-hidden="true">›</span>
          </Link>
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
    setImageFailed(false);
  }, [imageUrl]);

  return (
    <section
      style={{
        ...styles.baumannPanel,
        background: `linear-gradient(135deg, #ffffff 0%, #ffffff 54%, ${accentColor} 100%)`
      }}
      aria-label="맞춤 추천 테스트 결과"
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
      </div>
      {imageUrl && !imageFailed ? (
        <div style={styles.baumannImageWrap} aria-hidden="true">
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
        <div style={styles.baumannImageWrap} aria-hidden="true">
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

function MypageToastMessage({ message }: { message: string }) {
  return (
    <div style={styles.toast} role="status" aria-live="polite">
      <span style={styles.toastDot} />
      <span>{message}</span>
    </div>
  );
}

function ProfileAvatar({ size }: { size: "small" | "large" }) {
  const isLarge = size === "large";

  return (
    <div style={isLarge ? styles.avatarLarge : styles.avatarSmall} aria-hidden="true">
      <svg
        width={isLarge ? 34 : 22}
        height={isLarge ? 34 : 22}
        viewBox="0 0 24 24"
        fill="none"
        stroke="currentColor"
        strokeWidth="1.9"
        strokeLinecap="round"
        strokeLinejoin="round"
      >
        <path d="M20 21a8 8 0 0 0-16 0" />
        <circle cx="12" cy="8" r="4" />
      </svg>
    </div>
  );
}

function IconInfoRow({ icon, value }: { icon: "face" | "pin" | "mail"; value: string }) {
  return (
    <div style={styles.iconInfoRow}>
      <InfoIcon icon={icon} />
      <strong style={styles.iconInfoText}>{value}</strong>
    </div>
  );
}

function InfoIcon({ icon }: { icon: "face" | "pin" | "mail" }) {
  if (icon === "pin") {
    return (
      <svg style={styles.infoIcon} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8">
        <path d="M12 21s7-5.2 7-11a7 7 0 0 0-14 0c0 5.8 7 11 7 11Z" />
        <circle cx="12" cy="10" r="2.5" />
      </svg>
    );
  }

  if (icon === "mail") {
    return (
      <svg style={styles.infoIcon} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8">
        <rect x="4" y="6" width="16" height="12" rx="2" />
        <path d="m5 8 7 5 7-5" />
      </svg>
    );
  }

  return (
    <svg style={styles.infoIcon} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8">
      <path d="M20 21a8 8 0 0 0-16 0" />
      <circle cx="12" cy="8" r="4" />
    </svg>
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
  page: {
    display: "grid",
    gridTemplateColumns: "168px minmax(0, 1fr)",
    gap: 48,
    alignItems: "start",
    width: "min(1180px, calc(100% - 80px))",
    margin: "0 auto",
    padding: "36px 0 72px"
  },
  sidebar: {
    position: "sticky",
    top: 24
  },
  userBlock: {
    display: "flex",
    alignItems: "center",
    gap: 11,
    paddingBottom: 18
  },
  avatarSmall: {
    width: 38,
    height: 38,
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
    fontSize: 14,
    fontWeight: 600,
    color: "#222222"
  },
  userMeta: {
    margin: "2px 0 0",
    fontSize: 12,
    color: "#888888"
  },
  sidebarNav: {
    marginTop: 14,
    border: "1px solid #e0e0e0",
    borderRadius: 6,
    overflow: "hidden"
  },
  navGroup: {
    padding: "12px 0"
  },
  navGroupWithLine: {
    padding: "12px 0",
    borderTop: "1px solid #e0e0e0"
  },
  navItem: {
    display: "block",
    padding: "11px 16px",
    borderRadius: 0,
    color: "#444444",
    fontSize: 14,
    lineHeight: 1.45,
    textDecoration: "none"
  },
  navItemHover: {
    background: "rgba(0,0,0,0.04)"
  },
  navItemActive: {
    color: "#0c1117",
    fontWeight: 700,
    background: "transparent"
  },
  navDisabled: {
    display: "block",
    padding: "11px 16px",
    color: "#bbbbbb",
    fontSize: 14,
    lineHeight: 1.45
  },
  mobileTabs: {
    display: "none"
  },
  mobileTab: {
    display: "inline-flex",
    alignItems: "center",
    padding: "11px 14px",
    color: "#737b7a",
    fontSize: 13,
    textDecoration: "none",
    whiteSpace: "nowrap",
    borderBottom: "2px solid transparent"
  },
  mobileTabActive: {
    color: "#0c1117",
    fontWeight: 700,
    borderBottomColor: "#0c1117"
  },
  content: {
    minWidth: 0
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
  sectionAction: {
    display: "inline-flex",
    alignItems: "center",
    gap: 3,
    color: "#7b8794",
    fontSize: 13,
    fontWeight: 600,
    textDecoration: "none",
    whiteSpace: "nowrap"
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
  profileContentRow: {
    display: "flex",
    alignItems: "center",
    justifyContent: "space-between",
    gap: 24
  },
  profileSideActions: {
    display: "flex",
    flexDirection: "row",
    alignItems: "flex-end",
    gap: 8,
    flex: "0 0 auto"
  },
  profileEditButton: {
    minWidth: 70,
    minHeight: 42,
    padding: "0 22px",
    border: "1px solid #e1e5e8",
    borderRadius: 999,
    background: "#ffffff",
    color: "#333333",
    fontFamily: "inherit",
    fontSize: 15,
    fontWeight: 600,
    cursor: "pointer"
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
  baumannPanel: {
    display: "grid",
    gridTemplateColumns: "minmax(0, 1fr) 210px",
    alignItems: "center",
    gap: 24,
    minHeight: 240,
    margin: 0,
    padding: "28px 34px",
    borderRadius: 14,
    border: "1px solid #e6e9ee",
    color: "#222222",
    overflow: "hidden"
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
    fontWeight: 800
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
    justifySelf: "end",
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
    fontWeight: 800
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
  orderViewAllButton: {
    display: "inline-flex",
    alignItems: "center",
    gap: 3,
    padding: 0,
    border: "none",
    background: "transparent",
    color: "#7b8794",
    fontFamily: "inherit",
    fontSize: 13,
    fontWeight: 600,
    cursor: "pointer"
  },
  orderStatusGrid: {
    display: "grid",
    gridTemplateColumns: "repeat(5, minmax(0, 1fr))",
    gap: 0,
    padding: "12px 0 2px"
  },
  orderStatusItem: {
    position: "relative",
    display: "flex",
    flexDirection: "column",
    alignItems: "center",
    gap: 8,
    minWidth: 0
  },
  orderStatusCount: {
    color: "#d6dade",
    fontFamily: "'GmarketSans', sans-serif",
    fontSize: 24,
    fontWeight: 500,
    lineHeight: 1
  },
  orderStatusLabel: {
    color: "#aeb4ba",
    fontSize: 13,
    fontWeight: 600,
    lineHeight: 1.3,
    textAlign: "center"
  },
  orderStatusArrow: {
    position: "absolute",
    top: 3,
    right: -7,
    color: "#d7dce0",
    fontSize: 22,
    lineHeight: 1
  },
  toast: {
    position: "fixed",
    left: "50%",
    bottom: 36,
    zIndex: 1000,
    transform: "translateX(-50%)",
    display: "inline-flex",
    alignItems: "center",
    gap: 9,
    minHeight: 42,
    padding: "0 18px",
    borderRadius: 999,
    background: "#0c1117",
    color: "#ffffff",
    boxShadow: "0 12px 32px rgba(15,23,42,0.22)",
    fontSize: 14,
    fontWeight: 600
  },
  toastDot: {
    width: 7,
    height: 7,
    borderRadius: "50%",
    background: "#94e0f8",
    flex: "0 0 auto"
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
