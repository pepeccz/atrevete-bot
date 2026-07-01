/**
 * TypeScript types for the Atrévete Admin Panel
 * These mirror the database models from database/models.py
 */

// Enums
export type ServiceCategory = "HAIRDRESSING" | "AESTHETICS" | "BOTH";
export type AppointmentStatus =
  | "pending"
  | "confirmed"
  | "completed"
  | "cancelled"
  | "no_show";
/** Extended role set — includes human_agent added by the inbox migration (PR-1). */
export type MessageRole = "user" | "assistant" | "system" | "human_agent";

// Models
export interface Stylist {
  id: string;
  name: string;
  category: ServiceCategory;
  google_calendar_id: string | null;
  is_active: boolean;
  color?: string;
  metadata: Record<string, unknown>;
  created_at: string;
  updated_at: string;
}

// Google Calendar OAuth2 types
export interface GoogleCalendarStatus {
  connected: boolean;
  email: string | null;
  connected_at: string | null;
  token_healthy: boolean;
  scopes: string[];
}

export interface GoogleCalendar {
  id: string;
  summary: string;
  description: string;
  timeZone: string;
  primary: boolean;
  access_role: string;
  background_color: string | null;
}

export interface CreateCalendarPayload {
  summary: string;
  description?: string;
  timeZone?: string;
}

export interface UpdateCalendarPayload {
  summary?: string;
  description?: string;
}

export interface CalendarConflictError {
  message: string;
  stylist_names: string[];
}

// Calendar option classification for stylist modal
export const CALENDAR_OPTION_STATUS = {
  AVAILABLE: "available",
  CURRENT: "current",
  OCCUPIED: "occupied",
} as const;

export type CalendarOptionStatus =
  (typeof CALENDAR_OPTION_STATUS)[keyof typeof CALENDAR_OPTION_STATUS];

export interface CalendarOption {
  calendar: GoogleCalendar;
  status: CalendarOptionStatus;
  ownerStylistName?: string;
}

export interface Customer {
  id: string;
  phone: string;
  first_name: string;
  last_name: string | null;
  total_spent: string; // Decimal as string
  last_service_date: string | null;
  preferred_stylist_id: string | null;
  notes: string | null;
  chatwoot_conversation_id: string | null;
  created_at: string;
  // Policy acceptance (GDPR / cancellation policy)
  policy_accepted_at: string | null; // ISO-8601 or null
  policy_version: string | null;
}

export interface CustomerMemories {
  preferred_stylist_name?: string | null;
  preferred_stylist_id?: string | null;
  no_preference_stylist?: boolean | null;
  typical_services?: string[] | null;
  typical_day_of_week?: string | null;
  typical_time_of_day?: string | null;
  agent_notes?: string | null;
  visit_count?: number | null;
  last_visit_date?: string | null;
  last_stylist_name?: string | null;
}

export interface CustomerDetail extends Customer {
  preferred_stylist_name: string | null;
  memories: CustomerMemories | null;
}

export interface CustomerConsent {
  id: string;
  customer_id: string;
  policy_version: string;
  accepted_at: string; // ISO-8601
  accepted_via: "whatsapp" | "admin_panel";
  source_message_id: string | null;
}

export interface CustomerAppointment {
  id: string;
  start_time: string;
  duration_minutes: number;
  status: AppointmentStatus;
  stylist_name: string;
  service_names: string[];
  first_name: string;
  last_name: string | null;
  notes: string | null;
  created_at: string;
}

export interface CustomerAppointmentsPage {
  items: CustomerAppointment[];
  total: number;
  page: number;
  page_size: number;
  has_more: boolean;
}

export interface Service {
  id: string;
  name: string;
  category: ServiceCategory;
  duration_minutes: number;
  description: string | null;
  audience: string | null;
  is_active: boolean;
  metadata: Record<string, unknown> | null;
  created_at: string;
  updated_at: string;
}

/** GCal sync state for an appointment (gcal-sync-resilience). */
export type GcalSyncStatus = "synced" | "failed" | "not_applicable";
/** Which GCal operation was last attempted for a failed appointment. */
export type GcalOperation = "book" | "reschedule" | "cancel";

