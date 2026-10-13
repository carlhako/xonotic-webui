import type { ReactNode } from "react";

/** The inline "are you sure" used before anything that disturbs connected players. */
export function Confirm({
  children,
  confirmLabel,
  onConfirm,
  onCancel,
}: {
  children: ReactNode;
  confirmLabel: string;
  onConfirm: () => void;
  onCancel: () => void;
}) {
  return (
    <div className="confirm" role="alertdialog" aria-label="Confirm">
      <p>{children}</p>
      <div className="controls-row">
        <button className="btn btn-danger" onClick={onConfirm}>
          {confirmLabel}
        </button>
        <button className="btn" onClick={onCancel}>
          Cancel
        </button>
      </div>
    </div>
  );
}
