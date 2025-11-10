"""
Django Admin configuration for Atrévete models.

Provides comprehensive admin interfaces for all database models.
"""

from django.contrib import admin
from django.db.models import Count, Sum
from django.utils.html import format_html
from django.urls import reverse
from django.utils.safestring import mark_safe
from import_export.admin import ImportExportModelAdmin

from .models import (
    Stylist,
    Customer,
    Service,
    Appointment,
    Policy,
    ConversationHistory,
    BusinessHours,
)


# ============================================================================
# Admin Site Customization
# ============================================================================

admin.site.site_header = 'Atrévete Admin'
admin.site.site_title = 'Atrévete Admin'
admin.site.index_title = 'Panel de Administración'


# ============================================================================
# ModelAdmin Classes
# ============================================================================


@admin.register(Stylist)
class StylistAdmin(admin.ModelAdmin):
    """Admin interface for Stylist model."""

    list_display = ['name', 'category', 'is_active', 'google_calendar_id', 'created_at']
    list_filter = ['category', 'is_active', 'created_at']
    search_fields = ['name', 'google_calendar_id']
    readonly_fields = ['id', 'created_at', 'updated_at']
    ordering = ['name']
    list_per_page = 25

    fieldsets = (
        ('Información Básica', {
            'fields': ('name', 'category', 'is_active')
        }),
        ('Integración Google Calendar', {
            'fields': ('google_calendar_id',),
            'description': 'ID del calendario de Google asociado a este estilista.'
        }),
        ('Metadata', {
            'fields': ('metadata',),
            'classes': ('collapse',),
        }),
        ('Información del Sistema', {
            'fields': ('id', 'created_at', 'updated_at'),
            'classes': ('collapse',),
        }),
    )

    def get_queryset(self, request):
        """Add annotations for better performance."""
        qs = super().get_queryset(request)
        return qs.annotate(
            appointments_count=Count('appointments')
        )


@admin.register(Customer)
class CustomerAdmin(ImportExportModelAdmin):
    """Admin interface for Customer model with import/export capabilities."""

    list_display = ['full_name', 'phone', 'total_spent', 'last_service_date', 'preferred_stylist', 'created_at']
    list_filter = ['preferred_stylist', 'created_at', 'last_service_date']
    search_fields = ['first_name', 'last_name', 'phone']
    readonly_fields = ['id', 'created_at', 'total_spent_display', 'appointments_count']
    ordering = ['-last_service_date']
    list_per_page = 50
    date_hierarchy = 'created_at'

    fieldsets = (
        ('Información Personal', {
            'fields': ('first_name', 'last_name', 'phone')
        }),
        ('Estadísticas', {
            'fields': ('total_spent_display', 'appointments_count', 'last_service_date'),
        }),
        ('Preferencias', {
            'fields': ('preferred_stylist',),
        }),
        ('Metadata', {
            'fields': ('metadata',),
            'classes': ('collapse',),
            'description': 'Datos adicionales como whatsapp_name, referred_by, etc.'
        }),
        ('Información del Sistema', {
            'fields': ('id', 'created_at'),
            'classes': ('collapse',),
        }),
    )

    def total_spent_display(self, obj):
        """Display total spent with currency symbol."""
        return f"{obj.total_spent}€"
    total_spent_display.short_description = 'Total Gastado'

    def appointments_count(self, obj):
        """Display count of appointments."""
        count = obj.appointments.count()
        return format_html(
            '<a href="{}?customer__id__exact={}">{} citas</a>',
            reverse('admin:core_appointment_changelist'),
            obj.id,
            count
        )
    appointments_count.short_description = 'Número de Citas'

    def get_queryset(self, request):
        """Optimize queries with select_related."""
        qs = super().get_queryset(request)
        return qs.select_related('preferred_stylist')


