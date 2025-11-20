"""
Dashboard callback and views for Unfold admin dashboard.

Retrieves metrics from database and formats them for Chart.js rendering.
"""

import json
from datetime import timedelta
from typing import Any

from django.contrib.admin.views.decorators import staff_member_required
from django.db.models import Avg, Count, Sum
from django.db.models.functions import TruncDate, TruncMonth
from django.shortcuts import render
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from .health_utils import (
    get_archiver_health,
    get_docker_status,
    get_postgres_health,
    get_recent_activity,
    get_redis_health,
    get_status_color,
    get_status_icon,
    get_system_status,
)
from .models import Appointment, Customer, Service, Stylist


def dashboard_callback(request, context: dict[str, Any]) -> dict[str, Any]:
    """
    Callback function for Unfold dashboard.

    Fetches metrics and passes them to templates/admin/index.html
    """

    today = timezone.now()
    month_start = today.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

    # ===================================================================
    # KPI METRICS
    # ===================================================================

    # 1. Appointments this month
    appointments_this_month = Appointment.objects.filter(
        start_time__gte=month_start,
        status__in=['confirmed', 'completed']
    ).count()

    # 2. Total customers
    total_customers = Customer.objects.count()

    # 3. Average appointment duration
    avg_duration = Appointment.objects.filter(
        status__in=['confirmed', 'completed']
    ).aggregate(
        avg=Avg('duration_minutes')
    )['avg'] or 0

    # 4. Total hours booked this month
    total_minutes = Appointment.objects.filter(
        start_time__gte=month_start,
        status__in=['confirmed', 'completed']
    ).aggregate(
        total=Sum('duration_minutes')
    )['total'] or 0
    total_hours = total_minutes / 60

    # ===================================================================
    # CHART 1: Appointments Trend (Last 30 days)
    # ===================================================================

    appointments_by_date = Appointment.objects.filter(
        start_time__gte=today - timedelta(days=30),
        status__in=['confirmed', 'completed']
    ).annotate(
        date=TruncDate('start_time')
    ).values('date').annotate(
        count=Count('id')
    ).order_by('date')

    dates = []
    appointment_counts = []
    for item in appointments_by_date:
        dates.append(item['date'].strftime('%d/%m'))
        appointment_counts.append(item['count'])

    chart_appointments = {
        "labels": dates or [today.strftime('%d/%m')],
        "datasets": [{
            "label": str(_("Citas")),
            "data": appointment_counts or [0],
            "borderColor": "#8b5cf6",
            "backgroundColor": "rgba(139, 92, 246, 0.1)",
            "borderWidth": 2,
            "tension": 0.4,
            "fill": True,
        }]
    }

    # ===================================================================
    # CHART 2: Most Requested Services (Top 10)
    # ===================================================================

    # Get all appointments with services
    appointments_with_services = Appointment.objects.filter(
        start_time__gte=month_start,
        status__in=['confirmed', 'completed']
    ).values_list('service_ids', flat=True)

    # Count service usage
    service_counts = {}
    for service_ids in appointments_with_services:
        if service_ids:
            for service_id in service_ids:
                sid = str(service_id)
                service_counts[sid] = service_counts.get(sid, 0) + 1

    # Get service names
    services = Service.objects.filter(
        id__in=list(service_counts.keys())
    ).values('id', 'name')
    service_map = {str(s['id']): s['name'] for s in services}

    # Sort and limit
    sorted_services = sorted(
        [(service_map.get(sid, 'Desconocido'), count)
         for sid, count in service_counts.items()],
        key=lambda x: x[1],
        reverse=True
    )[:10]

    chart_services = {
        "labels": [s[0][:25] for s in sorted_services] if sorted_services else ["Sin datos"],
        "datasets": [{
            "label": str(_("Solicitudes")),
            "data": [s[1] for s in sorted_services] if sorted_services else [0],
            "backgroundColor": [
                "#8b5cf6", "#f43f5e", "#06b6d4", "#f59e0b", "#10b981",
                "#3b82f6", "#ec4899", "#14b8a6", "#f97316", "#6366f1",
            ],
            "borderRadius": 4,
        }]
    }

    # ===================================================================
    # CHART 3: Hours Worked (Last 12 months)
    # ===================================================================

    hours_by_month = Appointment.objects.filter(
        start_time__gte=today - timedelta(days=365),
        status__in=['confirmed', 'completed']
    ).annotate(
        month=TruncMonth('start_time')
    ).values('month').annotate(
        total_minutes=Sum('duration_minutes')
    ).order_by('month')

    months = []
    hours = []
    for item in hours_by_month:
        if item['month']:
            months.append(item['month'].strftime('%b %y'))
            hours.append(round((item['total_minutes'] or 0) / 60, 1))

    chart_hours = {
        "labels": months or [today.strftime('%b %y')],
        "datasets": [{
            "label": str(_("Horas")),
            "data": hours or [0],
            "borderColor": "#10b981",
            "backgroundColor": "rgba(16, 185, 129, 0.1)",
            "borderWidth": 2,
            "tension": 0.4,
            "fill": True,
        }]
    }

    # ===================================================================
    # CHART 4: Customer Growth (Last 12 months)
    # ===================================================================

    customers_by_month = Customer.objects.filter(
        created_at__gte=today - timedelta(days=365)
    ).annotate(
        month=TruncMonth('created_at')
    ).values('month').annotate(
        count=Count('id')
    ).order_by('month')

    months_growth = []
    customer_counts = []
    for item in customers_by_month:
        if item['month']:
            months_growth.append(item['month'].strftime('%b %y'))
            customer_counts.append(item['count'])

    chart_customers = {
        "labels": months_growth or [today.strftime('%b %y')],
        "datasets": [{
            "label": str(_("Nuevos clientes")),
            "data": customer_counts or [0],
            "borderColor": "#3b82f6",
            "backgroundColor": "rgba(59, 130, 246, 0.1)",
            "borderWidth": 2,
            "tension": 0.4,
            "fill": True,
        }]
    }

    # ===================================================================
    # CHART 5: Stylist Performance (This month)
    # ===================================================================

    stylist_stats = Appointment.objects.filter(
        start_time__gte=month_start,
        status__in=['confirmed', 'completed']
    ).values('stylist__name').annotate(
        count=Count('id'),
        total_minutes=Sum('duration_minutes')
    ).order_by('-count')

    stylist_names = []
    stylist_appointments = []
    stylist_hours = []
    for stat in stylist_stats:
        stylist_names.append(stat['stylist__name'])
        stylist_appointments.append(stat['count'])
        stylist_hours.append(round((stat['total_minutes'] or 0) / 60, 1))

    chart_stylists = {
        "labels": stylist_names or [str(_("Sin datos"))],
        "datasets": [
            {
                "label": str(_("Citas")),
                "data": stylist_appointments or [0],
                "backgroundColor": "#8b5cf6",
                "borderRadius": 4,
            },
            {
                "label": str(_("Horas")),
                "data": stylist_hours or [0],
                "backgroundColor": "#06b6d4",
                "borderRadius": 4,
            }
        ]
    }

    # ===================================================================
    # Update context
    # ===================================================================

    context.update({
        # KPI Metrics
        'kpi_appointments_month': appointments_this_month,
        'kpi_total_customers': total_customers,
        'kpi_avg_duration': round(avg_duration),
        'kpi_total_hours': round(total_hours, 1),

        # Chart data (JSON)
        'chart_appointments_json': json.dumps(chart_appointments),
        'chart_services_json': json.dumps(chart_services),
        'chart_hours_json': json.dumps(chart_hours),
        'chart_customers_json': json.dumps(chart_customers),
        'chart_stylists_json': json.dumps(chart_stylists),
    })

    return context


