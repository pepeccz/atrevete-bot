"""
Django models mapping to existing PostgreSQL tables.

IMPORTANT: All models have managed=False to prevent Django migrations.
Database schema is managed by Alembic in the main project.
"""

import uuid
from decimal import Decimal

from django.contrib.postgres.fields import ArrayField
from django.core.validators import MinValueValidator, MinLengthValidator
from django.db import models


# ============================================================================
# Enums (using TextChoices for Django Admin compatibility)
# ============================================================================


class ServiceCategory(models.TextChoices):
    """Service category enumeration."""
    HAIRDRESSING = "Peluquería", "Peluquería"
    AESTHETICS = "Estética", "Estética"


class PaymentStatus(models.TextChoices):
    """Payment status for appointments."""
    PENDING = "pending", "Pendiente"
    CONFIRMED = "confirmed", "Confirmado"
    REFUNDED = "refunded", "Reembolsado"
    FORFEITED = "forfeited", "Perdido"


class AppointmentStatus(models.TextChoices):
    """Appointment lifecycle status."""
    PROVISIONAL = "provisional", "Provisional"
    CONFIRMED = "confirmed", "Confirmada"
    COMPLETED = "completed", "Completada"
    CANCELLED = "cancelled", "Cancelada"
    EXPIRED = "expired", "Expirada"


class MessageRole(models.TextChoices):
    """Role of message sender in conversation history."""
    USER = "user", "Usuario"
    ASSISTANT = "assistant", "Asistente"
    SYSTEM = "system", "Sistema"


# ============================================================================
# Core Models
# ============================================================================


class Stylist(models.Model):
    """
    Stylist model - Salon professionals providing services.

    Maps to 'stylists' table managed by Alembic.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=100)
    category = models.CharField(
        max_length=20,
        choices=ServiceCategory.choices,
        help_text="Especialidad: Peluquería o Estética"
    )
    google_calendar_id = models.CharField(
        max_length=255,
        unique=True,
        help_text="ID del calendario de Google asociado"
    )
    is_active = models.BooleanField(
        default=True,
        help_text="Estilista activo y disponible para citas"
    )
    metadata = models.JSONField(
        default=dict,
        blank=True,
        help_text="Datos adicionales en formato JSON"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        managed = False
        db_table = 'stylists'
        verbose_name = 'Estilista'
        verbose_name_plural = 'Estilistas'
        ordering = ['name']

    def __str__(self):
        return f"{self.name} ({self.get_category_display()})"


class Customer(models.Model):
    """
    Customer model - Salon customers with contact info and booking history.

    Maps to 'customers' table managed by Alembic.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    phone = models.CharField(
        max_length=20,
        unique=True,
        validators=[MinLengthValidator(10)],
        help_text="Teléfono en formato E.164 (ej: +34612345678)"
    )
    first_name = models.CharField(max_length=100, verbose_name="Nombre")
    last_name = models.CharField(
        max_length=100,
        blank=True,
        null=True,
        verbose_name="Apellidos"
    )
    total_spent = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=Decimal("0.00"),
        validators=[MinValueValidator(Decimal("0.00"))],
        verbose_name="Total gastado",
        help_text="Total gastado en euros"
    )
    last_service_date = models.DateTimeField(
        blank=True,
        null=True,
        verbose_name="Última visita"
    )
    preferred_stylist = models.ForeignKey(
        Stylist,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='preferred_customers',
        verbose_name="Estilista preferido"
    )
    metadata = models.JSONField(
        default=dict,
        blank=True,
        help_text="Datos adicionales (whatsapp_name, referred_by, etc.)"
    )
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Fecha de registro")

    class Meta:
        managed = False
        db_table = 'customers'
        verbose_name = 'Cliente'
        verbose_name_plural = 'Clientes'
        ordering = ['-last_service_date']

    def __str__(self):
        full_name = f"{self.first_name} {self.last_name or ''}".strip()
        return f"{full_name} ({self.phone})"

    @property
    def full_name(self):
        """Return customer's full name."""
        return f"{self.first_name} {self.last_name or ''}".strip()


