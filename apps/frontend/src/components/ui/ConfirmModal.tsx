import type { CSSProperties } from "react";

type ConfirmModalProps = {
  open: boolean;
  title?: string;
  message: string;
  cancelLabel?: string;
  confirmLabel?: string;
  compact?: boolean;
  onCancel: () => void;
  onConfirm: () => void;
};

export default function ConfirmModal({
  open,
  title,
  message,
  cancelLabel = "취소",
  confirmLabel = "확인",
  compact = false,
  onCancel,
  onConfirm
}: ConfirmModalProps) {
  if (!open) return null;

  return (
    <div aria-modal="true" role="dialog" style={styles.overlay}>
      <div aria-labelledby={title ? "confirm-modal-title" : undefined} style={{ ...styles.modal, ...(compact ? styles.modalCompact : {}) }}>
        {title ? <h2 id="confirm-modal-title" style={styles.title}>{title}</h2> : null}
        <p style={{ ...styles.message, ...(compact ? styles.messageCompact : {}) }}>{message}</p>
        <div style={styles.actions}>
          <button className="bg-white hover:bg-[#FAFAFA]" onClick={onCancel} style={styles.cancelButton} type="button">
            {cancelLabel}
          </button>
          <button className="bg-white hover:bg-[#EAF9FD]" onClick={onConfirm} style={styles.confirmButton} type="button">
            {confirmLabel}
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
    width: "min(100%, 420px)",
    overflow: "hidden",
    borderRadius: 18,
    background: "#ffffff",
    boxShadow: "0 18px 48px rgba(12, 17, 23, 0.2)"
  },
  modalCompact: {
    width: "min(100%, 380px)"
  },
  title: {
    margin: 0,
    padding: "28px 28px 0",
    color: "#1a1a1a",
    fontSize: 18,
    fontWeight: 700,
    textAlign: "center"
  },
  message: {
    margin: 0,
    padding: "8px 28px 28px",
    color: "#1a1a1a",
    fontSize: 18,
    fontWeight: 700,
    lineHeight: 1.5,
    textAlign: "center"
  },
  messageCompact: {
    padding: "28px 24px",
    fontSize: 18,
    lineHeight: 1.45
  },
  actions: {
    display: "grid",
    gridTemplateColumns: "repeat(2, minmax(0, 1fr))",
    borderTop: "1px solid #e5e7eb"
  },
  cancelButton: {
    minHeight: 64,
    border: 0,
    borderRight: "1px solid #e5e7eb",
    color: "#3d3d3d",
    fontSize: 16,
    fontWeight: 500,
    cursor: "pointer"
  },
  confirmButton: {
    minHeight: 64,
    border: 0,
    color: "#2aa6d1",
    fontSize: 16,
    fontWeight: 700,
    cursor: "pointer"
  }
};
