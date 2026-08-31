import { useEffect } from "react";

/**
 * Warn before losing unsaved edits on a full-page unload (reload, tab close,
 * typed URL). In-app <Link> navigation isn't intercepted — that needs
 * react-router's data router (`useBlocker`), which this app's classic
 * <BrowserRouter> doesn't provide. The sticky Save/Discard bar keeps unsaved
 * state visible in the meantime.
 */
export function useUnsavedGuard(dirty: boolean) {
  useEffect(() => {
    if (!dirty) return;
    const handler = (e: BeforeUnloadEvent) => {
      e.preventDefault();
      e.returnValue = "";
    };
    window.addEventListener("beforeunload", handler);
    return () => window.removeEventListener("beforeunload", handler);
  }, [dirty]);
}
