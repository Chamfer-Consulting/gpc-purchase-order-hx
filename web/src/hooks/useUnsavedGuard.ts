import { useEffect } from "react";
import { useBlocker } from "react-router-dom";
import { modals } from "@mantine/modals";

/**
 * Warn before losing unsaved edits: a browser `beforeunload` prompt on
 * reload/close, and a themed confirm modal on in-app navigation.
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

  const blocker = useBlocker(
    ({ currentLocation, nextLocation }) =>
      dirty && currentLocation.pathname !== nextLocation.pathname,
  );

  useEffect(() => {
    if (blocker.state !== "blocked") return;
    modals.openConfirmModal({
      title: "Discard unsaved changes?",
      children: "You've edited this order but haven't saved. Leave anyway?",
      labels: { confirm: "Discard & leave", cancel: "Stay" },
      confirmProps: { color: "red" },
      onConfirm: () => blocker.proceed(),
      onCancel: () => blocker.reset(),
    });
  }, [blocker]);
}
