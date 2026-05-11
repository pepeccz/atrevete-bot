/**
 * API Client for Atrévete Admin Panel
 * Handles all HTTP requests to FastAPI backend
 */

import type {
  GlobalSearchResponse,
  NotificationsListResponse,
  NotificationsPaginatedResponse,
  NotificationQueryParams,
  NotificationStatsResponse,
  SystemSetting,
  SystemSettingsResponse,
  SettingsHistoryResponse,
  SystemServicesResponse,
  ServiceActionResponse,
  SystemServiceName,
  DeleteConversationResult,
  GoogleCalendarStatus,
  GoogleCalendar,
  CreateCalendarPayload,
  UpdateCalendarPayload,
  OverlapCheckResponse,
  TokenUsageList,
  CurrentMonthUsage,
  TokenPricing,
  Escalation,
  EscalationQueryParams,
  EscalationStats,
  CustomerDetail,
  CustomerAppointmentsPage,
  CustomerMemories,
  AdminUser,
  AdminUserListResponse,
  AdminUserCreateRequest,
  AdminUserUpdateRequest,
} from "./types";

const API_BASE_URL =
  process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

interface ApiError {
  error?: string;
  detail?: string | { message?: string; stylist_names?: string[] } | unknown;
  details?: unknown;
}

export class ApiRequestError extends Error {
  status: number;
  detail: unknown;
  stylistNames?: string[];

  constructor(message: string, status: number, detail?: unknown, stylistNames?: string[]) {
    super(message);
    this.name = "ApiRequestError";
    this.status = status;
    this.detail = detail;
    this.stylistNames = stylistNames;
  }
}

class ApiClient {
  private baseUrl: string;

  constructor(baseUrl: string) {
    this.baseUrl = baseUrl;
  }

  private async request<T>(
    endpoint: string,
    options: RequestInit = {}
  ): Promise<T> {
    const url = `${this.baseUrl}${endpoint}`;

    const headers: HeadersInit = {
      "Content-Type": "application/json",
      ...options.headers,
    };

    // Authentication is exclusively via HttpOnly cookie (admin_token).
    // The browser attaches it automatically thanks to credentials:"include".
    // No Authorization header is ever set by the client.

    const response = await fetch(url, {
      ...options,
      headers,
      credentials: "include",
    });

    if (!response.ok) {
      if (response.status === 401) {
        if (typeof window !== "undefined") {
          // Guardar URL actual para volver después del login
          const currentPath = window.location.pathname + window.location.search;
          if (currentPath !== "/login") {
            sessionStorage.setItem("returnTo", currentPath);
            window.location.href = "/login";
          }
          // If already on /login, do NOT redirect again — a stale cookie
          // would otherwise cause an infinite reload loop (getMe 401 → reload
          // → mount AuthProvider → getMe 401 → reload …). The login page
          // tolerates the 401 and renders the form.
        }
      }

      const errorBody: ApiError = await response.json().catch(() => ({
        error: `HTTP ${response.status}: ${response.statusText}`,
      }));

      // FastAPI returns { detail: string } or { detail: { message, stylist_names } }
      // Legacy format: { error: string, details?: unknown }
      let errorMessage = "Unknown error";
      let stylistNames: string[] | undefined;

      if (typeof errorBody.detail === "string") {
        errorMessage = errorBody.detail;
      } else if (
        errorBody.detail !== null &&
        typeof errorBody.detail === "object" &&
        "message" in (errorBody.detail as object)
      ) {
        const detailObj = errorBody.detail as { message?: string; stylist_names?: string[] };
        errorMessage = detailObj.message ?? "Unknown error";
        if (detailObj.stylist_names?.length) {
          stylistNames = detailObj.stylist_names;
          errorMessage = `${errorMessage}: ${detailObj.stylist_names.join(", ")}`;
        }
      } else if (errorBody.error) {
        errorMessage = errorBody.error;
      }

      throw new ApiRequestError(
        errorMessage,
        response.status,
        errorBody.detail ?? errorBody.details,
        stylistNames
      );
    }

    // Handle empty responses (204 No Content from DELETE endpoints)
    if (response.status === 204 || response.headers.get('content-length') === '0') {
      return undefined as T;
    }
    return response.json();
  }

  // Auth endpoints
  async login(
    username: string,
    password: string
  ): Promise<{ username: string; expires_in: number }> {
    // Server sets the admin_token HttpOnly cookie in the Set-Cookie header.
    // Response body contains only non-sensitive metadata (no access_token).
    return this.request<{ username: string; expires_in: number }>(
      "/api/admin/auth/login",
      {
        method: "POST",
        body: JSON.stringify({ username, password }),
      }
    );
  }

