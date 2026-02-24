"""Tests for server configuration."""

from __future__ import annotations

import os
from typing import TYPE_CHECKING
from unittest import mock

import pytest

from mcp_dap.config import ServerConfig
from mcp_dap.config import load_config
from mcp_dap.config import reset_config

if TYPE_CHECKING:
    from collections.abc import Generator


@pytest.fixture(autouse=True)
def reset_config_fixture() -> Generator[None, None, None]:
    """Reset config before and after each test."""
    reset_config()
    yield
    reset_config()


class TestServerConfig:
    """Tests for ServerConfig."""

    def test_default_values(self) -> None:
        """Test default configuration values."""
        config = ServerConfig()

        assert config.log_level == "INFO"
        assert config.default_adapter == "debugpy"
        assert config.adapters == {}

    def test_env_var_override_log_level(self) -> None:
        """Test environment variable overrides."""
        with mock.patch.dict(os.environ, {"MCP_DAP_LOG_LEVEL": "DEBUG"}):
            config = ServerConfig()
            assert config.log_level == "DEBUG"

    def test_env_var_disable_adapter(self) -> None:
        """Test disabling adapter via environment variable."""
        with mock.patch.dict(
            os.environ, {"MCP_DAP_ADAPTERS__DEBUGPY__ENABLED": "false"}
        ):
            config = ServerConfig()
            # In a dict[str, dict[str, Any]], Pydantic might keep env vars as strings
            # and it will only contain the entries provided in env
            assert str(config.adapters["debugpy"]["enabled"]).lower() == "false"
            assert "codelldb" not in config.adapters

    def test_env_var_set_adapter_path(self) -> None:
        """Test setting adapter path via environment variable."""
        with mock.patch.dict(
            os.environ, {"MCP_DAP_ADAPTERS__CODELLDB__PATH": "/custom/codelldb"}
        ):
            config = ServerConfig()
            assert config.adapters["codelldb"]["path"] == "/custom/codelldb"


class TestAdapterRegistry:
    """Tests for adapter registry building."""

    def test_build_registry_all_enabled(self) -> None:
        """Test registry with all adapters enabled."""
        config = ServerConfig()
        registry = config.build_adapter_registry()

        # Should have debugpy and its alias
        assert "debugpy" in registry
        assert "python" in registry
        # Should have codelldb and its aliases
        assert "codelldb" in registry
        assert "lldb" in registry
        assert "rust" in registry

    def test_build_registry_debugpy_disabled(self) -> None:
        """Test registry with debugpy disabled."""
        with mock.patch.dict(
            os.environ, {"MCP_DAP_ADAPTERS__DEBUGPY__ENABLED": "false"}
        ):
            config = ServerConfig()
            registry = config.build_adapter_registry()

            assert "debugpy" not in registry
            assert "python" not in registry
            assert "codelldb" in registry

    def test_build_registry_codelldb_disabled(self) -> None:
        """Test registry with codelldb disabled."""
        with mock.patch.dict(
            os.environ, {"MCP_DAP_ADAPTERS__CODELLDB__ENABLED": "false"}
        ):
            config = ServerConfig()
            registry = config.build_adapter_registry()

            assert "debugpy" in registry
            assert "codelldb" not in registry
            assert "rust" not in registry


class TestAdapterInfo:
    """Tests for adapter info generation."""

    def test_get_adapter_info_structure(self) -> None:
        """Test adapter info structure."""
        config = ServerConfig()
        info = config.get_adapter_info()

        assert "adapters" in info
        assert "default" in info
        assert "config_sources" in info
        assert isinstance(info["adapters"], list)
        assert len(info["adapters"]) >= 1

    def test_get_adapter_info_includes_schema(self) -> None:
        """Test that adapter info includes launch config schema."""
        config = ServerConfig()
        info = config.get_adapter_info()

        for adapter_info in info["adapters"]:
            if adapter_info.get("enabled", True):  # Only enabled adapters have full info
                assert "launch_config" in adapter_info
                assert "properties" in adapter_info["launch_config"]

    def test_get_adapter_info_disabled_adapter(self) -> None:
        """Test adapter info shows disabled adapters."""
        with mock.patch.dict(
            os.environ, {"MCP_DAP_ADAPTERS__DEBUGPY__ENABLED": "false"}
        ):
            config = ServerConfig()
            info = config.get_adapter_info()

            # Find debugpy in the list
            debugpy_info = next(
                (a for a in info["adapters"] if a["name"] == "debugpy"), None
            )
            assert debugpy_info is not None
            assert debugpy_info.get("enabled") is False


class TestLoadConfig:
    """Tests for load_config function."""

    def test_load_config_returns_instance(self) -> None:
        """Test that load_config returns a ServerConfig instance."""
        config = load_config()
        assert isinstance(config, ServerConfig)

    def test_reset_config_clears_cache(self) -> None:
        """Test that reset_config clears the cached config."""
        from mcp_dap.config import get_config

        # First load caches the config
        _ = get_config()
        reset_config()

        # Modify env and get new config
        with mock.patch.dict(os.environ, {"MCP_DAP_LOG_LEVEL": "ERROR"}):
            config2 = get_config()
            assert config2.log_level == "ERROR"
