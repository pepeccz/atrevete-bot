#!/bin/bash
set -e

# ============================================================================
# Django Admin Entrypoint Script
# ============================================================================
# This script ensures that Django's built-in migrations are applied before
# starting the Django Admin application with Gunicorn.
#
# IMPORTANT: This script only runs migrations for Django's built-in apps:
# - auth (authentication system)
# - admin (admin panel)
# - sessions (session management)
# - contenttypes (content type framework)
#
# The 'core' app models are unmanaged (managed=False) and use Alembic
# migrations from the main application.
# ============================================================================

echo "============================================================================"
echo "Django Admin Initialization"
echo "============================================================================"

# ----------------------------------------------------------------------------
# Wait for PostgreSQL to be ready
# ----------------------------------------------------------------------------
echo "[1/4] Waiting for PostgreSQL..."

MAX_RETRIES=30
RETRY_COUNT=0

while [ $RETRY_COUNT -lt $MAX_RETRIES ]; do
    if python manage.py shell -c "from django.db import connection; connection.ensure_connection()" 2>/dev/null; then
        echo "✓ PostgreSQL is ready"
        break
    fi

    RETRY_COUNT=$((RETRY_COUNT + 1))
    echo "  Attempt $RETRY_COUNT/$MAX_RETRIES - PostgreSQL not ready yet, waiting..."
    sleep 2
done

if [ $RETRY_COUNT -eq $MAX_RETRIES ]; then
    echo "✗ ERROR: PostgreSQL connection failed after $MAX_RETRIES attempts"
    exit 1
fi

# ----------------------------------------------------------------------------
# Run Django migrations (built-in apps only)
# ----------------------------------------------------------------------------
echo ""
echo "[2/4] Running Django migrations..."
python manage.py migrate --run-syncdb

echo "✓ Django migrations applied successfully"

# ----------------------------------------------------------------------------
# Create default superuser if it doesn't exist
# ----------------------------------------------------------------------------
echo ""
echo "[3/4] Creating default superuser (if needed)..."

python manage.py shell <<EOF
from django.contrib.auth import get_user_model

User = get_user_model()

if not User.objects.filter(username='admin').exists():
    User.objects.create_superuser(
        username='admin',
        email='admin@atrevetepeluqueria.com',
        password='admin123'
    )
    print('✓ Superuser "admin" created successfully')
    print('  Username: admin')
    print('  Password: admin123')
else:
    print('✓ Superuser "admin" already exists')
EOF

# ----------------------------------------------------------------------------
# Start Gunicorn
# ----------------------------------------------------------------------------
echo ""
echo "[4/4] Starting Gunicorn server..."
echo "============================================================================"
echo "Django Admin ready at http://localhost:8001/admin/"
echo "Login: admin / admin123"
echo "============================================================================"
echo ""

exec gunicorn --bind 0.0.0.0:8001 --workers 2 --timeout 120 atrevete_admin.wsgi:application