  async logout(): Promise<void> {
    // Server invalidates the JWT (Redis blacklist) and clears the cookie.
    try {
      await this.request("/api/admin/auth/logout", { method: "POST" });
    } catch (error) {
      // Ignore errors - cookie will expire naturally
      console.warn("Server logout failed:", error);
    }
  }

  async getMe(): Promise<{ id: string; username: string; role: string; display_name?: string | null }> {
    return this.request("/api/admin/auth/me");
  }

  // Dashboard endpoints
  async getDashboardKPIs(): Promise<import("./types").DashboardKPIs> {
    return this.request("/api/admin/dashboard/kpis");
  }

  async getTodayAgenda(): Promise<import("./types").TodayAgendaResponse> {
    return this.request("/api/admin/dashboard/today-agenda");
  }

  async getAppointmentsTrend(
    days: number = 14
  ): Promise<Array<import("./types").AppointmentTrendPoint>> {
    return this.request(`/api/admin/dashboard/charts/appointments-trend?days=${days}`);
  }

  async getTopServices(
    limit: number = 10
  ): Promise<Array<import("./types").TopServiceItem>> {
    // Uses 7-day window per redesign spec
    return this.request(`/api/admin/dashboard/charts/top-services?limit=${limit}`);
  }

  /** @deprecated Not used in redesigned dashboard */
  async getHoursWorked(
    months: number = 12
  ): Promise<Array<{ month: string; hours: number }>> {
    return this.request(`/api/admin/dashboard/charts/hours-worked?months=${months}`);
  }

  /** @deprecated Not used in redesigned dashboard */
  async getCustomerGrowth(
    months: number = 12
  ): Promise<Array<{ month: string; count: number }>> {
    return this.request(`/api/admin/dashboard/charts/customer-growth?months=${months}`);
  }

  /** @deprecated Not used in redesigned dashboard */
  async getStylistPerformance(): Promise<
    Array<{ name: string; appointments: number; hours: number }>
  > {
    return this.request("/api/admin/dashboard/charts/stylist-performance");
  }

  /**
   * Stylist activity — endpoint not yet implemented in backend.
   * Returns empty array as placeholder. TODO: wire when backend endpoint ships.
   */
  async getStylistActivity(): Promise<Array<import("./types").StylistActivityItem>> {
    // GAP: GET /api/admin/dashboard/stylist-activity does not exist yet.
    // Returns empty array so the frontend renders gracefully.
    return Promise.resolve([]);
  }

  // Generic CRUD methods
  async list<T>(
    resource: string,
    params?: Record<string, string | number | boolean>
  ): Promise<{ items: T[]; total: number; has_more: boolean }> {
    const searchParams = new URLSearchParams();
    if (params) {
      Object.entries(params).forEach(([key, value]) => {
        searchParams.append(key, String(value));
      });
    }
    const query = searchParams.toString();
    return this.request(`/api/admin/${resource}${query ? `?${query}` : ""}`);
  }

  async get<T>(resource: string, id: string): Promise<T> {
    return this.request(`/api/admin/${resource}/${id}`);
  }

  async create<T>(resource: string, data: Partial<T>): Promise<T> {
    return this.request(`/api/admin/${resource}`, {
      method: "POST",
      body: JSON.stringify(data),
    });
  }

  async update<T>(resource: string, id: string, data: Partial<T>): Promise<T> {
    return this.request(`/api/admin/${resource}/${id}`, {
      method: "PUT",
      body: JSON.stringify(data),
    });
  }

  async delete(resource: string, id: string): Promise<void> {
    await this.request(`/api/admin/${resource}/${id}`, {
      method: "DELETE",
    });
  }

  // Conversations endpoints
  async getConversation(conversationUuid: string): Promise<import("./types").ConversationHistory> {
    return this.request(`/api/admin/conversations/${conversationUuid}`);
  }

  async deleteConversation(conversationUuid: string): Promise<DeleteConversationResult> {
    return this.request<DeleteConversationResult>(
      `/api/admin/conversations/${conversationUuid}`,
      { method: "DELETE" }
    );
  }

