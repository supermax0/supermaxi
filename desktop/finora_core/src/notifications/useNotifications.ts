import { useCallback, useEffect, useRef } from "react";
import { useSource } from "../data/hooks";
import { HttpDataSource } from "../data/http";
import type { CoreEvent } from "../data/schemas";
import { useSound } from "./preferences";
import { NotificationVoice, noticeFor } from "./voice";

let active: NotificationVoice | null = null;
export function testNotificationSound() {
  active?.unlock();
  active?.enqueue({ kind: "test", key: `test:${Date.now()}` });
}
export function useNotificationVoice() {
  const source = useSource();
  const controllerRef = useRef<NotificationVoice | null>(null);
  useEffect(() => {
    const controller = new NotificationVoice(
      source instanceof HttpDataSource
        ? (notice, sdp, signal) => source.createNotificationSession(notice, sdp, signal)
        : null,
    );
    controllerRef.current = controller;
    active = controller;
    window.addEventListener("pointerdown", controller.unlock);
    window.addEventListener("keydown", controller.unlock);
    const unsubscribe = useSound.subscribe((state, prior) => {
      if (state.preferences !== prior.preferences) controller.preferencesChanged();
    });
    return () => {
      if (active === controller) active = null;
      if (controllerRef.current === controller) controllerRef.current = null;
      unsubscribe();
      window.removeEventListener("pointerdown", controller.unlock);
      window.removeEventListener("keydown", controller.unlock);
      controller.dispose();
    };
  }, [source]);
  return useCallback((event: CoreEvent) => {
    const notice = noticeFor(event);
    if (notice) controllerRef.current?.enqueue(notice);
  }, []);
}