@admin.register(Service)
class ServiceAdmin(ImportExportModelAdmin):
    """Admin interface for Service model with import/export capabilities."""

    list_display = ['name', 'category', 'duration_minutes', 'is_active']
    list_filter = ['category', 'is_active', 'created_at']
    search_fields = ['name', 'description']
    readonly_fields = ['id', 'created_at', 'updated_at']
    ordering = ['category', 'name']
    list_per_page = 50

    fieldsets = (
        ('Información Básica', {
            'fields': ('name', 'category', 'description', 'is_active')
        }),
        ('Duración', {
            'fields': ('duration_minutes',),
        }),
        ('Información del Sistema', {
            'fields': ('id', 'created_at', 'updated_at'),
            'classes': ('collapse',),
        }),
    )

    def get_form(self, request, obj=None, **kwargs):
        """Customize form help text."""
        form = super().get_form(request, obj, **kwargs)
        form.base_fields['duration_minutes'].help_text = 'Duración aproximada en minutos'
        return form


@admin.register(Appointment)
class AppointmentAdmin(ImportExportModelAdmin):
    """Admin interface for Appointment model with import/export capabilities."""

    list_display = [
        'start_time_display',
        'customer_link',
        'stylist',
        'status',
        'has_google_event',
    ]
    list_filter = ['status', 'stylist', 'start_time', 'created_at']
    search_fields = [
        'customer__first_name',
        'customer__last_name',
        'customer__phone',
        'google_calendar_event_id',
    ]
    readonly_fields = [
        'id',
        'google_calendar_event_id',
        'created_at',
        'updated_at',
        'service_list_display',
    ]
    ordering = ['-start_time']
    list_per_page = 50
    date_hierarchy = 'start_time'

    fieldsets = (
        ('Información de la Cita', {
            'fields': ('customer', 'stylist', 'start_time', 'duration_minutes')
        }),
        ('Servicios', {
            'fields': ('service_ids', 'service_list_display'),
            'description': 'Lista de UUIDs de servicios. Ver servicios seleccionados abajo.'
        }),
        ('Estado', {
            'fields': ('status', 'reminder_sent'),
        }),
        ('Integraciones Externas', {
            'fields': ('google_calendar_event_id',),
            'description': 'Este campo es gestionado automáticamente por el sistema. NO editar manualmente.',
            'classes': ('collapse',),
        }),
        ('Reservas Grupales', {
            'fields': ('group_booking_id', 'booked_by'),
            'classes': ('collapse',),
        }),
        ('Información del Sistema', {
            'fields': ('id', 'created_at', 'updated_at'),
            'classes': ('collapse',),
        }),
    )

    def start_time_display(self, obj):
        """Display start time in readable format."""
        return obj.start_time.strftime('%d/%m/%Y %H:%M')
    start_time_display.short_description = 'Fecha/Hora'
    start_time_display.admin_order_field = 'start_time'

    def customer_link(self, obj):
        """Display customer as clickable link."""
        url = reverse('admin:core_customer_change', args=[obj.customer.id])
        return format_html('<a href="{}">{}</a>', url, obj.customer.full_name)
    customer_link.short_description = 'Cliente'

    def has_google_event(self, obj):
        """Display if appointment has Google Calendar event."""
        if obj.google_calendar_event_id:
            return format_html('<span style="color: #27ae60;">Sí</span>')
        return format_html('<span style="color: #e74c3c;">No</span>')
    has_google_event.short_description = 'Google Calendar'

    def service_list_display(self, obj):
        """Display list of services for this appointment."""
        if not obj.service_ids:
            return "No hay servicios"

        services = Service.objects.filter(id__in=obj.service_ids)
        if not services.exists():
            return f"{len(obj.service_ids)} servicios (no encontrados en BD)"

        service_list = "<ul>" + "".join(
            f"<li>{service.name} ({service.duration_minutes}min)</li>"
            for service in services
        ) + "</ul>"
        return mark_safe(service_list)
    service_list_display.short_description = 'Servicios Seleccionados'

    def get_queryset(self, request):
        """Optimize queries with select_related."""
        qs = super().get_queryset(request)
        return qs.select_related('customer', 'stylist', 'booked_by')