  // Calendar endpoints
  async getCalendarAppointments(
    stylistId: string | null,
    start: string,
    end: string
  ): Promise<
    Array<{
      id: string;
      title: string;
      start: string;
      end: string;
      backgroundColor: string;
      borderColor: string;
      extendedProps: {
        appointment_id: string;
        customer_id: string;
        stylist_id: string;
        status: string;
        duration_minutes: number;
        notes: string | null;
      };
    }>
  > {
    const params = new URLSearchParams({ start, end });
    if (stylistId) params.append("stylist_id", stylistId);
    return this.request(`/api/admin/calendar/appointments?${params}`);
  }

  // New DB-first calendar events endpoint (multi-stylist support)
  async getCalendarEvents(
    stylistIds: string[],
    start: string,
    end: string,
    signal?: AbortSignal
  ): Promise<{
    events: Array<{
      id: string;
      title: string;
      start: string;
      end: string;
      backgroundColor: string;
      borderColor: string;
      extendedProps: {
        appointment_id?: string;
        blocking_event_id?: string;
        holiday_id?: string;
        customer_id?: string;
        stylist_id?: string;
        status?: string;
        duration_minutes?: number;
        notes?: string | null;
        description?: string | null;
        event_type?: string;
        type: "appointment" | "blocking_event" | "holiday";
        customer_name?: string;
        service_names?: string[];
      };
    }>;
    stylist_colors: Record<string, string>;
    total: number;
  }> {
    const params = new URLSearchParams({ start, end });
    if (stylistIds.length > 0) {
      params.append("stylist_ids", stylistIds.join(","));
    }
    return this.request(`/api/admin/calendar/events?${params}`, { signal });
  }

  // Admin availability search with date range and optional stylist filter
  async searchAvailability(
    serviceIds: string[],
    startDate: string,
    endDate: string,
    stylistId?: string | null
  ): Promise<{
    start_date: string;
    end_date: string;
    total_duration_minutes: number;
    service_category: string | null;
    days: Array<{
      date: string;
      day_name: string;
      is_closed: boolean;
      holiday: string | null;
      stylists: Array<{
        id: string;
        name: string;
        category: string;
        slots: Array<{
          time: string;
          end_time: string;
          full_datetime: string;
          stylist_id: string;
        }>;
      }>;
    }>;
    message?: string;
  }> {
    const body: Record<string, unknown> = {
      service_ids: serviceIds,
      start_date: startDate,
      end_date: endDate,
    };
    if (stylistId) {
      body.stylist_id = stylistId;
    }
    return this.request("/api/admin/availability/search", {
      method: "POST",
      body: JSON.stringify(body),
    });
  }

  // Single appointment endpoints
  async getAppointment(id: string): Promise<{
    id: string;
    customer_id: string;
    stylist_id: string;
    start_time: string;
    duration_minutes: number;
    status: string;
    first_name: string;
    last_name: string | null;
    notes: string | null;
    services: Array<{
      id: string;
      name: string;
      category: string;
      duration_minutes: number;
    }>;
    customer: {
      id: string;
      phone: string;
      first_name: string | null;
      last_name: string | null;
    };
    stylist: {
      id: string;
      name: string;
      category: string;
    };
    created_at: string;
    updated_at: string;
  }> {
    return this.request(`/api/admin/appointments/${id}`);
  }

  async getPendingActions(): Promise<{
    items: Array<{
      id: string;
      first_name: string;
      last_name: string | null;
      start_time: string;
      duration_minutes: number;
      status: string;
      stylist?: { id: string; name: string } | null;
      services?: Array<{ id: string; name: string }>;
    }>;
    total: number;
  }> {
    return this.request("/api/admin/appointments/pending-actions");
  }

  async updateAppointment(
    id: string,
    data: {
      stylist_id?: string;
      start_time?: string;
      duration_minutes?: number;
      status?: string;
      first_name?: string;
      last_name?: string;
      notes?: string;
      service_ids?: string[];
    }
  ): Promise<{
    id: string;
    customer_id: string;
    stylist_id: string;
    start_time: string;
    duration_minutes: number;
    status: string;
    first_name: string;
    last_name: string | null;
    notes: string | null;
    created_at: string;
    updated_at: string;
  }> {
    return this.request(`/api/admin/appointments/${id}`, {
      method: "PUT",
      body: JSON.stringify(data),
    });
  }

  async checkOverlaps(
    stylistId: string,
    startTime: string,
    durationMinutes: number,
    excludeAppointmentId?: string
  ): Promise<OverlapCheckResponse> {
    const params = new URLSearchParams({
      stylist_id: stylistId,
      start_time: startTime,
      duration_minutes: durationMinutes.toString(),
    });
    if (excludeAppointmentId) {
      params.set("exclude_appointment_id", excludeAppointmentId);
    }
    return this.request(`/api/admin/appointments/check-overlaps?${params}`);
  }