class Service(models.Model):
    """
    Service model - Individual salon services with pricing and duration.

    Maps to 'services' table managed by Alembic.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=200, verbose_name="Nombre del servicio")
    category = models.CharField(
        max_length=20,
        choices=ServiceCategory.choices,
        verbose_name="Categoría"
    )
    duration_minutes = models.IntegerField(
        validators=[MinValueValidator(1)],
        verbose_name="Duración (minutos)",
        help_text="Duración aproximada en minutos"
    )
    price_euros = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        validators=[MinValueValidator(Decimal("0.00"))],
        verbose_name="Precio (€)",
        help_text="Precio en euros"
    )
    requires_advance_payment = models.BooleanField(
        default=True,
        verbose_name="Requiere anticipo",
        help_text="Marcar si este servicio requiere pago anticipado"
    )
    description = models.TextField(
        blank=True,
        null=True,
        verbose_name="Descripción",
        help_text="Descripción detallada del servicio"
    )
    is_active = models.BooleanField(
        default=True,
        verbose_name="Activo",
        help_text="Servicio disponible para reserva"
    )
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Fecha de creación")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="Última actualización")

    class Meta:
        managed = False
        db_table = 'services'
        verbose_name = 'Servicio'
        verbose_name_plural = 'Servicios'
        ordering = ['category', 'name']

    def __str__(self):
        return f"{self.name} - {self.price_euros}€ ({self.duration_minutes}min)"


class Appointment(models.Model):
    """
    Appointment model - Booking transactions with state management.

    Maps to 'appointments' table managed by Alembic.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    customer = models.ForeignKey(
        Customer,
        on_delete=models.CASCADE,
        related_name='appointments',
        verbose_name="Cliente"
    )
    stylist = models.ForeignKey(
        Stylist,
        on_delete=models.RESTRICT,
        related_name='appointments',
        verbose_name="Estilista"
    )
    service_ids = ArrayField(
        models.UUIDField(),
        verbose_name="Servicios",
        help_text="IDs de los servicios reservados"
    )
    start_time = models.DateTimeField(
        verbose_name="Hora de inicio",
        help_text="Fecha y hora de la cita"
    )
    duration_minutes = models.IntegerField(
        validators=[MinValueValidator(1)],
        verbose_name="Duración (minutos)"
    )
    total_price = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        validators=[MinValueValidator(Decimal("0.00"))],
        verbose_name="Precio total (€)"
    )
    advance_payment_amount = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=Decimal("0.00"),
        validators=[MinValueValidator(Decimal("0.00"))],
        verbose_name="Anticipo (€)",
        help_text="Cantidad pagada por adelantado"
    )
    payment_status = models.CharField(
        max_length=20,
        choices=PaymentStatus.choices,
        default=PaymentStatus.PENDING,
        verbose_name="Estado del pago"
    )
    status = models.CharField(
        max_length=20,
        choices=AppointmentStatus.choices,
        default=AppointmentStatus.PROVISIONAL,
        verbose_name="Estado de la cita"
    )
    google_calendar_event_id = models.CharField(
        max_length=255,
        blank=True,
        null=True,
        verbose_name="ID evento Google Calendar",
        help_text="ID del evento en Google Calendar (gestionado automáticamente)"
    )
    stripe_payment_id = models.CharField(
        max_length=255,
        blank=True,
        null=True,
        verbose_name="ID pago Stripe",
        help_text="PaymentIntent ID de Stripe (gestionado automáticamente)"
    )
    stripe_payment_link_id = models.CharField(
        max_length=255,
        blank=True,
        null=True,
        verbose_name="ID Payment Link Stripe",
        help_text="Stripe Payment Link ID (gestionado automáticamente)"
    )
    payment_retry_count = models.IntegerField(
        default=0,
        validators=[MinValueValidator(0)],
        verbose_name="Intentos de pago"
    )
    reminder_sent = models.BooleanField(
        default=False,
        verbose_name="Recordatorio enviado"
    )
    group_booking_id = models.UUIDField(
        blank=True,
        null=True,
        verbose_name="ID reserva grupal",
        help_text="ID compartido para reservas grupales"
    )
    booked_by = models.ForeignKey(
        Customer,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='bookings_made_for_others',
        verbose_name="Reservado por",
        help_text="Cliente que realizó la reserva (si es para terceros)"
    )
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Fecha de creación")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="Última actualización")

    class Meta:
        managed = False
        db_table = 'appointments'
        verbose_name = 'Cita'
        verbose_name_plural = 'Citas'
        ordering = ['-start_time']

    def __str__(self):
        return f"Cita {self.customer.first_name} - {self.start_time.strftime('%d/%m/%Y %H:%M')} ({self.get_status_display()})"


