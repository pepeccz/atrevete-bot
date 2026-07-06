"use client";

import React, {
  createContext,
  useContext,
  useState,
  useEffect,
  useCallback,
} from "react";

interface SidebarContextType {
  /** The user's persisted preference — the only value ever written to localStorage. */
  isCollapsed: boolean;
  /**
   * PR-5 (sidebar-collapse architecture fix): a NON-PERSISTED, route-scoped
   * override. Routes with a layout that overflows below `xl` (e.g.
   * /conversations) call `setAutoCollapsed(true)` while narrow and
   * `setAutoCollapsed(false)` on unmount/regrow — this never touches
   * `isCollapsed` or localStorage, so a hard reload while narrow can no
   * longer "consolidate" the auto-collapse into the user's real preference
   * (the bug the prior borrow/restore approach had: shrinking wrote through
   * to the persisted key, and a reload lost the in-memory record needed to
   * restore it, leaving the sidebar stuck collapsed).
   */
  autoCollapsed: boolean;
  /** What should actually be RENDERED — `isCollapsed || autoCollapsed`. */
  effectiveCollapsed: boolean;
  setAutoCollapsed: (value: boolean) => void;
  isMobileOpen: boolean;
  isMobileSearchOpen: boolean;
  toggle: () => void;
  toggleMobile: () => void;
  closeMobile: () => void;
  toggleMobileSearch: () => void;
  closeMobileSearch: () => void;
  collapse: () => void;
  expand: () => void;
}

const SidebarContext = createContext<SidebarContextType | undefined>(undefined);

const STORAGE_KEY = "sidebar_collapsed";

export function SidebarProvider({ children }: { children: React.ReactNode }) {
  const [isCollapsed, setIsCollapsed] = useState(false);
  // PR-5: route-scoped, in-memory-only override — never read from or
  // written to localStorage (see `autoCollapsed` doc above).
  const [autoCollapsed, setAutoCollapsed] = useState(false);
  const [isMobileOpen, setIsMobileOpen] = useState(false);
  const [isMobileSearchOpen, setIsMobileSearchOpen] = useState(false);
  const [isHydrated, setIsHydrated] = useState(false);

  const effectiveCollapsed = isCollapsed || autoCollapsed;

  // Load from localStorage on mount
  useEffect(() => {
    const stored = localStorage.getItem(STORAGE_KEY);
    if (stored !== null) {
      setIsCollapsed(stored === "true");
    }
    setIsHydrated(true);
  }, []);

  // Save to localStorage on change. Watches ONLY `isCollapsed` (the user's
  // preference) — `autoCollapsed` is intentionally excluded, so a route's
  // temporary auto-collapse can never leak into the persisted preference.
  useEffect(() => {
    if (isHydrated) {
      localStorage.setItem(STORAGE_KEY, String(isCollapsed));
    }
  }, [isCollapsed, isHydrated]);

  // Manual-toggle semantics while auto-collapsed (PR-5, orchestrator
  // decision): the toggle button acts on the EFFECTIVE (displayed) state,
  // not the raw persisted one, and its result becomes the new persisted
  // preference. Concretely: invert whatever the user currently SEES
  // (`effectiveCollapsed`) and write that into `isCollapsed`, while clearing
  // `autoCollapsed` — a manual action always wins and opts the user out of
  // the auto-collapse for the remainder of this route visit (until the
  // route's own viewport-change listener genuinely re-enters a narrow
  // range, e.g. the user grows the window back out and shrinks it again).
  // When `autoCollapsed` is always false (routes that don't use it), this
  // is byte-for-byte the same toggle as before — no behavior change there.
  const toggle = useCallback(() => {
    setIsCollapsed((prevIsCollapsed) => {
      const wasEffectivelyCollapsed = prevIsCollapsed || autoCollapsed;
      return !wasEffectivelyCollapsed;
    });
    setAutoCollapsed(false);
  }, [autoCollapsed]);

  const toggleMobile = useCallback(() => {
    setIsMobileOpen((prev) => !prev);
  }, []);

  const closeMobile = useCallback(() => {
    setIsMobileOpen(false);
  }, []);

  const toggleMobileSearch = useCallback(() => {
    setIsMobileSearchOpen((prev) => !prev);
  }, []);

  const closeMobileSearch = useCallback(() => {
    setIsMobileSearchOpen(false);
  }, []);

  const collapse = useCallback(() => {
    setIsCollapsed(true);
  }, []);

  const expand = useCallback(() => {
    setIsCollapsed(false);
  }, []);

  return (
    <SidebarContext.Provider
      value={{
        isCollapsed,
        autoCollapsed,
        effectiveCollapsed,
        setAutoCollapsed,
        isMobileOpen,
        isMobileSearchOpen,
        toggle,
        toggleMobile,
        closeMobile,
        toggleMobileSearch,
        closeMobileSearch,
        collapse,
        expand,
      }}
    >
      {children}
    </SidebarContext.Provider>
  );
}

export function useSidebar() {
  const context = useContext(SidebarContext);
  if (context === undefined) {
    throw new Error("useSidebar must be used within a SidebarProvider");
  }
  return context;
}