  // Blocking Events endpoints
  async getBlockingEvents(
    stylistId?: string,
    start?: string,
    end?: string
  ): Promise<{
    items: Array<{
      id: string;
      stylist_id: string;
      title: string;
      description: string | null;
      start_time: string;
      end_time: string;
      event_type: string;
      google_calendar_event_id: string | null;
      created_at: string;
    }>;
    total: number;
  }> {
    const params = new URLSearchParams();
    if (stylistId) params.append("stylist_id", stylistId);
    if (start) params.append("start", start);
    if (end) params.append("end", end);
    const query = params.toString();
    return this.request(`/api/admin/blocking-events${query ? `?${query}` : ""}`);
  }

  async createBlockingEvent(
    data: {
      stylist_ids: string[];  // One or more stylists
      title: string;
      description?: string;
      start_time: string;
      end_time: string;
      event_type: string;
    },
    options?: { ignoreConflicts?: boolean }
  ): Promise<{
    created: number;
    events: Array<{
      id: string;
      stylist_id: string;
      title: string;
      description: string | null;
      start_time: string;
      end_time: string;
      event_type: string;
      created_at: string;
    }>;
  }> {
    const qs = options?.ignoreConflicts ? "?ignore_conflicts=true" : "";
    return this.request(`/api/admin/blocking-events${qs}`, {
      method: "POST",
      body: JSON.stringify(data),
    });
  }

  async deleteBlockingEvent(id: string): Promise<void> {
    await this.request(`/api/admin/blocking-events/${id}`, {
      method: "DELETE",
    });
  }

  async updateBlockingEvent(
    id: string,
    data: {
      title?: string;
      description?: string;
      start_time?: string;
      end_time?: string;
      event_type?: string;
    }
  ): Promise<{
    id: string;
    stylist_id: string;
    title: string;
    description: string | null;
    start_time: string;
    end_time: string;
    event_type: string;
    created_at: string;
  }> {
    return this.request(`/api/admin/blocking-events/${id}`, {
      method: "PUT",
      body: JSON.stringify(data),
    });
  }

  // Recurring Blocking Events

  async previewRecurringBlockingEvent(data: {
    stylist_ids: string[];
    title: string;
    description?: string;
    event_type: string;
    start_date: string;
    start_time: string;
    end_time: string;
    recurrence: {
      frequency: "WEEKLY" | "MONTHLY";
      interval: number;
      days_of_week?: number[];
      days_of_month?: number[];
      count: number;
    };
  }): Promise<{
    total_instances: number;
    dates: string[];
    conflicts: Array<{
      date: string;
      stylist_id: string;
      stylist_name: string;
      conflict_type: string;
      conflict_title: string;
      start_time: string;
      end_time: string;
    }>;
    instances_with_conflicts: number;
  }> {
    return this.request("/api/admin/blocking-events/recurring/preview", {
      method: "POST",
      body: JSON.stringify(data),
    });
  }

  async createRecurringBlockingEvent(
    data: {
      stylist_ids: string[];
      title: string;
      description?: string;
      event_type: string;
      start_date: string;
      start_time: string;
      end_time: string;
      recurrence: {
        frequency: "WEEKLY" | "MONTHLY";
        interval: number;
        days_of_week?: number[];
        days_of_month?: number[];
        count: number;
      };
    },
    ignoreConflicts: boolean = false
  ): Promise<{
    created_series: number;
    created_events: number;
    series: Array<{ series_id: string; stylist_id: string }>;
    events: Array<{
      id: string;
      stylist_id: string;
      title: string;
      start_time: string;
      end_time: string;
      event_type: string;
      series_id: string;
      occurrence_index: number;
    }>;
  }> {
    return this.request(`/api/admin/blocking-events/recurring?ignore_conflicts=${ignoreConflicts}`, {
      method: "POST",
      body: JSON.stringify(data),
    });
  }

  async getBlockingEventSeries(eventId: string): Promise<{
    series_id: string;
    total_instances: number;
    instance_index: number;
    remaining_instances: number;
    frequency: string;
    interval: number;
    days: string | null;
  } | null> {
    return this.request(`/api/admin/blocking-events/${eventId}/series`);
  }

