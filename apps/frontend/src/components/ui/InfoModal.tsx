import type { CSSProperties, ReactNode } from "react";

type InfoModalProps = {
  open: boolean;
  title?: string;
  children: ReactNode;
  closeLabel?: string;
  onClose: () => void;
};

// ConfirmModal 은 항상 취소/확인 두 버튼을 나란히 보여주는 확인용 모달이라, 그냥 조회만
// 하는 화면(예: 클레임 처리 이력)에 쓰면 같은 동작을 하는 버튼이 두 개 떠서 어색하다.
// 같은 관리자 모달 톤(어두운 오버레이 + 흰 카드)을 유지하면서 닫기 버튼 하나만 둔다.
export default function InfoModal({ open, title, children, closeLabel = "닫기", onClose }: InfoModalProps) {
  if (!open) return null;

  return (
    <div aria-modal="true" role="dialog" style={styles.overlay}>
      <div aria-labelledby={title ? "info-modal-title" : undefined} style={styles.modal}>
        {title ? (
          <h2 id="info-modal-title" style={styles.title}>
            {title}
          </h2>
        ) : null}
        <div style={styles.body}>{children}</div>
        <div style={styles.actions}>
          <button onClick={onClose} style={styles.closeButton} type="button">
            {closeLabel}
          </button>
        </div>
      </div>
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
    padding: 24,
    background: "rgba(12, 17, 23, 0.64)"
  },
  modal: {
    width: "min(100%, 560px)",
    maxHeight: "82vh",
    display: "flex",
    flexDirection: "column",
    overflow: "hidden",
    borderRadius: 18,
    background: "#ffffff",
    boxShadow: "0 18px 48px rgba(12, 17, 23, 0.2)"
  },
  title: {
    margin: 0,
    padding: "24px 24px 0",
    color: "#1a1a1a",
    fontSize: 18,
    fontWeight: 700,
    textAlign: "left"
  },
  body: {
    flex: "1 1 auto",
    minHeight: 0,
    overflowY: "auto",
    padding: "16px 24px 24px"
  },
  actions: {
    borderTop: "1px solid #e5e7eb",
    padding: "12px 24px"
  },
  closeButton: {
    width: "100%",
    minHeight: 44,
    border: "1px solid #e5e7eb",
    borderRadius: 10,
    background: "#ffffff",
    color: "#3d3d3d",
    fontSize: 15,
    fontWeight: 600,
    cursor: "pointer"
  }
};
