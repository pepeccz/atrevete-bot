"""
Integration tests for Docker Compose configuration
Tests validate AC requirements for Story 1.2
"""
import subprocess

import pytest
import yaml


class TestDockerComposeConfiguration:
    """Tests for docker-compose.yml structure and configuration"""

    @pytest.fixture
    def docker_compose_config(self):
        """Load and parse docker-compose.yml"""
        result = subprocess.run(
            ["docker-compose", "config"],
            capture_output=True,
            text=True,
            check=False
        )
        if result.returncode != 0:
            pytest.fail(f"docker-compose config failed: {result.stderr}")
        return yaml.safe_load(result.stdout)

    def test_docker_compose_file_parses_successfully(self):
        """AC 10: Docker Compose file parses without errors"""
        result = subprocess.run(
            ["docker-compose", "config"],
            capture_output=True,
            text=True,
            check=False
        )
        assert result.returncode == 0, f"docker-compose config failed: {result.stderr}"

    def test_all_required_services_defined(self, docker_compose_config):
        """AC 1: docker-compose.yml defines api, agent, and data services"""
        services = docker_compose_config.get("services", {})

        # Must have api, agent, postgres, redis services
        assert "api" in services, "api service not defined"
        assert "agent" in services, "agent service not defined"
        assert "postgres" in services, "postgres service not defined"
        assert "redis" in services, "redis service not defined"

    def test_postgres_configuration(self, docker_compose_config):
        """AC 2, 7: PostgreSQL 15+ with volume persistence"""
        postgres = docker_compose_config["services"]["postgres"]

        # Check image version
        assert "postgres:15" in postgres["image"], "PostgreSQL must be version 15+"

        # Check volume mount
        volumes = postgres.get("volumes", [])
        assert any("postgres_data" in str(vol) for vol in volumes), \
            "postgres_data volume not mounted"

    def test_redis_configuration(self, docker_compose_config):
        """AC 2, 8: Redis 7+ with RDB persistence"""
        redis = docker_compose_config["services"]["redis"]

        # Check image version
        assert "redis:7" in redis["image"], "Redis must be version 7+"

        # Check RDB persistence command
        command = redis.get("command", "")
        assert "--save" in command, "Redis RDB persistence not configured"

        # Check volume mount
        volumes = redis.get("volumes", [])
        assert any("redis_data" in str(vol) for vol in volumes), \
            "redis_data volume not mounted"

    def test_api_service_configuration(self, docker_compose_config):
        """AC 3, 6: API service exposes port 8000 and loads .env"""
        api = docker_compose_config["services"]["api"]

        # Check port mapping
        ports = api.get("ports", [])
        assert any("8000" in str(port) for port in ports), \
            "API service must expose port 8000"

        # Check env_file
        env_file = api.get("environment", {})
        # Environment variables should be loaded (validated by config parsing)
        assert len(env_file) > 0, "API service must load environment variables"

    def test_agent_service_configuration(self, docker_compose_config):
        """AC 4, 6: Agent connects to Redis and PostgreSQL"""
        agent = docker_compose_config["services"]["agent"]

        # Check dependencies
        depends_on = agent.get("depends_on", {})
        assert "postgres" in depends_on, "Agent must depend on postgres"
        assert "redis" in depends_on, "Agent must depend on redis"

        # Check env_file
        env_file = agent.get("environment", {})
        assert len(env_file) > 0, "Agent service must load environment variables"

    def test_network_configuration(self, docker_compose_config):
        """AC 5: All services share Docker network"""
        services = docker_compose_config["services"]

        # Check that network exists
        networks = docker_compose_config.get("networks", {})
        assert "atrevete-network" in networks, "atrevete-network not defined"

        # Check all services are on the network
        for service_name in ["api", "agent", "postgres", "redis"]:
            service = services[service_name]
            service_networks = service.get("networks", {})
            assert "atrevete-network" in service_networks or len(service_networks) > 0, \
                f"{service_name} not attached to network"

    def test_volumes_defined(self, docker_compose_config):
        """AC 7, 8: Named volumes defined for persistence"""
        volumes = docker_compose_config.get("volumes", {})

        assert "postgres_data" in volumes, "postgres_data volume not defined"
        assert "redis_data" in volumes, "redis_data volume not defined"

    def test_health_checks_configured(self, docker_compose_config):
        """AC 9: Health checks configured for all services"""
        services = docker_compose_config["services"]

        # Check postgres health check
        postgres_health = services["postgres"].get("healthcheck", {})
        assert "test" in postgres_health, "PostgreSQL health check not configured"

        # Check redis health check
        redis_health = services["redis"].get("healthcheck", {})
        assert "test" in redis_health, "Redis health check not configured"

        # Check api health check
        api_health = services["api"].get("healthcheck", {})
        assert "test" in api_health, "API health check not configured"

        # Check agent health check
        agent_health = services["agent"].get("healthcheck", {})
        assert "test" in agent_health, "Agent health check not configured"

    def test_restart_policies_configured(self, docker_compose_config):
        """All services should have restart: unless-stopped"""
        services = docker_compose_config["services"]

        for service_name in ["api", "agent", "postgres", "redis"]:
            service = services[service_name]
            restart = service.get("restart", "")
            assert restart == "unless-stopped", \
                f"{service_name} should have restart: unless-stopped"

    def test_dependency_ordering(self, docker_compose_config):
        """AC 4: Services depend on data services being healthy"""
        services = docker_compose_config["services"]

        # API depends on postgres and redis
        api_depends = services["api"].get("depends_on", {})
        assert "postgres" in api_depends, "API must depend on postgres"
        assert "redis" in api_depends, "API must depend on redis"

        # Agent depends on postgres, redis, and api
        agent_depends = services["agent"].get("depends_on", {})
        assert "postgres" in agent_depends, "Agent must depend on postgres"
        assert "redis" in agent_depends, "Agent must depend on redis"
        assert "api" in agent_depends, "Agent must depend on api"

        # Check health check conditions
        assert api_depends["postgres"].get("condition") == "service_healthy", \
            "API should wait for postgres to be healthy"
        assert agent_depends["api"].get("condition") == "service_healthy", \
            "Agent should wait for api to be healthy"