  async deleteBlockingEventWithScope(
    eventId: string,
    scope: "this_only" | "this_and_future" | "all" = "this_only"
  ): Promise<void> {
    await this.request(`/api/admin/blocking-events/${eventId}/series?scope=${scope}`, {
      method: "DELETE",
    });
  }

  async checkSeriesExceptions(
    eventId: string,
    scope: "this_and_future" | "all"
  ): Promise<{
    has_exceptions: boolean;
    exception_count: number;
    exceptions: Array<{
      id: string;
      title: string;
      start_time: string;
      occurrence_index: number;
    }>;
  }> {
    return this.request(`/api/admin/blocking-events/${eventId}/series/exceptions?scope=${scope}`);
  }

  async updateBlockingEventWithScope(
    eventId: string,
    data: {
      title?: string;
      description?: string;
      start_time?: string;
      end_time?: string;
      event_type?: string;
    },
    scope: "this_only" | "this_and_future" | "all" = "this_only",
    overwriteExceptions: boolean = false
  ): Promise<{
    updated_count: number;
    skipped_exceptions: number;
    events: Array<{
      id: string;
      title: string;
      start_time: string;
      end_time: string;
    }>;
  }> {
    const params = new URLSearchParams({
      scope,
      overwrite_exceptions: overwriteExceptions.toString(),
    });
    return this.request(
      `/api/admin/blocking-events/${eventId}/series?${params}`,
      {
        method: "PUT",
        body: JSON.stringify(data),
      }
    );
  }

  // Holidays endpoints
  async getHolidays(year?: number): Promise<{
    items: Array<{
      id: string;
      date: string;
      name: string;
      is_all_day: boolean;
    }>;
    total: number;
  }> {
    const params = year ? `?year=${year}` : "";
    return this.request(`/api/admin/holidays${params}`);
  }

  async createHoliday(data: {
    date: string;
    name: string;
    is_all_day?: boolean;
  }): Promise<{
    id: string;
    date: string;
    name: string;
    is_all_day: boolean;
  }> {
    return this.request("/api/admin/holidays", {
      method: "POST",
      body: JSON.stringify(data),
    });
  }

  async deleteHoliday(id: string): Promise<void> {
    await this.request(`/api/admin/holidays/${id}`, {
      method: "DELETE",
    });
  }

  // Global Search
  async globalSearch(
    query: string,
    signal?: AbortSignal,
    limit: number = 5
  ): Promise<GlobalSearchResponse> {
    return this.request(`/api/admin/search?q=${encodeURIComponent(query)}&limit=${limit}`, {
      signal,
    });
  }

  // Notifications
  async getNotifications(
    limit: number = 20,
    includeRead: boolean = false,
    signal?: AbortSignal
  ): Promise<NotificationsListResponse> {
    return this.request(`/api/admin/notifications?limit=${limit}&include_read=${includeRead}`, {
      signal,
    });
  }

  async getNotificationsPaginated(
    params: NotificationQueryParams,
    signal?: AbortSignal
  ): Promise<NotificationsPaginatedResponse> {
    const searchParams = new URLSearchParams();
    if (params.page) searchParams.append("page", params.page.toString());
    if (params.page_size) searchParams.append("page_size", params.page_size.toString());
    if (params.types?.length) searchParams.append("types", params.types.join(","));
    if (params.category) searchParams.append("category", params.category);
    if (params.is_read !== undefined) searchParams.append("is_read", params.is_read.toString());
    if (params.is_starred !== undefined) searchParams.append("is_starred", params.is_starred.toString());
    if (params.date_from) searchParams.append("date_from", params.date_from);
    if (params.date_to) searchParams.append("date_to", params.date_to);
    if (params.search) searchParams.append("search", params.search);
    if (params.sort_by) searchParams.append("sort_by", params.sort_by);
    if (params.sort_order) searchParams.append("sort_order", params.sort_order);
    return this.request(`/api/admin/notifications/paginated?${searchParams.toString()}`, { signal });
  }

  async getNotificationStats(): Promise<NotificationStatsResponse> {
    return this.request("/api/admin/notifications/stats");
  }

  async markNotificationRead(notificationId: string): Promise<{ success: boolean }> {
    return this.request(`/api/admin/notifications/${notificationId}/read`, {
      method: "PUT",
    });
  }

  async markNotificationUnread(notificationId: string): Promise<{ success: boolean }> {
    return this.request(`/api/admin/notifications/${notificationId}/unread`, {
      method: "PUT",
    });
  }

  async markAllNotificationsRead(): Promise<{ success: boolean }> {
    return this.request("/api/admin/notifications/mark-all-read", {
      method: "PUT",
    });
  }

