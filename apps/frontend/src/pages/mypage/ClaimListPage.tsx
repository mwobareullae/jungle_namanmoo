import type { CSSProperties } from "react";
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { getOrderClaims } from "../../lib/claimApi";
import type { OrderClaimResponse } from "../../types/claim";
import { MyPageLayout, PageTitle } from "./MyPageShell";

const claimTypeLabels: Record<OrderClaimResponse["claim_type"], string> = {
  RETURN: "반품",
  EXCHANGE: "교환",
  REFUND: "환불"
};

const claimStatusLabels: Record<string, string> = {
  REQUESTED: "접수됨",
  APPROVED: "승인됨",
  REJECTED: "반려됨",
  IN_PROGRESS: "처리중",
  COMPLETED: "처리완료",
  WITHDRAWN: "철회됨"
};

const formatDate = (value: string) => {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat("ko-KR", {
    year: "numeric",
    month: "numeric",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false
  }).format(date);
};

export default function ClaimListPage() {
  const [claims, setClaims] = useState<OrderClaimResponse[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [errorMessage, setErrorMessage] = useState("");

  const loadClaims = () => {
    setIsLoading(true);
    setErrorMessage("");
    void getOrderClaims()
      .then((response) => setClaims(response.items))
      .catch((error) =>
        setErrorMessage(
          error instanceof Error ? error.message : "클레임 내역을 불러오지 못했습니다."
        )
      )
      .finally(() => setIsLoading(false));
  };

  useEffect(() => {
    loadClaims();
  }, []);

  return (
    <MyPageLayout activePath="/mypage/claims">
      <PageTitle title="클레임 내역" />
      {isLoading ? (
        <section style={styles.stateCard}>클레임 내역을 불러오는 중입니다.</section>
      ) : errorMessage ? (
        <section aria-live="polite" style={styles.stateCard}>
          <strong style={styles.stateTitle}>클레임 내역을 불러오지 못했어요</strong>
          <p style={styles.stateText}>{errorMessage}</p>
          <button
            className="bg-white hover:bg-[#FAFAFA]"
            onClick={loadClaims}
            style={styles.retryButton}
            type="button"
          >
            다시 불러오기
          </button>
        </section>
      ) : claims.length === 0 ? (
        <section style={styles.stateCard}>
          <strong style={styles.stateTitle}>신청한 클레임이 없어요</strong>
          <p style={styles.stateText}>반품·교환·환불 신청 내역이 이곳에 표시됩니다.</p>
          <Link
            className="bg-[#0C1117] hover:bg-[#1A1A1A]"
            style={styles.primaryLink}
            to="/mypage/orders"
          >
            주문/배송내역 보기
          </Link>
        </section>
      ) : (
        <div style={styles.list}>
          {claims.map((claim) => (
            <Link
              className="no-underline hover:bg-[#FAFAFA]"
              key={claim.claim_code}
              style={styles.claimCard}
              to={`/mypage/claims/${encodeURIComponent(claim.claim_code)}`}
            >
              <div style={styles.claimHeader}>
                <strong style={styles.claimType}>{claimTypeLabels[claim.claim_type]}</strong>
                <span style={styles.claimStatus}>
                  {claimStatusLabels[claim.status] ?? claim.status}
                </span>
              </div>
              <div style={styles.claimInfo}>
                <span>신청번호 {claim.claim_code}</span>
                <span>주문번호 {claim.order_code}</span>
                <span>{formatDate(claim.requested_at)}</span>
              </div>
              <span style={styles.detailLink}>상세 보기 ›</span>
            </Link>
          ))}
        </div>
      )}
    </MyPageLayout>
  );
}

const styles: Record<string, CSSProperties> = {
  stateCard: {
    display: "grid",
    gap: 12,
    justifyItems: "center",
    padding: "72px 24px",
    border: "1px solid #edf0f2",
    borderRadius: 18,
    background: "#ffffff",
    textAlign: "center"
  },
  stateTitle: { color: "#1a1a1a", fontSize: 20, fontWeight: 700 },
  stateText: { margin: 0, color: "#7b868b", fontSize: 14, lineHeight: 1.6 },
  retryButton: {
    minHeight: 42,
    padding: "0 18px",
    border: "1px solid #dfe7ea",
    borderRadius: 10,
    color: "#33434a",
    fontSize: 14,
    fontWeight: 600,
    cursor: "pointer"
  },
  primaryLink: {
    display: "inline-flex",
    alignItems: "center",
    justifyContent: "center",
    minHeight: 44,
    padding: "0 18px",
    borderRadius: 10,
    color: "#ffffff",
    fontSize: 14,
    fontWeight: 600,
    textDecoration: "none"
  },
  list: { display: "grid", gap: 12 },
  claimCard: {
    position: "relative",
    display: "grid",
    gap: 12,
    padding: 22,
    border: "1px solid #e5eaec",
    borderRadius: 16,
    background: "#ffffff",
    color: "inherit"
  },
  claimHeader: { display: "flex", alignItems: "center", justifyContent: "space-between", gap: 12 },
  claimType: { color: "#1a1a1a", fontSize: 18, fontWeight: 700 },
  claimStatus: {
    padding: "5px 9px",
    borderRadius: 999,
    background: "#f1fbfe",
    color: "#2f7188",
    fontSize: 12,
    fontWeight: 700
  },
  claimInfo: { display: "grid", gap: 5, color: "#7b868b", fontSize: 13, lineHeight: 1.5 },
  detailLink: { color: "#2aa6d1", fontSize: 13, fontWeight: 700 }
};
