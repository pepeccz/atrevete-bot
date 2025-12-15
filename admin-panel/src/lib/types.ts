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
export type MessageRole = "user" | "assistant" | "system";

// Models
export interface Stylist {
  id: string;
  name: string;
  category: ServiceCategory;
  google_calendar_id: string;
  is_active: boolean;
  color?: string;
  metadata: Record<string, unknown>;
  created_at: string;
  updated_at: string;
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
  metadata: Record<string, unknown>;
  created_at: string;
}

export interface Service {
  id: string;
  name: string;
  category: ServiceCategory;
  duration_minutes: number;
  description: string | null;
  is_active: boolean;
  created_at: string;
  updated_at: string;
}

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
  created_at: string;
  updated_at: string;
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

export interface ConversationMessage {
  role: MessageRole;
  content: string;
  timestamp?: string;
}

export interface ConversationHistory {
  id: string;
  customer_id: string;
  started_at: string;
  ended_at: string | null;
  message_count: number;
  messages: ConversationMessage[];
  summary: string | null;
  metadata: Record<string, unknown>;
  created_at: string;
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
export interface DashboardKPIs {
  appointments_this_month: number;
  total_customers: number;
  avg_appointment_duration: number;
  total_hours_booked: number;
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
  | "confirmation-worker"
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