@admin.register(Policy)
class PolicyAdmin(admin.ModelAdmin):
    """Admin interface for Policy model."""

    list_display = ['key', 'description', 'updated_at']
    list_filter = ['created_at', 'updated_at']
    search_fields = ['key', 'description']
    readonly_fields = ['id', 'created_at', 'updated_at']
    ordering = ['key']
    list_per_page = 50

    fieldsets = (
        ('Información de la Política', {
            'fields': ('key', 'description')
        }),
        ('Valor (JSON)', {
            'fields': ('value',),
            'description': 'Contenido de la política en formato JSON.',
        }),
        ('Información del Sistema', {
            'fields': ('id', 'created_at', 'updated_at'),
            'classes': ('collapse',),
        }),
    )


@admin.register(ConversationHistory)
class ConversationHistoryAdmin(admin.ModelAdmin):
    """Admin interface for ConversationHistory model."""

    list_display = [
        'conversation_id',
        'customer_link',
        'message_role',
        'message_preview',
        'timestamp',
    ]
    list_filter = ['message_role', 'timestamp']
    search_fields = [
        'conversation_id',
        'message_content',
        'customer__first_name',
        'customer__last_name',
        'customer__phone',
    ]
    readonly_fields = ['id', 'timestamp', 'message_content_display']
    ordering = ['-timestamp']
    list_per_page = 100
    date_hierarchy = 'timestamp'

    fieldsets = (
        ('Información de la Conversación', {
            'fields': ('conversation_id', 'customer', 'message_role', 'timestamp')
        }),
        ('Mensaje', {
            'fields': ('message_content_display',),
        }),
        ('Metadata', {
            'fields': ('metadata',),
            'classes': ('collapse',),
        }),
        ('Información del Sistema', {
            'fields': ('id',),
            'classes': ('collapse',),
        }),
    )

    def customer_link(self, obj):
        """Display customer as clickable link."""
        if not obj.customer:
            return "Cliente no identificado"
        url = reverse('admin:core_customer_change', args=[obj.customer.id])
        return format_html('<a href="{}">{}</a>', url, obj.customer.full_name)
    customer_link.short_description = 'Cliente'

    def message_preview(self, obj):
        """Display truncated message content."""
        max_length = 100
        if len(obj.message_content) > max_length:
            return f"{obj.message_content[:max_length]}..."
        return obj.message_content
    message_preview.short_description = 'Mensaje'

    def message_content_display(self, obj):
        """Display full message content in readonly field."""
        return obj.message_content
    message_content_display.short_description = 'Contenido del Mensaje'

    def get_queryset(self, request):
        """Optimize queries with select_related."""
        qs = super().get_queryset(request)
        return qs.select_related('customer')


@admin.register(BusinessHours)
class BusinessHoursAdmin(admin.ModelAdmin):
    """Admin interface for BusinessHours model."""

    list_display = [
        'get_day_display',
        'is_closed',
        'opening_hours_display',
        'updated_at',
    ]
    list_filter = ['is_closed']
    readonly_fields = ['id', 'created_at', 'updated_at']
    ordering = ['day_of_week']
    list_per_page = 10

    fieldsets = (
        ('Día de la Semana', {
            'fields': ('day_of_week', 'is_closed')
        }),
        ('Horario de Apertura', {
            'fields': ('start_hour', 'start_minute'),
            'description': 'Dejar en blanco si el salón está cerrado.'
        }),
        ('Horario de Cierre', {
            'fields': ('end_hour', 'end_minute'),
            'description': 'Dejar en blanco si el salón está cerrado.'
        }),
        ('Información del Sistema', {
            'fields': ('id', 'created_at', 'updated_at'),
            'classes': ('collapse',),
        }),
    )

    def get_day_display(self, obj):
        """Display day of week name."""
        return obj.get_day_of_week_display()
    get_day_display.short_description = 'Día'
    get_day_display.admin_order_field = 'day_of_week'

    def opening_hours_display(self, obj):
        """Display opening hours in readable format."""
        if obj.is_closed:
            return format_html('<span style="color: #e74c3c; font-weight: 600;">CERRADO</span>')

        start = f"{obj.start_hour:02d}:{obj.start_minute:02d}"
        end = f"{obj.end_hour:02d}:{obj.end_minute:02d}"
        return format_html('<span style="color: #27ae60;">{} - {}</span>', start, end)
    opening_hours_display.short_description = 'Horario'
