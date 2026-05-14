/**
 * useNotes — CRUD hook for operator conversation notes.
 *
 * Provides optimistic updates: notes are added/removed from local state
 * immediately and rolled back on API error.
 *
 * PR-2, REQ-4.
 */

import { useCallback, useEffect, useState } from "react";
import api from "@/lib/api";
import type { ConversationNote } from "@/lib/types";

interface UseNotesResult {
  notes: ConversationNote[];
  loading: boolean;
  error: string | null;
  addNote: (content: string) => Promise<void>;
  editNote: (noteId: string, content: string) => Promise<void>;
  removeNote: (noteId: string) => Promise<void>;
  reload: () => void;
}

export function useNotes(conversationId: string | null): UseNotesResult {
  const [notes, setNotes] = useState<ConversationNote[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [version, setVersion] = useState(0);

  const reload = useCallback(() => setVersion((v) => v + 1), []);

  // ── Load notes ────────────────────────────────────────────────────────────
  useEffect(() => {
    if (!conversationId) {
      setNotes([]);
      return;
    }
    let cancelled = false;
    setLoading(true);
    setError(null);

    api
      .listNotes(conversationId)
      .then((resp) => {
        if (cancelled) return;
        setNotes(resp.items);
      })
      .catch((err) => {
        if (cancelled) return;
        setError(err?.message ?? "Error al cargar notas.");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, [conversationId, version]);

  // ── Add note (optimistic) ─────────────────────────────────────────────────
  const addNote = useCallback(
    async (content: string) => {
      if (!conversationId) return;

      // Optimistic placeholder
      const placeholder: ConversationNote = {
        id: `optimistic-${Date.now()}`,
        content,
        author_user_id: null,
        author_name: "...",
        created_at: new Date().toISOString(),
        updated_at: new Date().toISOString(),
      };
      setNotes((prev) => [placeholder, ...prev]);

      try {
        const created = await api.createNote(conversationId, content);
        // Replace placeholder with real note
        setNotes((prev) =>
          prev.map((n) => (n.id === placeholder.id ? created : n))
        );
      } catch (err) {
        // Roll back
        setNotes((prev) => prev.filter((n) => n.id !== placeholder.id));
        throw err;
      }
    },
    [conversationId]
  );

  // ── Edit note (optimistic) ────────────────────────────────────────────────
  const editNote = useCallback(async (noteId: string, content: string) => {
    const previous = notes.find((n) => n.id === noteId);
    if (!previous) return;

    // Optimistic update
    setNotes((prev) =>
      prev.map((n) =>
        n.id === noteId
          ? { ...n, content, updated_at: new Date().toISOString() }
          : n
      )
    );

    try {
      const updated = await api.updateNote(noteId, content);
      setNotes((prev) => prev.map((n) => (n.id === noteId ? updated : n)));
    } catch (err) {
      // Roll back
      setNotes((prev) => prev.map((n) => (n.id === noteId ? previous : n)));
      throw err;
    }
  }, [notes]);

  // ── Remove note (optimistic) ──────────────────────────────────────────────
  const removeNote = useCallback(async (noteId: string) => {
    const snapshot = notes;
    setNotes((prev) => prev.filter((n) => n.id !== noteId));

    try {
      await api.deleteNote(noteId);
    } catch (err) {
      // Roll back
      setNotes(snapshot);
      throw err;
    }
  }, [notes]);

  return { notes, loading, error, addNote, editNote, removeNote, reload };
}
