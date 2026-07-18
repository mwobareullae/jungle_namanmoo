import { ArrowClockwise } from "@phosphor-icons/react";
import { Link, Navigate, useLocation } from "react-router-dom";

import { AdminAccessStatus } from "./hooks/useAdminAccess";

// 관리자 페이지 진입 게이트. AdminDashboardPage 전체를 감싸서, 로그인/권한이
// 확인되기 전에는 사이드바·mock 화면 등 어떤 관리자 UI도 노출하지 않는다.

type AdminAccessNoticeProps = {
  status: Exclude<AdminAccessStatus, "authenticated">;
  retry: () => void;
};

export function AdminAccessNotice({ status, retry }: AdminAccessNoticeProps) {
  const location = useLocation();

  if (status === "unauthenticated") {
    return (
      <Navigate
        replace
        state={{ from: `${location.pathname}${location.search}${location.hash}` }}
        to="/login"
      />
    );
  }

  if (status === "forbidden") {
    return <Navigate replace to="/" />;
  }

  if (status === "checking") {
    return <main aria-busy="true" style={styles.loadingScreen} />;
  }

  return (
    <main style={styles.errorScreen}>
      <section aria-labelledby="adminAccessErrorTitle" style={styles.errorCard}>
        <div aria-hidden="true" style={styles.iconWrap}>
          <ArrowClockwise color="#0B2A3A" size={28} weight="regular" />
        </div>
        <div style={styles.copy}>
          <h1 id="adminAccessErrorTitle" style={styles.title}>페이지를 불러오지 못했어요</h1>
          <p style={styles.description}>네트워크 연결을 확인한 뒤 다시 시도해 주세요.</p>
        </div>
        <button onClick={retry} style={styles.retryButton} type="button">
          다시 시도
        </button>
        <Link style={styles.homeLink} to="/">홈으로 가기</Link>
      </section>
    </main>
  );
}

const styles = {
  loadingScreen: {
    minHeight: "100vh",
    background: "#000000"
  },
  errorScreen: {
    display: "grid",
    minHeight: "100vh",
    padding: 24,
    placeItems: "center",
    background: "#000000"
  },
  errorCard: {
    display: "grid",
    width: "min(100%, 440px)",
    justifyItems: "center",
    gap: 20,
    padding: "36px 32px",
    borderRadius: 16,
    background: "#FFFFFF",
    textAlign: "center" as const
  },
  iconWrap: {
    display: "grid",
    width: 56,
    height: 56,
    placeItems: "center",
    borderRadius: "50%",
    background: "#ECEFF3"
  },
  copy: {
    display: "grid",
    gap: 8
  },
  title: {
    margin: 0,
    color: "#25313F",
    fontSize: 20,
    fontWeight: 700,
    lineHeight: 1.35
  },
  description: {
    margin: 0,
    color: "#8A93A0",
    fontSize: 14,
    fontWeight: 500,
    lineHeight: 1.6
  },
  retryButton: {
    minWidth: 132,
    minHeight: 44,
    padding: "0 20px",
    border: 0,
    borderRadius: 10,
    background: "#0B2A3A",
    color: "#FFFFFF",
    cursor: "pointer",
    font: "inherit",
    fontSize: 14,
    fontWeight: 700
  },
  homeLink: {
    color: "#8A93A0",
    fontSize: 14,
    fontWeight: 600,
    textDecoration: "none"
  }
};
