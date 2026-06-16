/**
 * category-labels.ts
 * Shared label maps for human-readable display of internal enum/code values.
 * Pure module — no React, no fetch, no side effects.
 */

/**
 * Returns the mapped label for a raw internal value.
 * - Unknown keys: returns the raw value as-is (never blank).
 * - null / undefined / empty string: returns "—".
 */
function labelFrom(
  map: Readonly<Record<string, string>>,
  raw: string | null | undefined
): string {
  if (raw == null || raw === "") return "—";
  return map[raw] ?? raw;
}

// ---------------------------------------------------------------------------
// Service / stylist category
// ---------------------------------------------------------------------------

export const CATEGORY_LABELS = {
  HAIRDRESSING: "Peluquería",
  AESTHETICS: "Estética",
  BOTH: "Mixto",
  __null__: "Sin categoría",
} as const;

export const formatCategory = (v?: string | null): string =>
  labelFrom(CATEGORY_LABELS, v);

// ---------------------------------------------------------------------------
// Appointment status
// ---------------------------------------------------------------------------

export const APPOINTMENT_STATUS_LABELS = {
  pending: "Pendiente",
  confirmed: "Confirmada",
  completed: "Completada",
  cancelled: "Cancelada",
  no_show: "No asistió",
} as const;

export const formatAppointmentStatus = (v?: string | null): string =>
  labelFrom(APPOINTMENT_STATUS_LABELS, v);

// ---------------------------------------------------------------------------
// Escalation reason
// ---------------------------------------------------------------------------

export const ESCALATION_REASON_LABELS = {
  manual_request: "Solicitud manual",
  cancellation_window_exception: "Excepción de cancelación",
  medical_consultation: "Consulta médica",
  ambiguity: "Mensaje ambiguo",
  technical_error: "Error técnico",
  auto_escalation: "Escalación automática",
  policy_rejection: "Rechazo de política",
} as const;

export const formatEscalationReason = (v?: string | null): string =>
  labelFrom(ESCALATION_REASON_LABELS, v);

// ---------------------------------------------------------------------------
// Google Calendar access role
// ---------------------------------------------------------------------------

export const ACCESS_ROLE_LABELS = {
  owner: "Propietario",
  writer: "Editor",
  reader: "Lectura",
  freeBusyReader: "Solo disponibilidad",
} as const;

export const formatAccessRole = (v?: string | null): string =>
  labelFrom(ACCESS_ROLE_LABELS, v);

// ---------------------------------------------------------------------------
// OAuth scope URLs
// ---------------------------------------------------------------------------

const SCOPE_LABELS: Record<string, string> = {
  "https://www.googleapis.com/auth/calendar": "Acceso al calendario",
  "https://www.googleapis.com/auth/calendar.events": "Eventos del calendario",
};

/** Returns a short human-readable label for a Google OAuth scope URL. */
export const formatScope = (v?: string | null): string => {
  if (v == null || v === "") return "—";
  if (SCOPE_LABELS[v]) return SCOPE_LABELS[v];
  // Fallback: last path segment of the URL
  const parts = v.split("/");
  return parts[parts.length - 1] || v;
};

// ---------------------------------------------------------------------------
// LLM model identifiers
// ---------------------------------------------------------------------------

const MODEL_LABELS: Record<string, string> = {
  "openai/gpt-5.4-mini": "GPT-5.4 mini (OpenRouter)",
  "openai/gpt-4o-mini": "GPT-4o mini (OpenRouter)",
  "openai/gpt-4o": "GPT-4o (OpenRouter)",
};

/** Returns a human-readable label for an LLM model identifier. */
export const formatModel = (v?: string | null): string =>
  labelFrom(MODEL_LABELS, v);
