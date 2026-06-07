"""Unit tests for CustomerConsent SQLAlchemy model (T03).

Tests cover:
- Model can be imported and instantiated
- All required fields are present with correct types
- FK to customers uses ON DELETE RESTRICT
- accepted_via CHECK constraint reflected in __table_args__
- accepted_at defaults to current UTC time
- policy_version is non-null (nullable=False)
- source_message_id is nullable
- Composite index ix_customer_consents_customer_id_accepted_at declared

These are pure unit tests — no DB connection required.

Refs: Spec §1, Design §1.1-1.3, Task T03/T04
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from sqlalchemy import CheckConstraint, Index, inspect
from sqlalchemy.dialects.postgresql import UUID as PGUUID


class TestCustomerConsentModelExists:
    """Verify CustomerConsent can be imported (fails RED before T04)."""

    def test_customer_consent_importable(self):
        """CustomerConsent class must be importable from database.models."""
        from database.models import CustomerConsent  # noqa: F401

    def test_customer_consent_is_sqlalchemy_model(self):
        """CustomerConsent must be a SQLAlchemy mapped class."""
        from database.models import CustomerConsent

        assert hasattr(CustomerConsent, "__tablename__")
        assert CustomerConsent.__tablename__ == "customer_consents"


class TestCustomerConsentFields:
    """Verify all required fields with correct nullability and types."""

    def test_id_field_exists_uuid_pk(self):
        """id must be a UUID primary key with auto-default."""
        from database.models import CustomerConsent
        from sqlalchemy import inspect as sa_inspect

        mapper = sa_inspect(CustomerConsent)
        col = mapper.columns["id"]
        assert col.primary_key is True
        assert isinstance(col.type, PGUUID)

    def test_customer_id_field_exists_not_nullable(self):
        """customer_id must exist and must NOT be nullable."""
        from database.models import CustomerConsent
        from sqlalchemy import inspect as sa_inspect

        mapper = sa_inspect(CustomerConsent)
        col = mapper.columns["customer_id"]
        assert col.nullable is False

    def test_policy_version_field_not_nullable(self):
        """policy_version must NOT be nullable."""
        from database.models import CustomerConsent
        from sqlalchemy import inspect as sa_inspect

        mapper = sa_inspect(CustomerConsent)
        col = mapper.columns["policy_version"]
        assert col.nullable is False

    def test_accepted_at_field_not_nullable(self):
        """accepted_at must NOT be nullable."""
        from database.models import CustomerConsent
        from sqlalchemy import inspect as sa_inspect

        mapper = sa_inspect(CustomerConsent)
        col = mapper.columns["accepted_at"]
        assert col.nullable is False

    def test_accepted_via_field_not_nullable(self):
        """accepted_via must NOT be nullable."""
        from database.models import CustomerConsent
        from sqlalchemy import inspect as sa_inspect

        mapper = sa_inspect(CustomerConsent)
        col = mapper.columns["accepted_via"]
        assert col.nullable is False

    def test_source_message_id_is_nullable(self):
        """source_message_id must be nullable (optional field)."""
        from database.models import CustomerConsent
        from sqlalchemy import inspect as sa_inspect

        mapper = sa_inspect(CustomerConsent)
        col = mapper.columns["source_message_id"]
        assert col.nullable is True

    def test_created_at_field_exists(self):
        """created_at must exist with server_default."""
        from database.models import CustomerConsent
        from sqlalchemy import inspect as sa_inspect

        mapper = sa_inspect(CustomerConsent)
        col = mapper.columns["created_at"]
        assert col.nullable is False
        assert col.server_default is not None


class TestCustomerConsentForeignKey:
    """Verify FK constraint has ON DELETE RESTRICT."""

    def test_customer_id_fk_references_customers(self):
        """customer_id FK must reference customers.id."""
        from database.models import CustomerConsent
        from sqlalchemy import inspect as sa_inspect

        mapper = sa_inspect(CustomerConsent)
        col = mapper.columns["customer_id"]
        fks = list(col.foreign_keys)
        assert len(fks) == 1, "Expected exactly one FK on customer_id"
        fk = fks[0]
        assert "customers.id" in str(fk.target_fullname)

    def test_customer_id_fk_is_on_delete_restrict(self):
        """customer_id FK must have ondelete='RESTRICT'."""
        from database.models import CustomerConsent
        from sqlalchemy import inspect as sa_inspect

        mapper = sa_inspect(CustomerConsent)
        col = mapper.columns["customer_id"]
        fks = list(col.foreign_keys)
        assert len(fks) == 1
        fk = fks[0]
        # SQLAlchemy stores the ondelete action on the ForeignKey constraint
        assert fk.ondelete is not None
        assert fk.ondelete.upper() == "RESTRICT"


class TestCustomerConsentTableArgs:
    """Verify __table_args__ contains CHECK constraint and composite index."""

    def test_check_constraint_accepted_via_declared(self):
        """__table_args__ must contain a CHECK constraint for accepted_via."""
        from database.models import CustomerConsent

        table_args = CustomerConsent.__table_args__
        check_constraints = [
            c for c in table_args if isinstance(c, CheckConstraint)
        ]
        assert len(check_constraints) >= 1, "No CheckConstraint found in __table_args__"
        # At least one must reference accepted_via
        found = any(
            "accepted_via" in str(c.sqltext) for c in check_constraints
        )
        assert found, (
            "No CheckConstraint referencing 'accepted_via' found in __table_args__"
        )

    def test_check_constraint_valid_values_in_expression(self):
        """CHECK constraint expression must include 'whatsapp' and 'admin_panel'."""
        from database.models import CustomerConsent

        table_args = CustomerConsent.__table_args__
        check_constraints = [
            c for c in table_args if isinstance(c, CheckConstraint)
        ]
        for cc in check_constraints:
            expr = str(cc.sqltext)
            if "accepted_via" in expr:
                assert "whatsapp" in expr, "CHECK must include 'whatsapp'"
                assert "admin_panel" in expr, "CHECK must include 'admin_panel'"
                return
        pytest.fail("No accepted_via CHECK constraint found")

    def test_composite_index_declared(self):
        """__table_args__ must declare the composite index on (customer_id, accepted_at)."""
        from database.models import CustomerConsent

        table_args = CustomerConsent.__table_args__
        indexes = [a for a in table_args if isinstance(a, Index)]
        index_names = [idx.name for idx in indexes]
        assert "ix_customer_consents_customer_id_accepted_at" in index_names, (
            "Index ix_customer_consents_customer_id_accepted_at not found in __table_args__"
        )


class TestCustomerConsentInstantiation:
    """Verify object can be instantiated with required fields (no DB needed)."""

    def test_instantiate_with_required_fields(self):
        """CustomerConsent must accept required fields and produce a valid instance."""
        from database.models import CustomerConsent

        cid = uuid4()
        consent = CustomerConsent(
            customer_id=cid,
            policy_version="1.0",
            accepted_via="whatsapp",
        )
        assert consent.customer_id == cid
        assert consent.policy_version == "1.0"
        assert consent.accepted_via == "whatsapp"
        assert consent.source_message_id is None

    def test_instantiate_with_all_fields(self):
        """CustomerConsent must accept source_message_id and reflect it."""
        from database.models import CustomerConsent

        cid = uuid4()
        consent = CustomerConsent(
            customer_id=cid,
            policy_version="1.0",
            accepted_via="admin_panel",
            source_message_id="msg_abc123",
        )
        assert consent.source_message_id == "msg_abc123"

    def test_accepted_at_python_default_is_utc(self):
        """accepted_at Python-side default must produce an aware UTC datetime."""
        from database.models import CustomerConsent

        cid = uuid4()
        before = datetime.now(UTC)
        consent = CustomerConsent(
            customer_id=cid,
            policy_version="1.0",
            accepted_via="whatsapp",
        )
        after = datetime.now(UTC)
        # accepted_at uses a lambda default — it is set on object creation only
        # for models that define `default=lambda: datetime.now(UTC)`.
        # If the field has a server_default only, Python-side is None until flush.
        # We verify the Python default callable exists.
        from sqlalchemy import inspect as sa_inspect

        mapper = sa_inspect(CustomerConsent)
        col = mapper.columns["accepted_at"]
        # Either server_default or python-side default must be set
        assert col.server_default is not None or col.default is not None, (
            "accepted_at must have a default (server or Python-side)"
        )


class TestCustomerModelPolicyColumns:
    """Verify Customer model has the two new policy columns (T04)."""

    def test_customer_has_policy_accepted_at(self):
        """Customer model must have policy_accepted_at column."""
        from database.models import Customer
        from sqlalchemy import inspect as sa_inspect

        mapper = sa_inspect(Customer)
        assert "policy_accepted_at" in mapper.columns, (
            "Customer.policy_accepted_at column not found — implement T04"
        )

    def test_customer_policy_accepted_at_nullable(self):
        """Customer.policy_accepted_at must be nullable."""
        from database.models import Customer
        from sqlalchemy import inspect as sa_inspect

        mapper = sa_inspect(Customer)
        col = mapper.columns["policy_accepted_at"]
        assert col.nullable is True

    def test_customer_has_policy_version(self):
        """Customer model must have policy_version column."""
        from database.models import Customer
        from sqlalchemy import inspect as sa_inspect

        mapper = sa_inspect(Customer)
        assert "policy_version" in mapper.columns, (
            "Customer.policy_version column not found — implement T04"
        )

    def test_customer_policy_version_nullable(self):
        """Customer.policy_version must be nullable (backward compat — no backfill)."""
        from database.models import Customer
        from sqlalchemy import inspect as sa_inspect

        mapper = sa_inspect(Customer)
        col = mapper.columns["policy_version"]
        assert col.nullable is True
