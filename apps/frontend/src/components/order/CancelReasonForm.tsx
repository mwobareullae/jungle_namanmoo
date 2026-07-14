import type { CSSProperties, FormEvent } from "react";
import { useEffect, useState } from "react";
import {
  CANCEL_REASON_DETAIL_MAX_LENGTH,
  CANCEL_REASON_OPTIONS,
  type CancelReasonDraft
} from "./cancelReasonOptions";

type CancelReasonFormProps = {
  open: boolean;
  orderStatus: "PENDING_PAYMENT" | "PAID";
  submitting?: boolean;
  onCancel: () => void;
  onSubmit: (draft: CancelReasonDraft) => void;
};

export default function CancelReasonForm({
  open,
  orderStatus,
  submitting = false,
  onCancel,
  onSubmit
}: CancelReasonFormProps) {
  const [selectedOptionId, setSelectedOptionId] = useState("");
  const [detail, setDetail] = useState("");
  const [errorMessage, setErrorMessage] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);

  useEffect(() => {
    if (!open) return;
    const timerId = window.setTimeout(() => {
      setSelectedOptionId("");
      setDetail("");
      setErrorMessage("");
      setIsSubmitting(false);
    }, 0);
    return () => window.clearTimeout(timerId);
  }, [open]);

  if (!open) return null;

  const selectedOption = CANCEL_REASON_OPTIONS.find((option) => option.id === selectedOptionId);
  const isOther = selectedOptionId === "OTHER";

  const handleSubmit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!selectedOption) {
      setErrorMessage("취소 사유를 선택해 주세요.");
      return;
    }
    if (isOther && !detail.trim()) {
      setErrorMessage("기타 사유를 입력해 주세요.");
      return;
    }

    setErrorMessage("");
    setIsSubmitting(true);
    onSubmit({
      optionId: selectedOption.id,
      reasonCode: selectedOption.id,
      optionLabel: selectedOption.label,
      detail: detail.trim()
    });
  };

  return (
    <div aria-modal="true" role="dialog" style={styles.overlay}>
      <form aria-labelledby="cancel-reason-title" onSubmit={handleSubmit} style={styles.modal}>
        <div style={styles.header}>
          <div>
            <p style={styles.eyebrow}>주문 취소</p>
            <h2 id="cancel-reason-title" style={styles.title}>
              취소 사유를 알려주세요
            </h2>
          </div>
          <button
            aria-label="취소 사유 입력 닫기"
            className="bg-transparent hover:bg-[#FAFAFA]"
            onClick={onCancel}
            style={styles.closeButton}
            type="button"
          >
            ×
          </button>
        </div>
        <p style={styles.notice}>
          {orderStatus === "PENDING_PAYMENT"
            ? "결제 전 주문이라 확인 후 즉시 취소됩니다."
            : "결제 완료 주문은 취소 요청으로 접수되며 관리자 승인 후 처리됩니다."}
        </p>
        <fieldset style={styles.fieldset}>
          <legend style={styles.legend}>
            취소 사유 <span aria-hidden="true">*</span>
          </legend>
          <div style={styles.options}>
            {CANCEL_REASON_OPTIONS.map((option) => (
              <label key={option.id} style={styles.option}>
                <input
                  checked={selectedOptionId === option.id}
                  name="cancel-reason"
                  onChange={() => {
                    setSelectedOptionId(option.id);
                    setErrorMessage("");
                  }}
                  type="radio"
                  value={option.id}
                />
                <span>{option.label}</span>
              </label>
            ))}
          </div>
        </fieldset>
        {isOther ? (
          <label style={styles.detailLabel}>
            <span>
              상세 사유 <span aria-hidden="true">*</span>
            </span>
            <textarea
              maxLength={CANCEL_REASON_DETAIL_MAX_LENGTH}
              onChange={(event) => {
                setDetail(event.target.value);
                setErrorMessage("");
              }}
              placeholder="취소 사유를 입력해 주세요."
              rows={4}
              style={styles.textarea}
              value={detail}
            />
            <span style={styles.counter}>
              {detail.length}/{CANCEL_REASON_DETAIL_MAX_LENGTH}
            </span>
          </label>
        ) : null}
        {errorMessage ? (
          <p role="alert" style={styles.error}>
            {errorMessage}
          </p>
        ) : null}
        <div style={styles.actions}>
          <button
            className="bg-white hover:bg-[#FAFAFA]"
            disabled={submitting || isSubmitting}
            onClick={onCancel}
            style={styles.cancelButton}
            type="button"
          >
            돌아가기
          </button>
          <button
            className="bg-white hover:bg-[#EAF9FD]"
            disabled={submitting || isSubmitting}
            style={styles.submitButton}
            type="submit"
          >
            {submitting || isSubmitting ? "확인 중" : "다음"}
          </button>
        </div>
      </form>
    </div>
  );
}

