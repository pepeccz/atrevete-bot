"""add_stylist_slug_fix_calendar_duplication

Adds a stable `slug` identity column to the `stylists` table, backfills it
from existing names, deactivates duplicate stylist rows (keeping the canonical
one per name+category group), nulls out google_calendar_id on deactivated
duplicates so the partial unique index can be created, and converts
google_calendar_id from NOT NULL/unique-index to nullable with a partial unique
index (allowing multiple NULLs while still enforcing uniqueness on non-null
values).

Revision ID: q7r8s9t0u1v2
Revises: p6q7r8s9t0u1
Create Date: 2026-03-12 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import text

# revision identifiers, used by Alembic.
revision: str = 'q7r8s9t0u1v2'
down_revision: Union[str, None] = 'p6q7r8s9t0u1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # -------------------------------------------------------------------------
    # Step A — Add slug column as nullable (will be set NOT NULL after backfill)
    # -------------------------------------------------------------------------
    op.add_column(
        'stylists',
        sa.Column('slug', sa.String(length=100), nullable=True)
    )

    # -------------------------------------------------------------------------
    # Step B — Backfill slug from name
    # Normalisation: lowercase + translate accent characters + replace non-alnum
    # runs with hyphens.  Uses only PostgreSQL built-ins (no extensions needed).
    # -------------------------------------------------------------------------
    op.execute(text("""
        UPDATE stylists
        SET slug = regexp_replace(
            lower(
                translate(
                    name,
                    'áéíóúÁÉÍÓÚàèìòùÀÈÌÒÙäëïöüÄËÏÖÜâêîôûÂÊÎÔÛñÑçÇ',
                    'aeiouaeiouaeiouaeiouaeiouaeiouaeiounncC'
                )
            ),
            '[^a-z0-9]+', '-', 'g'
        )
    """))

    # Strip leading/trailing hyphens that may arise from punctuation in names.
    op.execute(text("""
        UPDATE stylists
        SET slug = trim(both '-' from slug)
        WHERE slug IS NOT NULL
    """))

    # -------------------------------------------------------------------------
    # Step C — Identify and deactivate duplicate stylist rows.
    # For each (name, category) group with more than one active row, keep the
    # row with the most recent created_at that also has a google_calendar_id
    # assigned (i.e., the "canonical" stylist), or fall back to the newest row
    # if none have a calendar assigned.  Deactivate all others.
    # -------------------------------------------------------------------------
    op.execute(text("""
        WITH ranked AS (
            SELECT
                id,
                name,
                category,
                google_calendar_id,
                created_at,
                is_active,
                -- Prefer rows that already have a calendar assigned, then newest.
                ROW_NUMBER() OVER (
                    PARTITION BY name, category
                    ORDER BY
                        CASE WHEN google_calendar_id IS NOT NULL THEN 0 ELSE 1 END ASC,
                        created_at DESC
                ) AS rn
            FROM stylists
            WHERE is_active = true
        ),
        groups_with_duplicates AS (
            SELECT name, category
            FROM ranked
            GROUP BY name, category
            HAVING COUNT(*) > 1
        ),
        to_deactivate AS (
            SELECT r.id
            FROM ranked r
            JOIN groups_with_duplicates g ON r.name = g.name AND r.category = g.category
            WHERE r.rn > 1
        )
        UPDATE stylists
        SET is_active = false
        WHERE id IN (SELECT id FROM to_deactivate)
    """))

    # -------------------------------------------------------------------------
    # Step D — Null out google_calendar_id on deactivated duplicate rows so the
    # partial unique index (which applies only to non-null values) can be created
    # without conflicts.  Deactivated rows should not "own" a calendar anyway.
    # -------------------------------------------------------------------------
    op.execute(text("""
        WITH canonical AS (
            -- Find the id of the active (canonical) row for each calendar ID.
            SELECT DISTINCT ON (google_calendar_id) id, google_calendar_id
            FROM stylists
            WHERE google_calendar_id IS NOT NULL AND is_active = true
            ORDER BY google_calendar_id, created_at DESC
        )
        UPDATE stylists s
        SET google_calendar_id = NULL
        WHERE s.google_calendar_id IS NOT NULL
          AND s.is_active = false
          AND EXISTS (
              SELECT 1 FROM canonical c WHERE c.google_calendar_id = s.google_calendar_id
          )
    """))

    # -------------------------------------------------------------------------
    # Step E — Set slug NOT NULL (all rows have been backfilled above)
    # -------------------------------------------------------------------------
    op.alter_column('stylists', 'slug', nullable=False)

    # -------------------------------------------------------------------------
    # Step F — Add partial unique index on slug (only for active stylists).
    # This allows deactivated (deleted) rows to have duplicate slugs without
    # violating uniqueness. The constraint is only enforced on active rows.
    # -------------------------------------------------------------------------
    op.create_index(
        'uq_stylists_slug',
        'stylists',
        ['slug'],
        unique=True,
        postgresql_where=text("is_active = true"),
    )

    # -------------------------------------------------------------------------
    # Step G — Drop the old column-level unique index on google_calendar_id.
    # This was created by the initial migration as:
    #   op.create_index(op.f('ix_stylists_google_calendar_id'), 'stylists',
    #                   ['google_calendar_id'], unique=True)
    # The index name is therefore 'ix_stylists_google_calendar_id'.
    # -------------------------------------------------------------------------
    op.drop_index('ix_stylists_google_calendar_id', table_name='stylists')

    # -------------------------------------------------------------------------
    # Step H — Make google_calendar_id nullable
    # -------------------------------------------------------------------------
    op.alter_column('stylists', 'google_calendar_id', nullable=True)

    # -------------------------------------------------------------------------
    # Step I — Add partial unique index: uniqueness only on non-null values,
    # allowing multiple stylists with google_calendar_id = NULL.
    # -------------------------------------------------------------------------
    op.create_index(
        'uq_stylists_google_calendar_id_notnull',
        'stylists',
        ['google_calendar_id'],
        unique=True,
        postgresql_where=text("google_calendar_id IS NOT NULL"),
    )


def downgrade() -> None:
    # -------------------------------------------------------------------------
    # Reverse Step I — Drop partial unique index
    # -------------------------------------------------------------------------
    op.drop_index('uq_stylists_google_calendar_id_notnull', table_name='stylists')

    # -------------------------------------------------------------------------
    # Reverse Step H — Make google_calendar_id NOT NULL again.
    # WARNING: this will fail if any rows have google_calendar_id = NULL.
    # Ensure all rows have a calendar ID before downgrading in production.
    # -------------------------------------------------------------------------
    op.alter_column('stylists', 'google_calendar_id', nullable=False)

    # -------------------------------------------------------------------------
    # Reverse Step G — Recreate the original unique index
    # -------------------------------------------------------------------------
    op.create_index(
        op.f('ix_stylists_google_calendar_id'),
        'stylists',
        ['google_calendar_id'],
        unique=True,
    )

    # -------------------------------------------------------------------------
    # Reverse Step F — Drop the slug partial unique index
    # -------------------------------------------------------------------------
    op.drop_index('uq_stylists_slug', table_name='stylists')

    # -------------------------------------------------------------------------
    # Reverse Step E — Make slug nullable again (required before dropping column)
    # -------------------------------------------------------------------------
    op.alter_column('stylists', 'slug', nullable=True)

    # -------------------------------------------------------------------------
    # Reverse Steps D & C — Reactivate deactivated duplicate rows and restore
    # google_calendar_id values.
    # NOTE: We cannot reliably restore the original google_calendar_id values
    # for previously-deactivated rows because we nulled them out.  The downgrade
    # reactivates the rows but leaves google_calendar_id as NULL.  Manual
    # intervention will be required to restore calendar assignments if needed.
    # -------------------------------------------------------------------------
    op.execute(text("""
        UPDATE stylists
        SET is_active = true
        WHERE is_active = false
          AND slug IS NOT NULL
    """))

    # -------------------------------------------------------------------------
    # Reverse Steps A & B — Drop the slug column
    # -------------------------------------------------------------------------
    op.drop_column('stylists', 'slug')