export interface Appointment {
  id: string;
  customer_id: string;
  stylist_id: string;
  service_ids: string[];
  start_time: string;
  duration_minutes: number;
  status: AppointmentStatus;
  google_calendar_event_id: string | null;
  first_name: string;
  last_name: string | null;
  notes: string | null;
  reminder_sent: boolean;
  confirmation_sent_at: string | null;
  reminder_sent_at: string | null;
  cancelled_at: string | null;
  cancellation_reason?: string | null;
  created_at: string;
  updated_at: string;
  // GCal sync state (gcal-sync-resilience)
  gcal_sync_status?: GcalSyncStatus;
  gcal_last_attempt_at?: string | null;
  gcal_last_error?: string | null;
  gcal_operation?: GcalOperation | null;
  // Expanded relations (optional)
  customer?: Customer;
  stylist?: Stylist;
  services?: Service[];
}

export interface Policy {
  id: string;
  key: string;
  value: Record<string, unknown>;
  description: string | null;
  created_at: string;
  updated_at: string;
}

export interface BusinessHours {
  id: string;
  day_of_week: number; // 0-6 (Monday-Sunday)
  is_closed: boolean;
  start_hour: number | null;  // nullable when closed
  start_minute: number | null; // nullable when closed
  end_hour: number | null;     // nullable when closed
  end_minute: number | null;   // nullable when closed
  created_at: string;
  updated_at: string;
}

export interface Holiday {
  id: string;
  date: string;        // ISO format: YYYY-MM-DD
  name: string;
  is_all_day: boolean;
}

/** PR-3b: Single file attachment returned by the message detail endpoint. */
export interface Attachment {
  id: string;
  file_type: string;
  url: string;
  thumb_url: string | null;
  content_type: string | null;
  filename: string | null;
  size_bytes: number | null;
  width: number | null;
  height: number | null;
  position: number;
  created_at: string;
}

export interface ConversationMessage {
  id: string;
  role: MessageRole;
  content: string;
  created_at: string;
  chatwoot_message_id: number | null;
  // Legacy field — kept for backward compatibility with archived conversations
  timestamp?: string;
  // PR-1 additive fields (may be absent on older archived rows)
  author_type?: "bot" | "human_agent" | "system" | "user" | null;
  read_at?: string | null;
  delivery_failed?: boolean;
  /** PR-3b: attachments sent with this message (images, audio, files). */
  attachments?: Attachment[];
}

/**
 * WhatsApp contact fallback shown by the inbox CustomerCard when a conversation
 * has no linked customers row yet. Populated by the inbound webhook from the
 * Chatwoot conversation.sender object.
 */
export interface WhatsappContact {
  name: string | null;
  phone: string | null;
}

export interface ConversationHistory {
  id: string;
  conversation_id: string; // thread_id string (LangGraph thread)
  customer_id: string | null;
  customer_name: string | null;
  /**
   * WhatsApp contact info captured from Chatwoot. Always present in detail
   * responses; either field may be null when no inbound has been processed yet.
   */
  whatsapp_contact?: WhatsappContact;
  started_at: string | null;
  ended_at: string | null;
  message_count: number;
  messages: ConversationMessage[];
  summary: string | null;
  metadata?: Record<string, unknown>;
  created_at: string;
}

export interface DeleteConversationResult {
  conversation_uuid: string;
  thread_id: string;
  db_deleted: boolean;
  redis_keys_deleted: number;
  redis_status: string;
  error: string | null;
}

// API Response types
export interface AvailableSlot {
  time: string;
  end_time: string;
  date: string;
  stylist: string;
  stylist_id: string;
  full_datetime: string;
}

export interface CalendarEvent {
  id: string;
  title: string;
  start: string;
  end: string;
  backgroundColor?: string;
  borderColor?: string;
  extendedProps: {
    appointment_id?: string;
    customer_name?: string;
    status?: AppointmentStatus;
    services?: string[];
  };
}

