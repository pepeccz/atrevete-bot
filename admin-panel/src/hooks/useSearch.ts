/**
 * useSearch — debounced conversation search with AbortController.
 *
 * Debounces the search term by 250 ms before firing the API request.
 * Cancels in-flight requests when the term changes (AbortController).
 *
 * Returns `results`, `loading`, and `error`.
 *
 * PR-2, REQ-6.
 */

"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useDebounce } from "@/hooks/use-debounce";
import api from "@/lib/api";

interface SearchResult {
  // Matches the conversation list item shape from GET /api/admin/conversations
  [key: string]: unknown;
}

interface UseSearchResult {
  results: SearchResult[];
  loading: boolean;
  error: string | null;
  /** Clear the results and reset loading/error state. */
  clear: () => void;
}

/**
 * @param query  Raw search term from the user (not debounced yet)
 */
export function useSearch(query: string): UseSearchResult {
  const [results, setResults] = useState<SearchResult[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const debouncedQuery = useDebounce(query.trim(), 250);
  const abortRef = useRef<AbortController | null>(null);

  const clear = useCallback(() => {
    setResults([]);
    setLoading(false);
    setError(null);
  }, []);

  useEffect(() => {
    if (!debouncedQuery) {
      clear();
      return;
    }

    // Cancel any in-flight request
    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;

    setLoading(true);
    setError(null);

    api
      .searchConversations(debouncedQuery)
      .then((resp) => {
        if (controller.signal.aborted) return;
        setResults((resp.items as SearchResult[]) ?? []);
      })
      .catch((err) => {
        if (controller.signal.aborted) return;
        if (err?.name === "AbortError") return;
        setError(err?.message ?? "Error al buscar conversaciones.");
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });

    return () => {
      controller.abort();
    };
  }, [debouncedQuery, clear]);

  return { results, loading, error, clear };
}