class Payment(models.Model):
    """
    Payment model - Records Stripe payment transactions for appointment deposits.

    Maps to 'payments' table managed by Alembic.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    appointment = models.ForeignKey(
        Appointment,
        on_delete=models.CASCADE,
        related_name='payments',
        verbose_name="Cita"
    )
    stripe_payment_intent_id = models.CharField(
        max_length=255,
        unique=True,
        verbose_name="PaymentIntent ID",
        help_text="ID del PaymentIntent de Stripe (pi_xxx)"
    )
    stripe_checkout_session_id = models.CharField(
        max_length=255,
        blank=True,
        null=True,
        verbose_name="Checkout Session ID",
        help_text="ID de la sesión de checkout de Stripe (cs_xxx)"
    )
    amount = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        verbose_name="Monto (€)",
        help_text="Monto del pago en euros"
    )
    status = models.CharField(
        max_length=20,
        choices=PaymentStatus.choices,
        default=PaymentStatus.PENDING,
        verbose_name="Estado"
    )
    stripe_metadata = models.JSONField(
        blank=True,
        null=True,
        verbose_name="Metadata Stripe",
        help_text="Datos adicionales del webhook de Stripe"
    )
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Fecha de creación")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="Última actualización")

    class Meta:
        managed = False
        db_table = 'payments'
        verbose_name = 'Pago'
        verbose_name_plural = 'Pagos'
        ordering = ['-created_at']

    def __str__(self):
        return f"Pago {self.stripe_payment_intent_id} - {self.amount}€ ({self.get_status_display()})"


class Policy(models.Model):
    """
    Policy model - Business rules and FAQs stored as key-value pairs.

    Maps to 'policies' table managed by Alembic.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    key = models.CharField(
        max_length=100,
        unique=True,
        verbose_name="Clave",
        help_text="Identificador único de la política o FAQ"
    )
    value = models.JSONField(
        verbose_name="Valor",
        help_text="Contenido de la política en formato JSON"
    )
    description = models.TextField(
        blank=True,
        null=True,
        verbose_name="Descripción",
        help_text="Descripción de la política"
    )
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Fecha de creación")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="Última actualización")

    class Meta:
        managed = False
        db_table = 'policies'
        verbose_name = 'Política/FAQ'
        verbose_name_plural = 'Políticas/FAQs'
        ordering = ['key']

    def __str__(self):
        return self.key


class ConversationHistory(models.Model):
    """
    ConversationHistory model - Archives conversation messages for long-term storage.

    Maps to 'conversation_history' table managed by Alembic.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    customer = models.ForeignKey(
        Customer,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='conversation_history',
        verbose_name="Cliente",
        help_text="Cliente asociado (puede ser null antes de identificación)"
    )
    conversation_id = models.CharField(
        max_length=255,
        verbose_name="ID Conversación",
        help_text="ID del thread de LangGraph"
    )
    timestamp = models.DateTimeField(verbose_name="Fecha/Hora")
    message_role = models.CharField(
        max_length=20,
        choices=MessageRole.choices,
        verbose_name="Rol"
    )
    message_content = models.TextField(verbose_name="Contenido")
    metadata = models.JSONField(
        default=dict,
        blank=True,
        verbose_name="Metadata",
        help_text="Datos adicionales (node_name, tool_calls, etc.)"
    )

    class Meta:
        managed = False
        db_table = 'conversation_history'
        verbose_name = 'Mensaje de Conversación'
        verbose_name_plural = 'Historial de Conversaciones'
        ordering = ['-timestamp']

    def __str__(self):
        return f"{self.conversation_id} - {self.get_message_role_display()} ({self.timestamp.strftime('%d/%m/%Y %H:%M')})"


class BusinessHours(models.Model):
    """
    Salon business hours configuration.

    Maps to 'business_hours' table managed by Alembic.
    Day of week: 0=Monday, 1=Tuesday, ..., 6=Sunday
    """

    DAYS_OF_WEEK = [
        (0, 'Lunes'),
        (1, 'Martes'),
        (2, 'Miércoles'),
        (3, 'Jueves'),
        (4, 'Viernes'),
        (5, 'Sábado'),
        (6, 'Domingo'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    day_of_week = models.IntegerField(
        choices=DAYS_OF_WEEK,
        unique=True,
        verbose_name="Día de la semana"
    )
    is_closed = models.BooleanField(
        default=False,
        verbose_name="Cerrado",
        help_text="Marcar si el salón está cerrado este día"
    )
    start_hour = models.IntegerField(
        blank=True,
        null=True,
        verbose_name="Hora de apertura",
        help_text="Hora de apertura (0-23)"
    )
    start_minute = models.IntegerField(
        default=0,
        verbose_name="Minutos de apertura",
        help_text="Minutos de apertura (0-59)"
    )
    end_hour = models.IntegerField(
        blank=True,
        null=True,
        verbose_name="Hora de cierre",
        help_text="Hora de cierre (0-23)"
    )
    end_minute = models.IntegerField(
        default=0,
        verbose_name="Minutos de cierre",
        help_text="Minutos de cierre (0-59)"
    )
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Fecha de creación")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="Última actualización")

    class Meta:
        managed = False
        db_table = 'business_hours'
        verbose_name = 'Horario del Negocio'
        verbose_name_plural = 'Horarios del Negocio'
        ordering = ['day_of_week']

    def __str__(self):
        day_name = self.get_day_of_week_display()
        if self.is_closed:
            return f"{day_name}: CERRADO"
        return f"{day_name}: {self.start_hour:02d}:{self.start_minute:02d} - {self.end_hour:02d}:{self.end_minute:02d}"
