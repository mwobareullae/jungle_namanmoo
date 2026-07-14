import type { CSSProperties } from "react";
import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import ConfirmModal from "../../components/ui/ConfirmModal";
import { getOrderClaim, withdrawOrderClaim } from "../../lib/claimApi";
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

const formatDate = (value?: string | null) => {
  if (!value) return "-";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat("ko-KR", { dateStyle: "medium", timeStyle: "short" }).format(date);
};

export default function ClaimDetailPage() {
  const { claimCode = "" } = useParams();
  const [claim, setClaim] = useState<OrderClaimResponse | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [errorMessage, setErrorMessage] = useState("");
  const [isWithdrawModalOpen, setIsWithdrawModalOpen] = useState(false);
  const [isWithdrawing, setIsWithdrawing] = useState(false);

  const loadClaim = () => {
    if (!claimCode) {
      setErrorMessage("클레임 번호가 없습니다.");
      setIsLoading(false);
      return;
    }
    setIsLoading(true);
    setErrorMessage("");
    void getOrderClaim(claimCode)
      .then(setClaim)
      .catch((error) =>
        setErrorMessage(
          error instanceof Error ? error.message : "클레임 상세를 불러오지 못했습니다."
        )
      )
      .finally(() => setIsLoading(false));
  };

  useEffect(() => {
    loadClaim();
  }, [claimCode]);

  const withdrawClaim = async () => {
    if (!claim || claim.status !== "REQUESTED" || isWithdrawing) return;
    setIsWithdrawing(true);
    try {
      const response = await withdrawOrderClaim(claim.claim_code);
      setClaim(response);
      setIsWithdrawModalOpen(false);
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : "클레임 철회에 실패했습니다.");
    } finally {
      setIsWithdrawing(false);
    }
  };

  return (
    <MyPageLayout activePath="/mypage/claims">
      <PageTitle
        rightSlot={
          <Link style={styles.backLink} to="/mypage/claims">
            목록으로
          </Link>
        }
        title="클레임 상세"
      />
      {isLoading ? (
        <section style={styles.stateCard}>클레임 상세를 불러오는 중입니다.</section>
      ) : null}
      {!isLoading && errorMessage ? (
        <section aria-live="polite" style={styles.stateCard}>
          <strong style={styles.stateTitle}>클레임 상세를 불러오지 못했어요</strong>
          <p style={styles.stateText}>{errorMessage}</p>
          <button
            className="bg-white hover:bg-[#FAFAFA]"
            onClick={loadClaim}
            style={styles.retryButton}
            type="button"
          >
            다시 불러오기
          </button>
        </section>
      ) : null}
      {!isLoading && claim ? (
        <div style={styles.stack}>
          <section style={styles.card}>
            <div style={styles.headerRow}>
              <h2 style={styles.title}>{claimTypeLabels[claim.claim_type]} 신청</h2>
              <span style={styles.status}>{claimStatusLabels[claim.status] ?? claim.status}</span>
            </div>
            <dl style={styles.infoList}>
              <div style={styles.infoListRow}>
                <dt>신청번호</dt>
                <dd>{claim.claim_code}</dd>
              </div>
              <div style={styles.infoListRow}>
                <dt>주문번호</dt>
                <dd>
                  <Link
                    style={styles.inlineLink}
                    to={`/mypage/orders/${encodeURIComponent(claim.order_code)}`}
                  >
                    {claim.order_code}
                  </Link>
                </dd>
              </div>
              <div style={styles.infoListRow}>
                <dt>신청 사유</dt>
                <dd>{claim.reason_detail || claim.reason_code}</dd>
              </div>
              <div style={styles.infoListRow}>
                <dt>환불 금액</dt>
                <dd>
                  {claim.refund_amount == null
                    ? "확인 중"
                    : `${claim.refund_amount.toLocaleString("ko-KR")}원`}
                </dd>
              </div>
              <div style={styles.infoListRow}>
                <dt>접수일</dt>
                <dd>{formatDate(claim.requested_at)}</dd>
              </div>
              <div style={styles.infoListRow}>
                <dt>처리일</dt>
                <dd>{formatDate(claim.processed_at)}</dd>
              </div>
              <div style={styles.infoListRow}>
                <dt>완료일</dt>
                <dd>{formatDate(claim.completed_at)}</dd>
              </div>
            </dl>
            {claim.status === "REQUESTED" ? (
              <button
                className="bg-white hover:bg-[#FAFAFA]"
                onClick={() => setIsWithdrawModalOpen(true)}
                style={styles.withdrawButton}
                type="button"
              >
                클레임 철회
              </button>
            ) : null}
          </section>
          <section style={styles.card}>
            <h2 style={styles.sectionTitle}>신청 상품</h2>
            <div style={styles.itemList}>
              {claim.items.map((item) => (
                <div key={item.order_item_id} style={styles.itemRow}>
                  <span>주문 상품 #{item.order_item_id}</span>
                  <span>
                    {item.quantity}개 · {item.resolution === "EXCHANGE" ? "교환" : "환불"}
                  </span>
                </div>
              ))}
            </div>
          </section>
        </div>
      ) : null}
      <ConfirmModal
        cancelLabel="돌아가기"
        confirmLabel={isWithdrawing ? "철회 중" : "철회하기"}
        message="접수된 클레임을 철회할까요?"
        onCancel={() => {
          if (!isWithdrawing) setIsWithdrawModalOpen(false);
        }}
        onConfirm={() => void withdrawClaim()}
        open={isWithdrawModalOpen}
        title="클레임 철회"
      />
    </MyPageLayout>
  );
}

const styles: Record<string, CSSProperties> = {
  backLink: { color: "#2aa6d1", fontSize: 14, fontWeight: 600, textDecoration: "none" },
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
  stack: { display: "grid", gap: 16 },
  card: { padding: 24, border: "1px solid #edf0f2", borderRadius: 18, background: "#ffffff" },
  headerRow: { display: "flex", alignItems: "center", justifyContent: "space-between", gap: 12 },
  title: { margin: 0, color: "#1a1a1a", fontSize: 22, fontWeight: 700 },
  sectionTitle: { margin: 0, color: "#1a1a1a", fontSize: 18, fontWeight: 700 },
  status: {
    padding: "6px 10px",
    borderRadius: 999,
    background: "#f1fbfe",
    color: "#2f7188",
    fontSize: 12,
    fontWeight: 700
  },
  infoList: { display: "grid", gap: 12, margin: "22px 0 0" },
  infoListRow: { display: "grid", gridTemplateColumns: "120px minmax(0, 1fr)", gap: 16 },
  itemRow: {
    display: "flex",
    justifyContent: "space-between",
    gap: 16,
    padding: "14px 0",
    borderTop: "1px solid #edf0f2",
    color: "#4e5c62",
    fontSize: 14
  },
  inlineLink: { color: "#2aa6d1", fontWeight: 600, textDecoration: "none" },
  withdrawButton: {
    width: "100%",
    minHeight: 46,
    marginTop: 22,
    border: "1px solid #d5d9dd",
    borderRadius: 10,
    color: "#33434a",
    fontSize: 14,
    fontWeight: 700,
    cursor: "pointer"
  },
  itemList: { display: "grid", marginTop: 14 }
};
