# Django Admin Panel - Atrévete Bot

## Overview

The Atrévete Admin Panel is a modern Django-based web interface for managing salon data. It uses **Django Unfold** for a ShadCN-inspired UI with a Zinc color palette.

**URL**: http://localhost:8001/admin

**Credentials**: admin / admin123

---

## Architecture

### Key Characteristics

- **Unmanaged Models**: All models use `managed=False` - database schema is managed by Alembic
- **Shared Database**: Connects to the same PostgreSQL as the main application
- **Import/Export**: CSV, Excel, JSON support via django-import-export
- **Modern UI**: Django Unfold with ShadCN-inspired design

### Technology Stack

| Component | Technology | Purpose |
|-----------|------------|---------|
| Framework | Django 5.0+ | Admin interface |
| UI Theme | Django Unfold | Modern ShadCN-style UI |
| Static Files | WhiteNoise | Efficient static serving |
| Database | PostgreSQL 15+ | Shared with main app |
| Server | Gunicorn | Production WSGI server |

---

## File Structure

```
admin/
├── __init__.py
├── manage.py                     # Django management script
├── atrevete_admin/
│   ├── __init__.py
│   ├── settings.py               # 🔑 Django settings with UNFOLD config
│   ├── urls.py                   # URL configuration
│   ├── wsgi.py                   # WSGI entry point
│   └── router.py                 # Database router (UnmanagedRouter)
├── core/
│   ├── __init__.py
│   ├── apps.py                   # App configuration
│   ├── admin.py                  # 🔑 ModelAdmin registrations
│   ├── models.py                 # 🔑 Unmanaged Django models
│   ├── views.py                  # Dashboard callback
│   └── migrations/               # Django auth migrations only
├── static/                       # Custom static files
└── templates/                    # Custom templates
```

---

## Models

All models map to existing PostgreSQL tables. **NO Django migrations should run for core app**.

### Registered Models (7 total)

| Model | Table | Admin Features |
|-------|-------|----------------|
| `Stylist` | stylists | Status badges, appointment count |
| `Customer` | customers | Import/Export, spending stats, appointment links |
| `Service` | services | Import/Export, category filtering |
| `Appointment` | appointments | Import/Export, date hierarchy, service list |
| `Policy` | policies | JSON editor, search |
| `ConversationHistory` | conversation_history | Message preview, role badges |
| `BusinessHours` | business_hours | Day display, open/closed status |

### Model Configuration

All models include:
```python
class Meta:
    managed = False  # CRITICAL: Prevents Django migrations
    db_table = 'table_name'
    verbose_name = 'Spanish Name'
    verbose_name_plural = 'Spanish Names'
```

---

## Admin Interface Features

### StylistAdmin

**List Display**: Name, Category, Status badge, Calendar ID, Created date

**Features**:
- Status badge (Activo/Inactivo) with color coding
- Appointment count annotation
- Category filtering
- Google Calendar ID display

**Fieldsets**:
1. Información Básica (name, category, is_active)
2. Integración Google Calendar
3. Metadata (collapsible)
4. Información del Sistema (collapsible)

---

### CustomerAdmin

**List Display**: Full name, Phone, Total spent, Last service, Preferred stylist

**Features**:
- **Import/Export** (CSV, Excel, JSON)
- Total spent display with currency
- Clickable appointment count (links to filtered appointments)
- Date hierarchy by created_at
- Optimized queries with select_related

**Fieldsets**:
1. Información Personal (first_name, last_name, phone)
2. Estadísticas (total_spent, appointments_count, last_service_date)
3. Preferencias (preferred_stylist, notes)
4. Metadata (collapsible)
5. Información del Sistema (collapsible)

---

### ServiceAdmin

**List Display**: Name, Category, Duration, Status badge

**Features**:
- **Import/Export** (CSV, Excel, JSON)
- Category and active status filtering
- Duration in minutes with help text
- Fuzzy search on name and description

**Fieldsets**:
1. Información Básica (name, category, description, is_active)
2. Duración (duration_minutes)
3. Información del Sistema (collapsible)

---

### AppointmentAdmin

**List Display**: Date/Time, Customer link, Appointment name, Stylist, Status badge, Google Cal indicator

**Features**:
- **Import/Export** (CSV, Excel, JSON)
- Date hierarchy by start_time
- Clickable customer links
- Service list display (fetches service names from UUIDs)
- Status badges with color coding:
  - `confirmed`: green
  - `completed`: blue
  - `cancelled`: red
  - `provisional`: yellow
  - `expired`: red
- Google Calendar sync indicator

**Fieldsets**:
1. Información de la Cita (customer, stylist, start_time, duration)
2. Datos del Cliente para esta Cita (first_name, last_name, notes)
3. Servicios (service_ids, service_list_display)
4. Estado (status, reminder_sent)
5. Integraciones Externas (google_calendar_event_id - collapsible)
6. Reservas Grupales (group_booking_id, booked_by - collapsible)
7. Información del Sistema (collapsible)

---

### PolicyAdmin

**List Display**: Key, Description, Updated date

**Features**:
- JSON field for flexible values
- Key-based search
- Chronological ordering

**Fieldsets**:
1. Información de la Política (key, description)
2. Valor JSON (value)
3. Información del Sistema (collapsible)

---

### ConversationHistoryAdmin

