"""Unit tests for AdminUser ORM model and Escalation FK.

Tests inspect ORM metadata without requiring a live database.
Integration-level tests (actual DB insert/constraint violations) are in
tests/integration/test_admin_users_migration.py.

Covers: FR-DB-1, FR-DB-2, SC-FK-1, SC-FK-2 (schema-level assertions).
"""

from __future__ import annotations

import pytest
from sqlalchemy import CheckConstraint, inspect

from database.models import AdminUser, Escalation


class TestAdminUserModel:
    """Tests for AdminUser ORM model fields and constraints (FR-DB-1)."""

    def test_admin_user_table_name(self):
        """AdminUser maps to admin_users table."""
        assert AdminUser.__tablename__ == "admin_users"

    def test_admin_user_required_columns_exist(self):
        """AdminUser model has all required columns per FR-DB-1."""
        column_names = {col.key for col in inspect(AdminUser).columns}
        required = {
            "id",
            "username",
            "password_hash",
            "role",
            "is_active",
            "display_name",
            "last_login_at",
            "created_at",
            "updated_at",
        }
        missing = required - column_names
        assert not missing, f"Missing columns: {missing}"

    def test_admin_user_id_is_primary_key(self):
        """id column is a primary key."""
        col = inspect(AdminUser).columns["id"]
        assert col.primary_key is True

    def test_admin_user_username_not_nullable(self):
        """username column is NOT NULL."""
        col = inspect(AdminUser).columns["username"]
        assert col.nullable is False

    def test_admin_user_username_is_unique(self):
        """username has a unique constraint."""
        col = AdminUser.__table__.c["username"]
        assert col.unique is True

    def test_admin_user_password_hash_not_nullable(self):
        """password_hash column is NOT NULL."""
        col = inspect(AdminUser).columns["password_hash"]
        assert col.nullable is False

    def test_admin_user_role_not_nullable(self):
        """role column is NOT NULL."""
        col = inspect(AdminUser).columns["role"]
        assert col.nullable is False

    def test_admin_user_is_active_not_nullable(self):
        """is_active column is NOT NULL."""
        col = inspect(AdminUser).columns["is_active"]
        assert col.nullable is False

    def test_admin_user_is_active_column_default_is_true(self):
        """is_active column has default=True defined on the ORM column."""
        col = AdminUser.__table__.c["is_active"]
        # The column-level default value is True
        assert col.default is not None and col.default.arg is True

    def test_admin_user_display_name_nullable(self):
        """display_name column is nullable."""
        col = inspect(AdminUser).columns["display_name"]
        assert col.nullable is True

    def test_admin_user_last_login_at_nullable(self):
        """last_login_at column is nullable."""
        col = inspect(AdminUser).columns["last_login_at"]
        assert col.nullable is True

    def test_admin_user_role_check_constraint_exists(self):
        """Table has a CHECK constraint that references role."""
        check_constraints = [
            c for c in AdminUser.__table__.constraints if isinstance(c, CheckConstraint)
        ]
        assert check_constraints, "No CHECK constraint found on admin_users"
        role_check_found = any(
            "role" in str(c.sqltext).lower() or (c.name and "role" in c.name.lower())
            for c in check_constraints
        )
        assert role_check_found, (
            "No CHECK constraint referencing 'role' found. "
            f"Found constraints: {[str(c.sqltext) for c in check_constraints]}"
        )

    def test_admin_user_role_check_allows_admin_and_stylist(self):
        """CHECK constraint text allows exactly 'admin' and 'stylist'."""
        check_constraints = [
            c for c in AdminUser.__table__.constraints if isinstance(c, CheckConstraint)
        ]
        role_check = next(
            (c for c in check_constraints if "role" in str(c.sqltext).lower()),
            None,
        )
        assert role_check is not None
        sql_text = str(role_check.sqltext).lower()
        assert "admin" in sql_text
        assert "stylist" in sql_text

    def test_admin_user_composite_index_role_active(self):
        """Table has a composite index on (role, is_active)."""
        indexes = {idx.name: idx for idx in AdminUser.__table__.indexes}
        assert (
            "ix_admin_users_role_active" in indexes
        ), f"Expected ix_admin_users_role_active index. Found: {list(indexes.keys())}"

    def test_admin_user_repr_contains_key_fields(self):
        """AdminUser __repr__ contains id, username, and role."""
        from uuid import uuid4

        uid = uuid4()
        user = AdminUser(id=uid, username="reprtest", password_hash="hash", role="admin")
        r = repr(user)
        assert "AdminUser" in r
        assert "reprtest" in r
        assert "admin" in r


class TestEscalationResolvedByFK:
    """Tests for Escalation.resolved_by_user_id nullable FK (FR-DB-2, SC-FK-1, SC-FK-2)."""

    def test_escalation_has_resolved_by_user_id_column(self):
        """Escalation model has resolved_by_user_id column."""
        col_names = {col.key for col in inspect(Escalation).columns}
        assert "resolved_by_user_id" in col_names

    def test_escalation_resolved_by_user_id_is_nullable(self):
        """resolved_by_user_id column is nullable (SC-FK-1)."""
        col = inspect(Escalation).columns["resolved_by_user_id"]
        assert col.nullable is True

    def test_escalation_resolved_by_user_id_fk_to_admin_users(self):
        """resolved_by_user_id has a FK pointing to admin_users.id."""
        fk_targets = {fk.column.table.name for fk in Escalation.__table__.foreign_keys}
        assert (
            "admin_users" in fk_targets
        ), f"No FK from escalations → admin_users found. FK targets: {fk_targets}"

    def test_escalation_resolved_by_fk_on_delete_set_null(self):
        """resolved_by_user_id FK has ON DELETE SET NULL (SC-FK-2)."""
        for fk in Escalation.__table__.foreign_keys:
            if fk.column.table.name == "admin_users":
                assert fk.ondelete is not None, "FK has no ondelete clause"
                assert (
                    fk.ondelete.upper() == "SET NULL"
                ), f"Expected ON DELETE SET NULL, got {fk.ondelete!r}"
                return
        pytest.fail("FK to admin_users not found in escalations table")