  async toggleNotificationStar(notificationId: string): Promise<{
    success: boolean;
    is_starred: boolean;
    starred_at: string | null;
  }> {
    return this.request(`/api/admin/notifications/${notificationId}/star`, {
      method: "PUT",
    });
  }

  async deleteNotification(notificationId: string): Promise<{ success: boolean }> {
    return this.request(`/api/admin/notifications/${notificationId}`, {
      method: "DELETE",
    });
  }

  async bulkDeleteNotifications(ids: string[]): Promise<{ success: boolean; deleted: number }> {
    return this.request("/api/admin/notifications/bulk", {
      method: "DELETE",
      body: JSON.stringify({ ids }),
    });
  }

  getNotificationsExportUrl(params: NotificationQueryParams): string {
    const searchParams = new URLSearchParams();
    if (params.types?.length) searchParams.append("types", params.types.join(","));
    if (params.category) searchParams.append("category", params.category);
    if (params.is_read !== undefined) searchParams.append("is_read", params.is_read.toString());
    if (params.is_starred !== undefined) searchParams.append("is_starred", params.is_starred.toString());
    if (params.date_from) searchParams.append("date_from", params.date_from);
    if (params.date_to) searchParams.append("date_to", params.date_to);
    if (params.search) searchParams.append("search", params.search);
    return `${this.baseUrl}/api/admin/notifications/export?${searchParams.toString()}`;
  }

  // Health check
  async health(): Promise<{
    status: string;
    redis: string;
    postgres: string;
  }> {
    return this.request("/health");
  }

  // System Settings
  async getSystemSettings(): Promise<SystemSettingsResponse> {
    return this.request("/api/admin/settings");
  }

  async getSystemSetting(key: string): Promise<SystemSetting> {
    return this.request(`/api/admin/settings/${key}`);
  }

  async updateSystemSetting(
    key: string,
    value: string | number | boolean,
    reason?: string
  ): Promise<SystemSetting> {
    return this.request(`/api/admin/settings/${key}`, {
      method: "PUT",
      body: JSON.stringify({ value, reason }),
    });
  }

  async resetSystemSetting(key: string): Promise<SystemSetting> {
    return this.request(`/api/admin/settings/${key}/reset`, {
      method: "POST",
    });
  }

  async getSettingsHistory(
    key?: string,
    limit: number = 50,
    offset: number = 0
  ): Promise<SettingsHistoryResponse> {
    const params = new URLSearchParams();
    if (key) params.append("key", key);
    params.append("limit", limit.toString());
    params.append("offset", offset.toString());
    return this.request(`/api/admin/settings/history?${params.toString()}`);
  }

  async restartConfirmationWorker(): Promise<{ success: boolean; message: string }> {
    return this.request("/api/admin/settings/restart-worker", {
      method: "POST",
    });
  }

  // System Management
  async getSystemServices(): Promise<SystemServicesResponse> {
    return this.request("/api/admin/system/services");
  }

  async restartService(service: SystemServiceName): Promise<ServiceActionResponse> {
    return this.request(`/api/admin/system/${service}/restart`, {
      method: "POST",
    });
  }

  async stopService(service: SystemServiceName): Promise<ServiceActionResponse> {
    return this.request(`/api/admin/system/${service}/stop`, {
      method: "POST",
    });
  }

  getServiceLogsUrl(service: SystemServiceName): string {
    // No token in URL — authentication via HttpOnly cookie (credentials:"include").
    return `${this.baseUrl}/api/admin/system/${service}/logs`;
  }

  async triggerGcalSync(): Promise<ServiceActionResponse> {
    return this.request("/api/admin/system/gcal-sync/trigger", {
      method: "POST",
    });
  }

  async clearSystemCache(): Promise<ServiceActionResponse> {
    return this.request("/api/admin/system/cache/clear", {
      method: "POST",
    });
  }

  // Google Calendar OAuth2 endpoints
  async getGoogleCalendarStatus(): Promise<GoogleCalendarStatus> {
    return this.request("/api/admin/google/status");
  }

  async getGoogleCalendarAuthUrl(): Promise<{ url: string; state: string }> {
    return this.request("/api/admin/google/auth-url");
  }

  async getGoogleCalendars(): Promise<{ calendars: GoogleCalendar[] }> {
    return this.request("/api/admin/google/calendars");
  }

  async disconnectGoogleCalendar(): Promise<void> {
    await this.request("/api/admin/google/disconnect", {
      method: "DELETE",
    });
  }

