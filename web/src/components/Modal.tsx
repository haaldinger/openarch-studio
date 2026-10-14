import { useEffect, useRef, type ReactNode } from "react";
import { createPortal } from "react-dom";
import { X } from "lucide-react";

interface ModalProps {
  open: boolean;
  title: string;
  onClose: () => void;
  children: ReactNode;
  footer?: ReactNode;
  /** Element to focus when the modal opens (e.g. the primary input). */
  initialFocusRef?: React.RefObject<HTMLElement>;
}

/** Accessible, themed dialog: overlay, Esc/overlay-click to close, focus on open. */
export function Modal({ open, title, onClose, children, footer, initialFocusRef }: ModalProps) {
  const cardRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    document.addEventListener("keydown", onKey);
    const focusTarget = initialFocusRef?.current ?? cardRef.current;
    focusTarget?.focus();
    return () => document.removeEventListener("keydown", onKey);
  }, [open, onClose, initialFocusRef]);

  if (!open) return null;

  return createPortal(
    <div className="modal-overlay" onMouseDown={onClose}>
      <div
        ref={cardRef}
        className="modal"
        role="dialog"
        aria-modal="true"
        aria-label={title}
        tabIndex={-1}
        onMouseDown={(e) => e.stopPropagation()}
      >
        <header className="modal-head">
          <h2 className="modal-title">{title}</h2>
          <button type="button" className="modal-close" aria-label="Close" onClick={onClose}>
            <X size={18} />
          </button>
        </header>
        <div className="modal-body">{children}</div>
        {footer && <footer className="modal-actions">{footer}</footer>}
      </div>
    </div>,
    document.body,
  );
}
