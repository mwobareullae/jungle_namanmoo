import { useEffect, useRef, type CSSProperties, type ReactNode } from "react";

type ConfirmModalProps = {
  open: boolean;
  title?: string;
  message: string;
  cancelLabel?: string;
  confirmLabel?: string;
  compact?: boolean;
  children?: ReactNode;
  onCancel: () => void;
  onConfirm: () => void;
};

const FOCUSABLE_SELECTOR =
  'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])';

export default function ConfirmModal({
  open,
  title,
  message,
  cancelLabel = "취소",
  confirmLabel = "확인",
  compact = false,
  children,
  onCancel,
  onConfirm
}: ConfirmModalProps) {
  const modalRef = useRef<HTMLDivElement>(null);
  const cancelButtonRef = useRef<HTMLButtonElement>(null);
  const previouslyFocusedRef = useRef<HTMLElement | null>(null);
  const onCancelRef = useRef(onCancel);

  useEffect(() => {
    onCancelRef.current = onCancel;
  });

  useEffect(() => {
    if (!open) return undefined;

    previouslyFocusedRef.current = document.activeElement as HTMLElement | null;
    cancelButtonRef.current?.focus();

    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        onCancelRef.current();
        return;
      }
      if (event.key !== "Tab" || !modalRef.current) return;

      const focusables = Array.from(modalRef.current.querySelectorAll<HTMLElement>(FOCUSABLE_SELECTOR));
      if (focusables.length === 0) return;

      const first = focusables[0];
      const last = focusables[focusables.length - 1];

      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    };

    document.addEventListener("keydown", handleKeyDown);
    return () => {
      document.removeEventListener("keydown", handleKeyDown);
      previouslyFocusedRef.current?.focus();
    };
  }, [open]);

  if (!open) return null;

  return (
    <div aria-modal="true" role="dialog" style={styles.overlay}>
      <div aria-labelledby={title ? "confirm-modal-title" : undefined} ref={modalRef} style={{ ...styles.modal, ...(compact ? styles.modalCompact : {}) }}>
        {title ? <h2 id="confirm-modal-title" style={styles.title}>{title}</h2> : null}
        <p style={{ ...styles.message, ...(compact ? styles.messageCompact : {}) }}>{message}</p>
        {children ? <div style={styles.extra}>{children}</div> : null}
        <div style={styles.actions}>
          <button className="bg-white hover:bg-[#FAFAFA]" onClick={onCancel} ref={cancelButtonRef} style={styles.cancelButton} type="button">
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
  extra: {
    display: "flex",
    justifyContent: "center",
    padding: "0 28px 28px"
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