  async assignCalendarToStylist(
    stylistId: string,
    calendarId: string
  ): Promise<void> {
    await this.request(`/api/admin/stylists/${stylistId}/calendar`, {
      method: "PUT",
      body: JSON.stringify({ calendar_id: calendarId }),
    });
  }

  async createGoogleCalendar(payload: CreateCalendarPayload): Promise<GoogleCalendar> {
    return this.request("/api/admin/google/calendars", {
      method: "POST",
      body: JSON.stringify(payload),
    });
  }

  async updateGoogleCalendar(
    calendarId: string,
    payload: UpdateCalendarPayload
  ): Promise<GoogleCalendar> {
    return this.request(`/api/admin/google/calendars/${encodeURIComponent(calendarId)}`, {
      method: "PATCH",
      body: JSON.stringify(payload),
    });
  }

  async deleteGoogleCalendar(calendarId: string): Promise<void> {
    await this.request(`/api/admin/google/calendars/${encodeURIComponent(calendarId)}`, {
      method: "DELETE",
    });
  }

  // =========================================================================
  // Token Usage
  // =========================================================================

  async getTokenUsage(months: number = 12): Promise<TokenUsageList> {
    return this.request<TokenUsageList>(`/api/token-usage?months=${months}`);
  }

  async getCurrentMonthTokenUsage(): Promise<CurrentMonthUsage> {
    return this.request<CurrentMonthUsage>("/api/token-usage/current");
  }

  async getTokenPricing(): Promise<TokenPricing> {
    return this.request<TokenPricing>("/api/token-usage/pricing");
  }

  // Escalations
  async getEscalations(params?: EscalationQueryParams): Promise<{
    items: Escalation[];
    total: number;
    page: number;
    page_size: number;
    has_more: boolean;
  }> {
    const searchParams = new URLSearchParams();
    if (params?.page) searchParams.set("page", String(params.page));
    if (params?.page_size) searchParams.set("page_size", String(params.page_size));
    if (params?.status) searchParams.set("status", params.status);
    if (params?.source) searchParams.set("source", params.source);
    if (params?.is_technical_error !== undefined)
      searchParams.set("is_technical_error", String(params.is_technical_error));
    if (params?.date_from) searchParams.set("date_from", params.date_from);
    if (params?.date_to) searchParams.set("date_to", params.date_to);
    if (params?.search) searchParams.set("search", params.search);
    if (params?.sort_by) searchParams.set("sort_by", params.sort_by);
    if (params?.sort_order) searchParams.set("sort_order", params.sort_order);
    const qs = searchParams.toString();
    return this.request(`/api/admin/escalations${qs ? `?${qs}` : ""}`);
  }

  async getEscalation(id: string): Promise<Escalation> {
    return this.request(`/api/admin/escalations/${id}`);
  }

  async resolveEscalation(id: string): Promise<Escalation> {
    return this.request(`/api/admin/escalations/${id}/resolve`, { method: "PATCH" });
  }

  async getEscalationStats(): Promise<EscalationStats> {
    return this.request("/api/admin/escalations/stats");
  }

  // Customer detail endpoints
  async getCustomerDetail(id: string): Promise<CustomerDetail> {
    return this.request<CustomerDetail>(`/api/admin/customers/${id}`);
  }

  async getCustomerAppointments(
    id: string,
    page: number = 1,
    pageSize: number = 20
  ): Promise<CustomerAppointmentsPage> {
    const params = new URLSearchParams({
      page: page.toString(),
      page_size: pageSize.toString(),
    });
    return this.request<CustomerAppointmentsPage>(
      `/api/admin/customers/${id}/appointments?${params}`
    );
  }

  async updateCustomerMemories(
    id: string,
    memories: Partial<CustomerMemories>
  ): Promise<{ memories: CustomerMemories }> {
    return this.request<{ memories: CustomerMemories }>(
      `/api/admin/customers/${id}/memories`,
      {
        method: "PUT",
        body: JSON.stringify(memories),
      }
    );
  }

  // Admin user management endpoints (users:manage gated on backend)

  async listUsers(params?: { limit?: number; offset?: number }): Promise<AdminUserListResponse> {
    const query = new URLSearchParams();
    if (params?.limit != null) query.set("limit", String(params.limit));
    if (params?.offset != null) query.set("offset", String(params.offset));
    const qs = query.toString();
    return this.request<AdminUserListResponse>(`/api/admin/users/${qs ? `?${qs}` : ""}`);
  }