const styles: Record<string, CSSProperties> = {
  overlay: {
    position: "fixed",
    inset: 0,
    zIndex: 1400,
    display: "flex",
    alignItems: "center",
    justifyContent: "center",
    padding: 16,
    background: "rgba(12, 17, 23, 0.64)"
  },
  modal: {
    width: "min(100%, 480px)",
    maxHeight: "min(720px, calc(100dvh - 32px))",
    overflowY: "auto",
    borderRadius: 18,
    background: "#ffffff",
    boxShadow: "0 18px 48px rgba(12, 17, 23, 0.2)"
  },
  header: { display: "flex", justifyContent: "space-between", gap: 16, padding: "24px 24px 0" },
  eyebrow: { margin: 0, color: "#2aa6d1", fontSize: 12, fontWeight: 700 },
  title: { margin: "5px 0 0", color: "#1a1a1a", fontSize: 20, lineHeight: 1.35 },
  closeButton: {
    width: 32,
    height: 32,
    border: 0,
    borderRadius: 8,
    color: "#6b7280",
    fontSize: 28,
    lineHeight: 1,
    cursor: "pointer"
  },
  notice: {
    margin: "16px 24px 0",
    padding: "12px 14px",
    borderRadius: 10,
    background: "#f1fbfe",
    color: "#46616d",
    fontSize: 13,
    lineHeight: 1.5
  },
  fieldset: { margin: "20px 24px 0", padding: 0, border: 0 },
  legend: { marginBottom: 10, color: "#1a1a1a", fontSize: 14, fontWeight: 700 },
  options: { display: "grid", gap: 8 },
  option: {
    display: "flex",
    alignItems: "center",
    gap: 10,
    minHeight: 44,
    padding: "0 12px",
    border: "1px solid #e2e8eb",
    borderRadius: 10,
    color: "#33434a",
    fontSize: 14,
    cursor: "pointer"
  },
  detailLabel: {
    display: "grid",
    gap: 8,
    margin: "16px 24px 0",
    color: "#1a1a1a",
    fontSize: 14,
    fontWeight: 700
  },
  textarea: {
    width: "100%",
    boxSizing: "border-box",
    padding: "12px 14px",
    border: "1px solid #dfe7ea",
    borderRadius: 10,
    color: "#33434a",
    fontSize: 14,
    fontWeight: 400,
    lineHeight: 1.5,
    resize: "vertical"
  },
  counter: { color: "#8a989e", fontSize: 12, fontWeight: 500, textAlign: "right" },
  error: { margin: "12px 24px 0", color: "#c44747", fontSize: 13 },
  actions: {
    display: "grid",
    gridTemplateColumns: "repeat(2, minmax(0, 1fr))",
    marginTop: 24,
    borderTop: "1px solid #e5e7eb"
  },
  cancelButton: {
    minHeight: 58,
    border: 0,
    borderRight: "1px solid #e5e7eb",
    color: "#3d3d3d",
    fontSize: 15,
    fontWeight: 600,
    cursor: "pointer"
  },
  submitButton: {
    minHeight: 58,
    border: 0,
    color: "#2aa6d1",
    fontSize: 15,
    fontWeight: 700,
    cursor: "pointer"
  }
};