// Auth types
export interface LoginRequest {
  username: string;
  password: string;
}

export interface LoginResponse {
  access_token: string;
  token_type: string;
  expires_in: number;
}

export interface User {
  username: string;
  role: string;
}

// Dashboard types
/** @deprecated Legacy monthly-aggregate KPIs — use DashboardKPIs instead */
export interface DashboardKPIsLegacy {
  appointments_this_month: number;
  total_customers: number;
  avg_appointment_duration: number;
  total_hours_booked: number;
}

/** Today-scoped KPIs returned by GET /api/admin/dashboard/kpis (Slice 2a) */
export interface DashboardKPIs {
  // New today-scoped fields
  confirmation_rate_today: number | null;
  confirmed_today: number;
  total_today: number;
  appointments_today: number;
  occupation_today: number;
  booked_minutes_today: number;
  business_minutes_today: number;
  new_customers_this_week: number;
  // Legacy fields (deprecated, may be null)
  appointments_this_month?: number | null;
  total_customers?: number | null;
  avg_appointment_duration?: number | null;
  total_hours_booked?: number | null;
}

export interface AgendaCustomer {
  id: string;
  name: string;
  phone?: string | null;
}

export interface AgendaStylist {
  id: string;
  name: string;
  color: string;
}

export interface AgendaService {
  id: string;
  name: string;
}

export interface TodayAgendaItem {
  id: string;
  start_time: string;
  end_time: string;
  duration_minutes: number;
  status: AppointmentStatus;
  customer: AgendaCustomer;
  stylist: AgendaStylist;
  services: AgendaService[];
}

export interface TodayAgendaResponse {
  date: string;
  appointments: TodayAgendaItem[];
}

/** Top services (7-day window) */
export interface TopServiceItem {
  name: string;
  count: number;
}

/** Stylist activity for today */
export interface StylistActivityItem {
  id: string;
  name: string;
  color: string;
  appointments_today: number;
  booked_minutes_today: number;
  utilization_pct: number;
}

/** 14-day appointments trend */
export interface AppointmentTrendPoint {
  date: string;
  count: number;
}

// API pagination
export interface PaginatedResponse<T> {
  items: T[];
  total: number;
  page: number;
  page_size: number;
  has_more: boolean;
}

// Search types
export interface SearchResultItem {
  id: string;
  type: "customer" | "appointment" | "service" | "stylist";
  title: string;
  subtitle: string | null;
  url: string;
}

export interface GlobalSearchResponse {
  customers: SearchResultItem[];
  appointments: SearchResultItem[];
  services: SearchResultItem[];
  stylists: SearchResultItem[];
  total: number;
}

// Notification types
export type NotificationType =
  // Appointment lifecycle
  | "appointment_created"
  | "appointment_cancelled"
  | "appointment_confirmed"
  | "appointment_completed"
  // Confirmation system
  | "confirmation_sent"
  | "confirmation_received"
  | "auto_cancelled"
  | "confirmation_failed"
  | "reminder_sent"
  // Escalation system (human handoff)
  | "escalation_manual"
  | "escalation_technical"
  | "escalation_auto"
  | "escalation_medical"
  | "escalation_ambiguity";

export interface Notification {
  id: string;
  type: NotificationType;
  title: string;
  message: string;
  entity_type: string;
  entity_id: string | null;
  is_read: boolean;
  is_starred: boolean;
  created_at: string;
  read_at: string | null;
  starred_at: string | null;
}

export interface NotificationsListResponse {
  items: Notification[];
  unread_count: number;
  total: number;
}

// Notification categories mapping
export const NOTIFICATION_CATEGORIES = {
  citas: [
    "appointment_created",
    "appointment_cancelled",
    "appointment_confirmed",
    "appointment_completed",
  ],
  confirmaciones: [
    "confirmation_sent",
    "confirmation_received",
    "auto_cancelled",
    "confirmation_failed",
    "reminder_sent",
  ],
  escalaciones: [
    "escalation_manual",
    "escalation_technical",
    "escalation_auto",
    "escalation_medical",
    "escalation_ambiguity",
  ],
} as const;

