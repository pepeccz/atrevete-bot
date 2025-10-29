#!/bin/bash
set -e

# Entrypoint script for Atrevete Bot Agent Service
# This script initializes the database and Redis before starting the agent

echo "================================================"
echo "Atrevete Bot Agent - Entrypoint"
echo "================================================"

# Function to run database initialization
initialize_database() {
    echo ""
    echo "Running database initialization..."

    if /app/docker/init-db.sh; then
        echo "✓ Database initialization completed"
        return 0
    else
        echo "✗ ERROR: Database initialization failed"
        return 1
    fi
}

# Function to verify system readiness
verify_system() {
    echo ""
    echo "Verifying system readiness..."

    if python /app/scripts/init_system.py; then
        echo "✓ System verification passed"
        return 0
    else
        echo "⚠ WARNING: System verification had issues (continuing anyway)"
        return 0  # Don't fail on verification issues
    fi
}

# Main execution
main() {
    echo "Starting agent initialization sequence..."

    # Step 1: Initialize database
    if ! initialize_database; then
        echo ""
        echo "FATAL ERROR: Cannot start agent - database initialization failed"
        exit 1
    fi

    # Step 2: Verify system (non-blocking)
    verify_system

    echo ""
    echo "================================================"
    echo "Initialization complete - Starting agent service"
    echo "================================================"
    echo ""

    # Step 3: Start the actual agent service
    # Pass all arguments to the agent
    exec "$@"
}

# Run main function with all script arguments
main "$@"
