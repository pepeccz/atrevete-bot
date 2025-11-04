#!/bin/bash
set -e

# Database initialization script for Atrevete Bot
# This script runs Alembic migrations and seeds the database
# It's designed to be idempotent and can be run multiple times safely

echo "========================================"
echo "Atrevete Bot - Database Initialization"
echo "========================================"

# Configuration
MAX_RETRIES=30
RETRY_INTERVAL=2
DB_HOST="${POSTGRES_HOST:-postgres}"
DB_PORT="${POSTGRES_PORT:-5432}"
DB_NAME="${POSTGRES_DB:-atrevete_db}"
DB_USER="${POSTGRES_USER:-atrevete}"

echo "Database Configuration:"
echo "  Host: $DB_HOST"
echo "  Port: $DB_PORT"
echo "  Database: $DB_NAME"
echo "  User: $DB_USER"
echo ""

# Function to wait for PostgreSQL to be ready
wait_for_postgres() {
    echo "Waiting for PostgreSQL to be ready..."

    for i in $(seq 1 $MAX_RETRIES); do
        if pg_isready -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -d "$DB_NAME" > /dev/null 2>&1; then
            echo "✓ PostgreSQL is ready (attempt $i/$MAX_RETRIES)"
            return 0
        fi

        echo "  Waiting for PostgreSQL... (attempt $i/$MAX_RETRIES)"
        sleep $RETRY_INTERVAL
    done

    echo "✗ ERROR: PostgreSQL did not become ready after $MAX_RETRIES attempts"
    return 1
}

# Function to check if database is already initialized
check_db_initialized() {
    echo "Checking if database is already initialized..."

    # Check if alembic_version table exists
    if psql -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -d "$DB_NAME" -t -c "SELECT 1 FROM information_schema.tables WHERE table_name='alembic_version'" | grep -q 1; then
        echo "✓ Database already initialized (alembic_version table exists)"
        return 0
    else
        echo "  Database not initialized yet"
        return 1
    fi
}

# Function to run Alembic migrations
run_migrations() {
    echo ""
    echo "Running Alembic migrations..."

    # Set DATABASE_URL for Alembic (uses psycopg, not asyncpg)
    export DATABASE_URL="postgresql+psycopg://${DB_USER}:${POSTGRES_PASSWORD}@${DB_HOST}:${DB_PORT}/${DB_NAME}"

    if alembic upgrade head; then
        echo "✓ Migrations completed successfully"
        return 0
    else
        echo "✗ ERROR: Migration failed"
        return 1
    fi
}

# Function to run seed data
run_seeds() {
    echo ""
    echo "Loading seed data..."

    # Set DATABASE_URL for seed scripts (uses asyncpg)
    export DATABASE_URL="postgresql+asyncpg://${DB_USER}:${POSTGRES_PASSWORD}@${DB_HOST}:${DB_PORT}/${DB_NAME}"

    # List of seed scripts in order
    # NOTE: packs removed (functionality eliminated), faqs consolidated into policies
    SEED_SCRIPTS=(
        "database.seeds.services"
        "database.seeds.stylists"
        "database.seeds.business_hours"
        "database.seeds.policies"
    )

    for seed_script in "${SEED_SCRIPTS[@]}"; do
        echo "  Running: python -m $seed_script"
        if python -m "$seed_script"; then
            echo "  ✓ $seed_script completed"
        else
            echo "  ✗ WARNING: $seed_script failed (continuing anyway)"
        fi
    done

    echo "✓ Seed data loading completed"
    return 0
}

# Function to verify critical tables exist
verify_tables() {
    echo ""
    echo "Verifying critical tables exist..."

    CRITICAL_TABLES=(
        "customers"
        "stylists"
        "services"
        "appointments"
        "conversation_history"
    )

    for table in "${CRITICAL_TABLES[@]}"; do
        if psql -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -d "$DB_NAME" -t -c "SELECT 1 FROM information_schema.tables WHERE table_name='$table'" | grep -q 1; then
            echo "  ✓ Table '$table' exists"
        else
            echo "  ✗ WARNING: Table '$table' not found"
        fi
    done

    return 0
}

# Main execution
main() {
    echo "Starting initialization process..."
    echo ""

    # Step 1: Wait for PostgreSQL
    if ! wait_for_postgres; then
        echo ""
        echo "FATAL ERROR: Could not connect to PostgreSQL"
        exit 1
    fi

    # Step 2: Check if already initialized
    if check_db_initialized; then
        echo ""
        echo "Database already initialized, skipping migrations"
        verify_tables
        echo ""
        echo "========================================"
        echo "Initialization check completed"
        echo "========================================"
        exit 0
    fi

    # Step 3: Run migrations
    if ! run_migrations; then
        echo ""
        echo "FATAL ERROR: Migration failed"
        exit 1
    fi

    # Step 4: Run seeds
    if ! run_seeds; then
        echo ""
        echo "WARNING: Some seeds failed, but continuing"
    fi

    # Step 5: Verify tables
    verify_tables

    echo ""
    echo "========================================"
    echo "Initialization completed successfully!"
    echo "========================================"
}

# Run main function
main