# ============================================================================
# Infrastructure Status View
# ============================================================================


@staff_member_required
def status_view(request):
    """
    Infrastructure status dashboard.

    Displays health and status of all services:
    - Docker containers
    - Redis
    - PostgreSQL
    - Archiver worker
    - Recent activity metrics

    Only accessible to staff members.
    """
    # Gather health data from all services
    redis_health = get_redis_health()
    postgres_health = get_postgres_health()
    archiver_health = get_archiver_health()
    docker_services = get_docker_status()
    recent_activity = get_recent_activity()

    # Calculate overall system status
    system_status = get_system_status(redis_health, postgres_health, archiver_health)

    # Filter key services from Docker list
    key_services = {
        "atrevete-api": None,
        "atrevete-agent": None,
        "atrevete-postgres": None,
        "atrevete-redis": None,
        "atrevete-admin": None,
        "atrevete-archiver": None,
    }

    for service in docker_services:
        name = service.get("name", "")
        if name in key_services:
            key_services[name] = service

    # Prepare context
    context = {
        "title": _("Estado del Sistema"),
        "system_status": system_status,
        "system_status_icon": get_status_icon(system_status),
        "system_status_color": get_status_color(system_status),
        "redis_health": redis_health,
        "redis_icon": get_status_icon(redis_health.get("status", "unknown")),
        "postgres_health": postgres_health,
        "postgres_icon": get_status_icon(postgres_health.get("status", "unknown")),
        "archiver_health": archiver_health,
        "archiver_icon": get_status_icon(archiver_health.get("status", "unknown")),
        "api_service": key_services.get("atrevete-api"),
        "api_icon": get_status_icon(
            key_services.get("atrevete-api", {}).get("health", "unknown")
        ),
        "agent_service": key_services.get("atrevete-agent"),
        "agent_icon": get_status_icon(
            key_services.get("atrevete-agent", {}).get("health", "unknown")
        ),
        "all_services": docker_services,
        "recent_activity": recent_activity,
        "timestamp": timezone.now(),
    }

    return render(request, "admin/status.html", context)