export type NotificationCategory = keyof typeof NOTIFICATION_CATEGORIES;

// Query params for notifications list
export interface NotificationQueryParams {
  page?: number;
  page_size?: number;
  types?: NotificationType[];
  category?: NotificationCategory;
  is_read?: boolean;
  is_starred?: boolean;
  date_from?: string;
  date_to?: string;
  search?: string;
  sort_by?: "created_at" | "type";
  sort_order?: "asc" | "desc";
}

// Stats response for charts
export interface NotificationStatsResponse {
  by_type: Record<string, number>;
  by_category: Record<string, number>;
  trend: Array<{ date: string; count: number }>;
  total: number;
  unread: number;
  starred: number;
}

// Paginated response
export interface NotificationsPaginatedResponse {
  items: Notification[];
  total: number;
  page: number;
  page_size: number;
  has_more: boolean;
  unread_count: number;
  starred_count: number;
}

// Category display names for UI
export const NOTIFICATION_CATEGORY_LABELS: Record<NotificationCategory, string> = {
  citas: "Citas",
  confirmaciones: "Confirmaciones",
  escalaciones: "Escalaciones",
};

// Type display names for UI
export const NOTIFICATION_TYPE_LABELS: Record<NotificationType, string> = {
  appointment_created: "Cita creada",
  appointment_cancelled: "Cita cancelada",
  appointment_confirmed: "Cita confirmada",
  appointment_completed: "Cita completada",
  confirmation_sent: "Confirmación enviada",
  confirmation_received: "Confirmación recibida",
  auto_cancelled: "Auto-cancelada",
  confirmation_failed: "Confirmación fallida",
  reminder_sent: "Recordatorio enviado",
  escalation_manual: "Escalación manual",
  escalation_technical: "Escalación técnica",
  escalation_auto: "Escalación automática",
  escalation_medical: "Escalación médica",
  escalation_ambiguity: "Escalación por ambigüedad",
};

// System Settings types
export type SettingValueType = "string" | "int" | "float" | "boolean" | "enum";

export type SettingCategory =
  | "ai_control"
  | "confirmation"
  | "booking"
  | "llm"
  | "rate_limiting"
  | "cache"
  | "archival"
  | "gcal_sync";

export interface SystemSetting {
  id: string;
  key: string;
  value: string | number | boolean;
  value_type: SettingValueType;
  default_value: string | number | boolean;
  min_value: number | null;
  max_value: number | null;
  allowed_values: string[] | null;
  label: string;
  description: string | null;
  requires_restart: boolean;
  display_order: number;
  updated_at: string | null;
  updated_by: string | null;
}

export interface SystemSettingsResponse {
  categories: Record<SettingCategory, SystemSetting[]>;
}

export interface SettingsHistoryEntry {
  id: string;
  setting_key: string;
  previous_value: string | number | boolean | null;
  new_value: string | number | boolean;
  changed_by: string;
  change_reason: string | null;
  changed_at: string;
}

export interface SettingsHistoryResponse {
  entries: SettingsHistoryEntry[];
  total: number;
}

// System Management types
export type SystemServiceName =
  | "api"
  | "agent"
  | "archiver"
  | "gcal-sync-worker"
  | "postgres"
  | "redis";

export interface SystemService {
  name: SystemServiceName;
  container: string;
  status: string; // running, exited, paused, etc.
  health: string | null; // healthy, unhealthy, starting, null
}

export interface SystemServicesResponse {
  services: SystemService[];
}

export interface ServiceActionResponse {
  success: boolean;
  message: string;
}

// Overlap Check types for appointment creation
export interface OverlapConflict {
  appointment_id: string;
  customer_name: string;
  service_names: string;
  start_time: string;
  end_time: string;
  status: string;
}

export interface OverlapCheckResponse {
  has_overlaps: boolean;
  conflicts: OverlapConflict[];
  checked_range: {
    start_time: string;
    end_time: string;
    duration_minutes: number;
  };
}

