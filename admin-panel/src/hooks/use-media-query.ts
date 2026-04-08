"use client";

import { useState, useEffect } from "react";

/**
 * Evalúa una media query CSS y devuelve si coincide con el viewport actual.
 * Maneja SSR correctamente devolviendo `false` en el servidor.
 *
 * @param query  Media query CSS, e.g. "(max-width: 768px)"
 * @returns      `true` si la media query coincide; `false` si no coincide o en SSR
 *
 * @example
 * const isMobile = useMediaQuery("(max-width: 768px)");
 */
export function useMediaQuery(query: string): boolean {
  const [matches, setMatches] = useState<boolean>(false);

  useEffect(() => {
    // SSR safety: window no existe en el servidor
    if (typeof window === "undefined") return;

    const mediaQueryList = window.matchMedia(query);

    // Establecer el valor inicial
    setMatches(mediaQueryList.matches);

    // Listener para cambios de viewport
    const handleChange = (event: MediaQueryListEvent) => {
      setMatches(event.matches);
    };

    mediaQueryList.addEventListener("change", handleChange);

    return () => {
      mediaQueryList.removeEventListener("change", handleChange);
    };
  }, [query]);

  return matches;
}
