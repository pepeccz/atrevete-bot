#!/bin/bash
# run-tests-with-coverage.sh
# Helper script to run tests with coverage report locally
#
# Usage:
#   ./scripts/run-tests-with-coverage.sh           # All tests
#   ./scripts/run-tests-with-coverage.sh unit      # Unit tests only
#   ./scripts/run-tests-with-coverage.sh integration  # Integration tests only

set -e  # Exit on error

# Colors for output
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

echo -e "${GREEN}🧪 Running tests with coverage...${NC}"

# Set DATABASE_URL for tests
export DATABASE_URL="postgresql+asyncpg://atrevete:changeme_min16chars_secure_password@localhost:5432/atrevete_db"

# Determine test path
TEST_PATH="tests"
if [ "$1" = "unit" ]; then
    TEST_PATH="tests/unit"
    echo -e "${YELLOW}📦 Running unit tests only${NC}"
elif [ "$1" = "integration" ]; then
    TEST_PATH="tests/integration"
    echo -e "${YELLOW}🔗 Running integration tests only${NC}"
elif [ "$1" = "scenarios" ]; then
    TEST_PATH="tests/integration/scenarios"
    echo -e "${YELLOW}🎭 Running scenario tests only${NC}"
fi

# Run pytest with coverage
echo -e "${GREEN}Running pytest...${NC}"
pytest $TEST_PATH \
    --cov=agent \
    --cov=shared \
    --cov=database \
    --cov-report=term-missing:skip-covered \
    --cov-report=html \
    --cov-report=xml \
    --cov-fail-under=85 \
    -vv

# Check exit code
if [ $? -eq 0 ]; then
    echo -e "${GREEN}✅ Tests passed!${NC}"
    echo -e "${GREEN}📊 Coverage report generated:${NC}"
    echo -e "   - HTML: ${YELLOW}htmlcov/index.html${NC}"
    echo -e "   - XML:  ${YELLOW}coverage.xml${NC}"
    echo ""
    echo -e "${GREEN}To view HTML report:${NC}"
    echo -e "   ${YELLOW}firefox htmlcov/index.html${NC}"
    echo -e "   ${YELLOW}# or${NC}"
    echo -e "   ${YELLOW}xdg-open htmlcov/index.html${NC}"
else
    echo -e "${RED}❌ Tests failed or coverage below 85%${NC}"
    exit 1
fi