**List Display**: Conversation ID, Customer link, Role badge, Message preview, Timestamp

**Features**:
- Date hierarchy by timestamp
- Role badges with colors:
  - `user`: blue
  - `assistant`: green
  - `system`: yellow
- Message preview (100 chars)
- Full message display in detail view
- Search across conversation_id, content, customer info

**Fieldsets**:
1. Información de la Conversación (conversation_id, customer, message_role, timestamp)
2. Mensaje (message_content_display)
3. Metadata (collapsible)
4. Información del Sistema (collapsible)

---

### BusinessHoursAdmin

**List Display**: Day name, Open/Closed status, Hours, Updated date

**Features**:
- Day of week display (Lunes, Martes, etc.)
- Open/Closed badges with colors
- Formatted hours display (HH:MM - HH:MM)
- Only 7 rows (one per day)

**Fieldsets**:
1. Día de la Semana (day_of_week, is_closed)
2. Horario de Apertura (start_hour, start_minute)
3. Horario de Cierre (end_hour, end_minute)
4. Información del Sistema (collapsible)

---

## UI Configuration (Django Unfold)

### Theme: ShadCN-inspired Zinc Palette

```python
"COLORS": {
    "base": {
        "50": "oklch(98.5% 0 0)",   # Lightest
        ...
        "950": "oklch(14.5% 0 0)",  # Darkest
    },
    "primary": { ... },  # Same as base for neutral look
}
```

### Sidebar Navigation

```
Panel Principal
├── Dashboard

Gestión del Salón
├── Citas
├── Clientes
├── Estilistas
└── Servicios

Configuración
├── Horarios
├── Políticas/FAQs
└── Historial Conversaciones

Sistema (superuser only)
├── Usuarios
└── Grupos
```

### Branding

- **Site Title**: "Atrévete Admin"
- **Site Header**: "Atrévete"
- **Site Subheader**: "Salón de Belleza"
- **Border Radius**: 6px (ShadCN default)

---

## Database Router

The `UnmanagedRouter` prevents Django from running migrations on core app tables:

```python
# atrevete_admin/router.py
class UnmanagedRouter:
    def allow_migrate(self, db, app_label, model_name=None, **hints):
        # Never run migrations for core app
        if app_label == 'core':
            return False
        return True
```

---

## Import/Export Functionality

### Supported Models

- Customer
- Service
- Appointment

### Supported Formats

- CSV
- Excel (xlsx)
- JSON

### Usage

1. Navigate to model list view
2. Click **Import** or **Export** button in toolbar
3. Select format and file
4. For import: Preview changes before confirming

### Configuration

```python
from unfold.contrib.import_export.forms import ExportForm, ImportForm

@admin.register(Customer)
class CustomerAdmin(ModelAdmin):
    import_form_class = ImportForm
    export_form_class = ExportForm
```

---

## Localization

- **Language**: Spanish (es-es)
- **Timezone**: Europe/Madrid
- **Date Format**: DD/MM/YYYY
- **Time Format**: HH:MM

All verbose_name and help_text are in Spanish.

---

## Dashboard

The dashboard displays metrics via the `dashboard_callback` function in `core/views.py`.

**Typical Metrics**:
- Total customers
- Appointments today
- Active stylists
- Revenue statistics

---

## Development

### Running Locally

```bash
# Start all services
docker-compose up -d

# View admin logs
docker-compose logs -f admin
```

### Shell Access

```bash
# Django shell
docker exec atrevete-admin python manage.py shell

# Create superuser
docker exec atrevete-admin python manage.py createsuperuser

# Collect static files
docker exec atrevete-admin python manage.py collectstatic --noinput
```

### Important Notes

1. **Never run Django migrations for core app** - Schema is managed by Alembic
2. **Django only manages auth tables** (auth_user, auth_group, sessions, contenttypes)
3. **Static files** served via WhiteNoise with compression
4. **Settings** imported from `shared/config.py` for DATABASE_URL

---

## Troubleshooting

### "Table does not exist" errors

Ensure Alembic migrations are up to date:
```bash
DATABASE_URL="postgresql+psycopg://..." ./venv/bin/alembic upgrade head
```

### Static files not loading

```bash
docker exec atrevete-admin python manage.py collectstatic --noinput
docker-compose restart admin
```

### Cannot login

1. Check credentials: admin / admin123
2. Verify service is running: `docker-compose ps admin`
3. Check logs: `docker-compose logs admin`

### Model changes not reflected

Remember: Django models are read-only mirrors of Alembic-managed tables. To change schema:
1. Modify `database/models.py` (SQLAlchemy)
2. Create Alembic migration
3. Update `admin/core/models.py` (Django) to match

---

## Screenshots Guide

### List Views

Each list view includes:
- Search bar
- Filter sidebar (collapsible)
- Bulk action dropdown
- Import/Export buttons (where supported)
- Pagination
- Date hierarchy (where configured)

### Detail Views

Each detail view includes:
- Organized fieldsets
- Collapsible sections for advanced fields
- Save buttons at bottom
- Delete button (where permitted)
- History link

### Badges

Status and role fields display as colored badges:
- **Success (green)**: Active, Confirmed, Assistant
- **Danger (red)**: Inactive, Cancelled, Expired
- **Warning (yellow)**: Provisional, System
- **Info (blue)**: Completed, User
