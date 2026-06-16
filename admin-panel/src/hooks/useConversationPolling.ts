"use client";

import { useEffect, useRef, useCallback } from "react";

type PollingMode = "thread" | "list";

interface UseConversationPollingOptions {
  /**
   * The async function to call on each poll tick.
   * Should be a stable reference (memoized with useCallback).
   */
  fetchFn: () => Promise<void>;
  /**
   * "thread" — active conversation thread view (3s focused / 10s blurred).
   * "list"   — conversation list view (60s baseline / 30s if unread badge > 0).
   */
  mode: PollingMode;
  /**
   * Number of unread/triggered items. When > 0 in list mode the interval
   * shortens from 60s to 30s to surface new items faster.
   */
  unreadCount?: number;
  /** Set false to pause polling regardless of visibility (e.g. during a mutation). */
  enabled?: boolean;
}

/**
 * Adaptive conversation polling hook.
 *
 * Cadences (FR-UI-6, NFR-3):
 * - Thread mode + window focused: 3 s
 * - Thread mode + window blurred: 10 s
 * - List mode + no unread:        60 s
 * - List mode + unread > 0:       30 s
 * - document.hidden = true:       paused (no polls)
 *
 * Backoff on consecutive errors: doubles the current interval on each error,
 * capped at 60 s. Resets when a poll succeeds.
 *
 * Uses Page Visibility API + window focus/blur events.
 */
export function useConversationPolling({
  fetchFn,
  mode,
  unreadCount = 0,
  enabled = true,
}: UseConversationPollingOptions): void {
  const isFocusedRef = useRef<boolean>(
    typeof document !== "undefined" ? document.hasFocus() : true
  );
  const backoffRef = useRef<number>(0); // consecutive error count
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const getBaseInterval = useCallback((): number => {
    if (mode === "thread") {
      return isFocusedRef.current ? 3_000 : 10_000;
    }
    // list mode
    return unreadCount > 0 ? 30_000 : 60_000;
  }, [mode, unreadCount]);

  const getInterval = useCallback((): number => {
    const base = getBaseInterval();
    if (backoffRef.current === 0) return base;
    // Exponential backoff: base * 2^errors, capped at 60s
    return Math.min(base * Math.pow(2, backoffRef.current), 60_000);
  }, [getBaseInterval]);

  const scheduleNext = useCallback(
    (intervalMs: number, poll: () => void) => {
      if (timerRef.current !== null) {
        clearTimeout(timerRef.current);
      }
      timerRef.current = setTimeout(poll, intervalMs);
    },
    []
  );

  useEffect(() => {
    if (!enabled) return;

    let cancelled = false;

    const poll = async () => {
      if (cancelled) return;
      if (typeof document !== "undefined" && document.hidden) {
        // Page is hidden — pause, retry when visible.
        scheduleNext(getInterval(), poll);
        return;
      }
      try {
        await fetchFn();
        backoffRef.current = 0; // reset on success
      } catch {
        backoffRef.current = Math.min(backoffRef.current + 1, 5); // cap at 5 doublings
      }
      if (!cancelled) {
        scheduleNext(getInterval(), poll);
      }
    };

    // Initial load runs unconditionally — even if the tab is currently hidden
    // (e.g. opened in a background tab or restored on startup) — so the view is
    // populated by the time the user looks at it. Subsequent scheduled polls
    // still respect document.hidden (in `poll`) to avoid background work.
    const initialFetch = async () => {
      if (cancelled) return;
      try {
        await fetchFn();
        backoffRef.current = 0;
      } catch {
        backoffRef.current = Math.min(backoffRef.current + 1, 5);
      }
      if (!cancelled) {
        scheduleNext(getInterval(), poll);
      }
    };
    initialFetch();

    const handleFocus = () => {
      isFocusedRef.current = true;
    };
    const handleBlur = () => {
      isFocusedRef.current = false;
    };
    const handleVisibilityChange = () => {
      if (!document.hidden && !cancelled) {
        // Tab became visible — poll immediately to surface any missed messages.
        if (timerRef.current !== null) {
          clearTimeout(timerRef.current);
          timerRef.current = null;
        }
        poll();
      }
    };

    if (typeof window !== "undefined") {
      window.addEventListener("focus", handleFocus);
      window.addEventListener("blur", handleBlur);
      document.addEventListener("visibilitychange", handleVisibilityChange);
    }

    return () => {
      cancelled = true;
      if (timerRef.current !== null) {
        clearTimeout(timerRef.current);
        timerRef.current = null;
      }
      if (typeof window !== "undefined") {
        window.removeEventListener("focus", handleFocus);
        window.removeEventListener("blur", handleBlur);
        document.removeEventListener("visibilitychange", handleVisibilityChange);
      }
    };
  }, [enabled, fetchFn, scheduleNext, getInterval]);
}
