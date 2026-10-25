// Ask Hindsight as a panel over any page: on the right on wider screens, a bottom sheet under 600px.
// It wraps the Counselor page as is. Counselor mounts the first time the panel opens and stays
// mounted, so a conversation survives moving between pages.
import { useEffect, useRef } from "react";
import { Counselor } from "../routes/Counselor";
import { Icon } from "./Icons";

export const ASK_PANEL_ID = "ask-panel";
const SHEET_QUERY = "(max-width: 600px)";

export function AskPanel({
  open,
  mounted,
  pathname,
  onClose,
}: {
  open: boolean;
  /** Opened at least once: keep Counselor (and its conversation) alive. */
  mounted: boolean;
  pathname: string;
  onClose: () => void;
}) {
  const heading = useRef<HTMLHeadingElement>(null);
  const opener = useRef<HTMLElement | null>(null);

  // Focus moves into the panel on open and back to whatever opened it on close.
  useEffect(() => {
    if (open) {
      opener.current = document.activeElement as HTMLElement | null;
      heading.current?.focus();
    } else {
      opener.current?.focus();
      opener.current = null;
    }
  }, [open]);

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  // The sheet covers the page on a phone, so following a link from it closes it.
  useEffect(() => {
    if (open && window.matchMedia(SHEET_QUERY).matches) onClose();
  }, [pathname]);

  if (!mounted) return null;
  return (
    <>
      <div className="ask-backdrop" hidden={!open} onClick={onClose} />
      <aside
        id={ASK_PANEL_ID}
        className="ask-panel"
        aria-labelledby="ask-panel-title"
        hidden={!open}
      >
        <header className="ask-panel-head">
          <h2 id="ask-panel-title" ref={heading} tabIndex={-1}>
            Ask Hindsight
          </h2>
          <button
            type="button"
            className="ask-close"
            onClick={onClose}
            aria-label="Close Ask Hindsight"
          >
            <Icon name="close" size={24} />
          </button>
        </header>
        <div className="ask-panel-body">
          <Counselor />
        </div>
      </aside>
    </>
  );
}
