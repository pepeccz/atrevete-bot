"use client";

import { useCallback, useEffect, useState } from "react";
import type { Attachment } from "@/lib/types";

/**
 * useLightbox — manages open/closed state and navigation for the image lightbox.
 *
 * Accepts the full list of image-type attachments across the conversation so
 * prev/next navigation works across all messages, not just a single bubble.
 *
 * PR-3b (inbox-operator-features).
 */
export function useLightbox(images: Attachment[]) {
  const [openIndex, setOpenIndex] = useState<number | null>(null);

  const isOpen = openIndex !== null;
  const currentIndex = openIndex ?? 0;

  const open = useCallback((idx: number) => {
    setOpenIndex(idx);
  }, []);

  const close = useCallback(() => {
    setOpenIndex(null);
  }, []);

  const next = useCallback(() => {
    setOpenIndex((prev) => {
      if (prev === null) return prev;
      return prev < images.length - 1 ? prev + 1 : prev;
    });
  }, [images.length]);

  const prev = useCallback(() => {
    setOpenIndex((prev) => {
      if (prev === null) return prev;
      return prev > 0 ? prev - 1 : prev;
    });
  }, []);

  // ESC key closes the lightbox.
  useEffect(() => {
    if (!isOpen) return;
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") close();
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [isOpen, close]);

  return { isOpen, currentIndex, open, close, next, prev };
}
