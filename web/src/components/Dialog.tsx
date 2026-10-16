import { useEffect, useRef } from "react";
import type { ReactNode } from "react";

/** A modal dialog on the native `<dialog>` element: `showModal()` supplies Escape, the
 *  focus trap and the backdrop. It is closed by its button, by Escape and by a click on
 *  the backdrop, and focus goes back to what opened it. */
export function Dialog({
  title,
  onClose,
  returnFocusTo,
  wide = false,
  children,
}: {
  title: ReactNode;
  onClose: () => void;
  /** The element to focus again when the dialog closes (the native default is the
   *  element focused when it opened, which a mouse click on a row would not be). */
  returnFocusTo?: HTMLElement | null;
  /** A wider dialog, for a table. */
  wide?: boolean;
  children: ReactNode;
}) {
  const ref = useRef<HTMLDialogElement>(null);
  const closeRef = useRef(onClose);
  closeRef.current = onClose;
  const focusRef = useRef(returnFocusTo);
  focusRef.current = returnFocusTo;

  useEffect(() => {
    const dialog = ref.current;
    if (!dialog) return;
    if (!dialog.open) dialog.showModal();
    return () => {
      if (dialog.open) dialog.close();
      focusRef.current?.focus();
    };
  }, []);

  return (
    <dialog
      ref={ref}
      className={wide ? "dialog dialog-wide" : "dialog"}
      aria-labelledby="dialog-title"
      onCancel={(e) => {
        // Escape: let React unmount us (which closes the dialog) instead of the browser.
        e.preventDefault();
        closeRef.current();
      }}
      onKeyDown={(e) => {
        if (e.key === "Escape") {
          e.preventDefault();
          closeRef.current();
        }
      }}
      onClick={(e) => {
        // only a click on the backdrop itself, never on the content
        if (e.target === ref.current) closeRef.current();
      }}
    >
      <div className="dialog-head">
        <h2 id="dialog-title">{title}</h2>
        <button className="btn" onClick={() => closeRef.current()} aria-label="Close">
          Close
        </button>
      </div>
      <div className="dialog-body">{children}</div>
    </dialog>
  );
}
