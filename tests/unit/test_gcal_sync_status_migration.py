"""Unit tests for GCal sync status model fields — AS9.

Validates that the ORM model has the 4 new gcal columns
and that the StrEnums define the correct values.

Integration-level migration test (AS9 default='synced' on existing rows)
is covered in tests/integration/test_gcal_migration.py.
"""

from database.models import Appointment, GcalOperation, GcalSyncStatus


class TestGcalSyncStatusEnum:
    """GcalSyncStatus StrEnum values."""

    def test_has_synced(self):
        assert GcalSyncStatus.SYNCED == "synced"

    def test_has_failed(self):
        assert GcalSyncStatus.FAILED == "failed"

    def test_has_not_applicable(self):
        assert GcalSyncStatus.NOT_APPLICABLE == "not_applicable"


class TestGcalOperationEnum:
    """GcalOperation StrEnum values."""

    def test_has_book(self):
        assert GcalOperation.BOOK == "book"

    def test_has_reschedule(self):
        assert GcalOperation.RESCHEDULE == "reschedule"

    def test_has_cancel(self):
        assert GcalOperation.CANCEL == "cancel"


class TestAppointmentGcalColumns:
    """Appointment model must expose the 4 new gcal columns."""

    def test_gcal_sync_status_column_exists(self):
        assert "gcal_sync_status" in Appointment.__table__.columns
        col = Appointment.__table__.columns["gcal_sync_status"]
        assert col.nullable is False

    def test_gcal_sync_status_has_server_default_synced(self):
        col = Appointment.__table__.columns["gcal_sync_status"]
        assert col.server_default is not None
        assert col.server_default.arg == "synced"

    def test_gcal_last_attempt_at_column_exists(self):
        assert "gcal_last_attempt_at" in Appointment.__table__.columns
        col = Appointment.__table__.columns["gcal_last_attempt_at"]
        assert col.nullable is True

    def test_gcal_last_error_column_exists(self):
        assert "gcal_last_error" in Appointment.__table__.columns
        col = Appointment.__table__.columns["gcal_last_error"]
        assert col.nullable is True

    def test_gcal_operation_column_exists(self):
        assert "gcal_operation" in Appointment.__table__.columns
        col = Appointment.__table__.columns["gcal_operation"]
        assert col.nullable is True
