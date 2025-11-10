"""
Database Router for Atrévete Admin

This router prevents Django from running any migrations on the database.
All database schema management is handled by Alembic in the main project.
"""


class UnmanagedRouter:
    """
    A database router that prevents Django from managing the database schema.

    All models in the 'core' app have managed=False, but this router provides
    an additional layer of protection to ensure no migrations are ever run.
    """

    def db_for_read(self, model, **hints):
        """
        All read operations go to the default database.
        """
        return 'default'

    def db_for_write(self, model, **hints):
        """
        All write operations go to the default database.
        """
        return 'default'

    def allow_relation(self, obj1, obj2, **hints):
        """
        Allow all relations between objects.
        """
        return True

    def allow_migrate(self, db, app_label, model_name=None, **hints):
        """
        CRITICAL: Only allow Django to manage its own tables (auth, admin, sessions, contenttypes).

        Block migrations for 'core' app - those tables are managed by Alembic.
        """
        # Allow Django's built-in apps to migrate
        if app_label in ['auth', 'admin', 'sessions', 'contenttypes']:
            return True

        # Block migrations for our core app (managed by Alembic)
        if app_label == 'core':
            return False

        # Block everything else by default
        return False