// Token Usage types
export interface TokenUsage {
  id: string;
  year: number;
  month: number;
  input_tokens: number;
  output_tokens: number;
  total_tokens: number;
  total_requests: number;
  cost_input_eur: number;
  cost_output_eur: number;
  cost_total_eur: number;
  created_at: string;
  updated_at: string;
}

export interface TokenUsageList {
  items: TokenUsage[];
  total: number;
}

export interface CurrentMonthUsage {
  year: number;
  month: number;
  input_tokens: number;
  output_tokens: number;
  total_tokens: number;
  total_requests: number;
  cost_input_eur: number;
  cost_output_eur: number;
  cost_total_eur: number;
}

export interface TokenPricing {
  input_price_per_million: number;
  output_price_per_million: number;
}

// ─── Billing & Invoicing ─────────────────────────────────────────────────────

export type InvoiceStatus = "draft" | "issued" | "paid" | "overdue" | "void";
export type PaymentStatus = "pending" | "processing" | "succeeded" | "failed" | "refunded";

export interface InvoiceResponse {
  id: string;
  invoice_number: string;
  year: number;
  month: number;
  period_label: string;
  maintenance_amount_eur: string;
  token_amount_eur: string;
  total_amount_eur: string;
  status: InvoiceStatus;
  issued_at: string | null;
  paid_at: string | null;
  due_date: string;
  has_pdf: boolean;
  stripe_payment_intent_id: string | null;
  stripe_invoice_id: string | null;
  invoice_pdf_url: string | null;
  subtotal_eur: string | null;
  tax_rate_pct: string | null;
  tax_amount_eur: string | null;
  gross_amount_eur: string | null;
  notes: string | null;
  payments: PaymentSummary[];
  created_at: string;
  updated_at: string;
}

export interface PaymentSummary {
  id: string;
  stripe_payment_intent_id: string;
  amount_eur: string;
  status: PaymentStatus;
  payment_method: string;
  failure_reason: string | null;
  created_at: string;
}

export interface InvoiceListResponse {
  invoices: InvoiceResponse[];
  total: number;
  page: number;
  page_size: number;
}

export interface CurrentEstimateResponse {
  year: number;
  month: number;
  period_label: string;
  estimate_date: string;
  next_invoice_date: string;
  maintenance_amount_eur: string;
  token_amount_eur: string;
  total_amount_eur: string;
  subtotal_eur: string;
  tax_amount_eur: string;
  gross_amount_eur: string;
  input_tokens: number;
  output_tokens: number;
  total_requests: number;
}

export interface StripeStatusResponse {
  configured: boolean;
  customer_id: string | null;
  payment_method_last4: string | null;
  payment_method_status: string | null;
  sepa_mandate_status: string | null;
}

export interface SetupSessionResponse {
  checkout_url: string;
  session_id: string;
}

// ─── Escalations ────────────────────────────────────────────────────────────

export type EscalationSource = "manual" | "auto_error" | "fallback";
export type EscalationStatus = "triggered" | "resolved";

export interface Escalation {
  id: string;
  conversation_id: string;
  customer_id: string | null;
  customer_name: string | null;
  customer_phone: string;
  reason: string;
  source: EscalationSource;
  status: EscalationStatus;
  is_technical_error: boolean;
  issue_summary: string | null;
  contact_preference: string | null;
  triggered_at: string;
  resolved_at: string | null;
  metadata: Record<string, unknown> | null;
}

export interface EscalationQueryParams {
  page?: number;
  page_size?: number;
  status?: EscalationStatus | "";
  source?: EscalationSource | "";
  is_technical_error?: boolean;
  date_from?: string;
  date_to?: string;
  search?: string;
  sort_by?: "triggered_at" | "status" | "source";
  sort_order?: "asc" | "desc";
}

export interface EscalationStats {
  total: number;
  pending: number;
  resolved: number;
  by_source: Record<EscalationSource, number>;
  technical_errors: number;
}

export const ESCALATION_SOURCE_LABELS: Record<EscalationSource, string> = {
  manual: "Manual",
  auto_error: "Error automático",
  fallback: "Fallback",
};

