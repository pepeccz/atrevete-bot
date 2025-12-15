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
} from "./types";

const API_BASE_URL =
  process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

interface ApiError {
  error: string;
  details?: unknown;
}

class ApiClient {
  private baseUrl: string;
  private token: string | null = null;

  constructor(baseUrl: string) {
    this.baseUrl = baseUrl;
  }

  setToken(token: string | null) {
    this.token = token;
  }

  getToken(): string | null {
    if (typeof window !== "undefined") {
      return this.token || localStorage.getItem("admin_token");
    }
    return this.token;
  }

  private async request<T>(
    endpoint: string,
    options: RequestInit = {}
  ): Promise<T> {
    const url = `${this.baseUrl}${endpoint}`;
    const token = this.getToken();

    const headers: HeadersInit = {
      "Content-Type": "application/json",
      ...options.headers,
    };

    // Include Authorization header as fallback for API clients
    // Primary authentication is via HttpOnly cookie (set by server)
    if (token) {
      (headers as Record<string, string>)["Authorization"] = `Bearer ${token}`;
    }

    const response = await fetch(url, {
      ...options,
      headers,
      // SECURITY: Include credentials to send HttpOnly cookies automatically
      credentials: "include",
    });

    if (!response.ok) {
      if (response.status === 401) {
        // Token expired or invalid
        this.setToken(null);
        if (typeof window !== "undefined") {
          localStorage.removeItem("admin_token");
          // Guardar URL actual para volver después del login
          const currentPath = window.location.pathname + window.location.search;
          if (currentPath !== "/login") {
            sessionStorage.setItem("returnTo", currentPath);
          }
          window.location.href = "/login";
        }
      }

      const error: ApiError = await response.json().catch(() => ({
        error: `HTTP ${response.status}: ${response.statusText}`,
      }));
      throw new Error(error.error || "Unknown error");
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
  ): Promise<{ access_token: string; token_type: string; expires_in: number }> {
    const response = await this.request<{
      access_token: string;
      token_type: string;
      expires_in: number;
    }>("/api/admin/auth/login", {
      method: "POST",
      body: JSON.stringify({ username, password }),
    });
    this.setToken(response.access_token);
    if (typeof window !== "undefined") {
      localStorage.setItem("admin_token", response.access_token);
    }
    return response;
  }

  async logout(): Promise<void> {
    // Call server logout endpoint to invalidate token and clear cookie
    try {
      await this.request("/api/admin/auth/logout", { method: "POST" });
    } catch (error) {
      // Ignore errors - we'll clear local state anyway
      console.warn("Server logout failed:", error);
    }

    // Clear local state
    this.setToken(null);
    if (typeof window !== "undefined") {
      localStorage.removeItem("admin_token");
    }
  }

  async getMe(): Promise<{ username: string; role: string }> {
    return this.request("/api/admin/auth/me");
  }

  // Dashboard endpoints
  async getDashboardKPIs(): Promise<{
    appointments_this_month: number;
    total_customers: number;
    avg_appointment_duration: number;
    total_hours_booked: number;
  }> {
    return this.request("/api/admin/dashboard/kpis");
  }

  async getAppointmentsTrend(
    days: number = 30
  ): Promise<Array<{ date: string; count: number }>> {
    return this.request(`/api/admin/dashboard/charts/appointments-trend?days=${days}`);
  }

  async getTopServices(
    limit: number = 10
  ): Promise<Array<{ name: string; count: number }>> {
    return this.request(`/api/admin/dashboard/charts/top-services?limit=${limit}`);
  }

  async getHoursWorked(
    months: number = 12
  ): Promise<Array<{ month: string; hours: number }>> {
    return this.request(`/api/admin/dashboard/charts/hours-worked?months=${months}`);
  }

  async getCustomerGrowth(
    months: number = 12
  ): Promise<Array<{ month: string; count: number }>> {
    return this.request(`/api/admin/dashboard/charts/customer-growth?months=${months}`);
  }

  async getStylistPerformance(): Promise<
    Array<{ name: string; appointments: number; hours: number }>
  > {
    return this.request("/api/admin/dashboard/charts/stylist-performance");
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
    end: string
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
      };
    }>;
    stylist_colors: Record<string, string>;
    total: number;
  }> {
    const params = new URLSearchParams({ start, end });
    if (stylistIds.length > 0) {
      params.append("stylist_ids", stylistIds.join(","));
    }
    return this.request(`/api/admin/calendar/events?${params}`);
  }

  async getAvailability(
    stylistId: string,
    date: string
  ): Promise<
    Array<{ time: string; end_time: string; available: boolean }>
  > {
    return this.request(
      `/api/admin/calendar/availability?stylist_id=${stylistId}&date=${date}`
    );
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

  async createBlockingEvent(data: {
    stylist_ids: string[];  // One or more stylists
    title: string;
    description?: string;
    start_time: string;
    end_time: string;
    event_type: string;
  }): Promise<{
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
    return this.request("/api/admin/blocking-events", {
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
    limit: number = 5
  ): Promise<GlobalSearchResponse> {
    return this.request(`/api/admin/search?q=${encodeURIComponent(query)}&limit=${limit}`);
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
    const token = this.getToken();
    return `${this.baseUrl}/api/admin/system/${service}/logs?token=${token}`;
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
}

export const api = new ApiClient(API_BASE_URL);
export default api;
