import { ReactNode, useEffect } from "react";

interface ModalCardProps {
  open: boolean;
  title: string;
  onClose: () => void;
  children: ReactNode;
  closeDisabled?: boolean;
}

export function ModalCard({ open, title, onClose, children, closeDisabled = false }: ModalCardProps) {
  useEffect(() => {
    if (!open) {
      return;
    }

    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";

    function onKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape" && !closeDisabled) {
        onClose();
      }
    }

    window.addEventListener("keydown", onKeyDown);
    return () => {
      document.body.style.overflow = previousOverflow;
      window.removeEventListener("keydown", onKeyDown);
    };
  }, [open, onClose, closeDisabled]);

  if (!open) {
    return null;
  }

  return (
    <div
      className="modal-backdrop"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget && !closeDisabled) {
          onClose();
        }
      }}
    >
      <div className="card modal-card" role="dialog" aria-modal="true" aria-label={title}>
        <div className="modal-header">
          <h2>{title}</h2>
          <button type="button" className="modal-close-button" onClick={onClose} disabled={closeDisabled} aria-label="Close dialog">
            Close
          </button>
        </div>
        {children}
      </div>
    </div>
  );
}