export const ESCALATION_STATUS_LABELS: Record<EscalationStatus, string> = {
  triggered: "Pendiente",
  resolved: "Resuelta",
};

export const ESCALATION_SOURCE_COLORS: Record<EscalationSource, string> = {
  manual: "text-orange-500",
  auto_error: "text-red-600",
  fallback: "text-purple-500",
};

// ─── Admin Users ─────────────────────────────────────────────────────────────

export type AdminUserRole = "admin" | "stylist";

export interface AdminUser {
  id: string;
  username: string;
  role: AdminUserRole;
  is_active: boolean;
  display_name: string | null;
  last_login_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface AdminUserListResponse {
  items: AdminUser[];
  total: number;
  limit: number;
  offset: number;
}

export interface AdminUserCreateRequest {
  username: string;
  password: string;
  role: AdminUserRole;
  display_name?: string | null;
}

export interface AdminUserUpdateRequest {
  role?: AdminUserRole | null;
  is_active?: boolean | null;
  display_name?: string | null;
}

// ─── Inbox (conversaciones-inbox) ────────────────────────────────────────────

/** Extended ConversationHistory fields added by the inbox migration (PR-1). */
export interface ConversationHistoryInbox extends ConversationHistory {
  paused_at: string | null;
  resumed_at: string | null;
  context_injected_at: string | null;
  /** Whether the bot is currently active for this conversation. */
  atencion_automatica: boolean | null;
  /** Filter label returned by the listing endpoint ?filter= param. */
  filter_label?: string;
  /**
   * PR-1: count of unread customer messages (read_at IS NULL AND author_type='user').
   * Optional — absent on older archived rows or when migration not yet applied.
   */
  unread_message_count?: number | null;
  /**
   * R1: True when an Escalation row with status='triggered' exists for this conversation.
   * More accurate than the paused_at proxy (which also catches manual takeovers).
   */
  is_escalated?: boolean;
  /** R3a: escalation reason from the triggered Escalation row. */
  escalation_reason?: string | null;
  /** R3a: escalation source (manual, safety, cancellation_window_exception, etc). */
  escalation_source?: string | null;
  /** R3a: ISO timestamp when the escalation was triggered. */
  escalation_triggered_at?: string | null;
}

export type InboxFilter = "all" | "bot_on" | "bot_off" | "escalated" | "unread";

// ─── Conversation notes (PR-2) ────────────────────────────────────────────────

export interface ConversationNote {
  id: string;
  content: string;
  author_user_id: string | null;
  author_name: string;
  created_at: string;
  updated_at: string;
}

export interface NoteListResponse {
  items: ConversationNote[];
}

// ─── Sidebar aggregate (PR-2) ─────────────────────────────────────────────────

export interface SidebarCustomer {
  id: string;
  name: string;
  phone: string;
  customer_notes_count: number;
}

export interface SidebarEscalation {
  id: string;
  reason: string;
  triggered_at: string;
}

export interface SidebarResponse {
  customer: SidebarCustomer | null;
  notes: ConversationNote[];
  active_escalation: SidebarEscalation | null;
}

// Inbox API request/response shapes (mirrors api/models/inbox.py from PR-2).

export interface InboxMessageResponse {
  id: string;
  content: string;
  created_at: string;
  author_username: string | null;
}

export interface InboxPauseResponse {
  paused_at: string;
  escalation_id?: string | null;
}

export interface InboxResumeResponse {
  resumed_at: string;
  pending_injection_ttl_seconds: number;
}

export interface InboxEscalationResponse {
  escalation_id: string;
}

export interface InboxWindowStatusResponse {
  window_open: boolean;
  last_user_message_at: string | null;
  hours_until_close: number | null;
}

export interface InboxTemplateParamDef {
  name: string;
  label: string;
}

export interface InboxTemplateDef {
  name: string;
  /** Human-readable label returned by the API. Falls back to `name` when absent. */
  display_name?: string;
  status: "approved" | "pending";
  params: InboxTemplateParamDef[];
}

export interface InboxTemplateListResponse {
  items: InboxTemplateDef[];
}