  async getUser(id: string): Promise<AdminUser> {
    return this.request<AdminUser>(`/api/admin/users/${id}`);
  }

  async createUser(data: AdminUserCreateRequest): Promise<AdminUser> {
    return this.request<AdminUser>("/api/admin/users/", {
      method: "POST",
      body: JSON.stringify(data),
    });
  }

  async updateUser(id: string, data: AdminUserUpdateRequest): Promise<AdminUser> {
    return this.request<AdminUser>(`/api/admin/users/${id}`, {
      method: "PATCH",
      body: JSON.stringify(data),
    });
  }

  async resetUserPassword(id: string, newPassword: string): Promise<void> {
    await this.request(`/api/admin/users/${id}/password-reset`, {
      method: "POST",
      body: JSON.stringify({ new_password: newPassword }),
    });
  }

  // =========================================================================
  // Inbox endpoints (conversaciones-inbox PR-3)
  // All paths under /api/admin/conversations/{id}/*
  // Methods use POST to match PR-2 implementation (admin.py uses POST, not PATCH).
  // =========================================================================

  /**
   * Send a free-text message from the admin panel to the customer via Chatwoot.
   * Requires conversations:write permission. Only valid within the 24h window.
   * FR-API-1, SC-1.
   */
  async sendMessage(
    convId: string,
    text: string
  ): Promise<import("./types").InboxMessageResponse> {
    return this.request<import("./types").InboxMessageResponse>(
      `/api/admin/conversations/${convId}/send-message`,
      { method: "POST", body: JSON.stringify({ text }) }
    );
  }

  /**
   * Send a Meta-approved template message. Requires templates:send permission.
   * Only available when window_open=false (outside 24h window).
   * FR-API-2, SC-1.
   */
  async sendTemplate(
    convId: string,
    templateName: string,
    params: Record<string, string>
  ): Promise<import("./types").InboxMessageResponse> {
    return this.request<import("./types").InboxMessageResponse>(
      `/api/admin/conversations/${convId}/send-template`,
      { method: "POST", body: JSON.stringify({ template_name: templateName, params }) }
    );
  }

  /**
   * Pause the bot for a conversation (atencion_automatica=False).
   * source="manual" creates an Escalation row. Requires bot:pause permission.
   * FR-API-2, SC-6.
   */
  async pauseConversation(
    convId: string,
    source: "manual" | "toggle",
    reason?: string
  ): Promise<import("./types").InboxPauseResponse> {
    return this.request<import("./types").InboxPauseResponse>(
      `/api/admin/conversations/${convId}/pause`,
      { method: "POST", body: JSON.stringify({ source, reason: reason ?? null }) }
    );
  }

  /**
   * Resume the bot for a conversation (atencion_automatica=True).
   * Sets pending_injection Redis flag. Requires bot:resume permission.
   * FR-API-3, SC-3.
   */
  async resumeConversation(
    convId: string
  ): Promise<import("./types").InboxResumeResponse> {
    return this.request<import("./types").InboxResumeResponse>(
      `/api/admin/conversations/${convId}/resume`,
      { method: "POST", body: JSON.stringify({}) }
    );
  }

  /**
   * Manually escalate a conversation. Requires escalations:resolve permission (admin only).
   * FR-API-5.
   */
  async escalateConversation(
    convId: string,
    reason: string,
    note?: string
  ): Promise<import("./types").InboxEscalationResponse> {
    return this.request<import("./types").InboxEscalationResponse>(
      `/api/admin/conversations/${convId}/escalate`,
      { method: "POST", body: JSON.stringify({ reason, note: note ?? null }) }
    );
  }

  /**
   * Get the current 24h message window status for a conversation.
   * Computed server-side from MAX(created_at WHERE role='user'). FR-API-4, SC-4.
   */
  async getWindowStatus(
    convId: string,
    signal?: AbortSignal
  ): Promise<import("./types").InboxWindowStatusResponse> {
    return this.request<import("./types").InboxWindowStatusResponse>(
      `/api/admin/conversations/${convId}/window-status`,
      { signal }
    );
  }

  /**
   * List available Meta templates and their approval status.
   * Requires conversations:read permission. FR-API-6.
   */
  async listTemplates(): Promise<import("./types").InboxTemplateListResponse> {
    return this.request<import("./types").InboxTemplateListResponse>(
      "/api/admin/conversations/templates"
    );
  }
}

export const api = new ApiClient(API_BASE_URL);
export default api;
