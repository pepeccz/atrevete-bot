"use client";

import { useEffect, useRef } from "react";
import { createPortal } from "react-dom";
import { X, ChevronLeft, ChevronRight } from "lucide-react";
import type { Attachment } from "@/lib/types";

interface Props {
  /** Only image-type attachments; sorted by position. */
  attachments: Attachment[];
  initialIndex: number;
  onClose: () => void;
  onNext: () => void;
  onPrev: () => void;
  currentIndex: number;
}

/**
 * AttachmentLightbox — full-screen image viewer with keyboard navigation.
 *
 * - Portal-based overlay rendered to document.body.
 * - Backdrop click closes.
 * - ESC key handled by useLightbox (parent hook).
 * - Left/Right arrows navigate (disabled at bounds).
 * - Displays filename + "Imagen N de M" counter.
 *
 * PR-3b (inbox-operator-features).
 */
export function AttachmentLightbox({
  attachments,
  onClose,
  onNext,
  onPrev,
  currentIndex,
}: Props) {
  const closeButtonRef = useRef<HTMLButtonElement>(null);
  const total = attachments.length;
  const current = attachments[currentIndex];

  // Focus the close button on mount for accessibility.
  useEffect(() => {
    closeButtonRef.current?.focus();
  }, []);

  // Navigate with keyboard arrow keys.
  useEffect(() => {
    const handleKey = (e: KeyboardEvent) => {
      if (e.key === "ArrowRight") onNext();
      if (e.key === "ArrowLeft") onPrev();
    };
    window.addEventListener("keydown", handleKey);
    return () => window.removeEventListener("keydown", handleKey);
  }, [onNext, onPrev]);

  if (!current) return null;

  const canGoPrev = currentIndex > 0;
  const canGoNext = currentIndex < total - 1;
  const displayName = current.filename ?? "Imagen";
  const counter = total > 1 ? `Imagen ${currentIndex + 1} de ${total}` : "Imagen";

  return createPortal(
    <div
      className="fixed inset-0 z-[9999] flex flex-col items-center justify-center bg-black/85"
      role="dialog"
      aria-modal="true"
      aria-label={counter}
      onClick={onClose}
    >
      {/* Top bar: filename + counter + close button */}
      <div
        className="absolute top-0 left-0 right-0 flex items-center justify-between px-4 py-3 text-white/90 bg-black/40"
        onClick={(e) => e.stopPropagation()}
      >
        <span className="text-sm truncate max-w-[60vw]" title={displayName}>
          {displayName}
        </span>
        <div className="flex items-center gap-3">
          <span className="text-sm text-white/70">{counter}</span>
          <button
            ref={closeButtonRef}
            onClick={onClose}
            aria-label="Cerrar"
            className="rounded-full p-1.5 hover:bg-white/15 transition-colors focus:outline-none focus:ring-2 focus:ring-white/50"
          >
            <X className="h-5 w-5" />
          </button>
        </div>
      </div>

      {/* Prev arrow */}
      {total > 1 && (
        <button
          onClick={(e) => {
            e.stopPropagation();
            onPrev();
          }}
          disabled={!canGoPrev}
          aria-label="Imagen anterior"
          className="absolute left-3 top-1/2 -translate-y-1/2 rounded-full p-2 bg-black/40 text-white hover:bg-black/60 disabled:opacity-20 disabled:cursor-default transition-colors focus:outline-none focus:ring-2 focus:ring-white/50"
        >
          <ChevronLeft className="h-6 w-6" />
        </button>
      )}

      {/* Image — click does not close (stopPropagation) */}
      <img
        src={current.url}
        alt={displayName}
        className="max-w-[90vw] max-h-[80vh] object-contain rounded shadow-2xl"
        onClick={(e) => e.stopPropagation()}
        draggable={false}
      />

      {/* Next arrow */}
      {total > 1 && (
        <button
          onClick={(e) => {
            e.stopPropagation();
            onNext();
          }}
          disabled={!canGoNext}
          aria-label="Siguiente imagen"
          className="absolute right-3 top-1/2 -translate-y-1/2 rounded-full p-2 bg-black/40 text-white hover:bg-black/60 disabled:opacity-20 disabled:cursor-default transition-colors focus:outline-none focus:ring-2 focus:ring-white/50"
        >
          <ChevronRight className="h-6 w-6" />
        </button>
      )}
    </div>,
    document.body,
  );
}
