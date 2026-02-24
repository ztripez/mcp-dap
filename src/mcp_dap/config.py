"""MCP-DAP server configuration."""

from __future__ import annotations

import os
from pathlib import Path
from typing import TYPE_CHECKING
from typing import Any

from pydantic import Field
from pydantic_settings import BaseSettings
from pydantic_settings import PydanticBaseSettingsSource
from pydantic_settings import SettingsConfigDict
from pydantic_settings import TomlConfigSettingsSource

if TYPE_CHECKING:
    from mcp_dap.adapters.base import AdapterConfig


class ServerConfig(BaseSettings):
    """MCP-DAP server configuration.

    Configuration is loaded from (in order of precedence):
    1. Environment variables (prefixed with MCP_DAP_)
    2. Config file (~/.config/mcp-dap/config.toml or ./mcp-dap.toml)
    3. Default values

    Environment variable examples:
        MCP_DAP_LOG_LEVEL=DEBUG
        MCP_DAP_ADAPTERS__DEBUGPY__ENABLED=false
        MCP_DAP_ADAPTERS__DEBUGPY__PYTHON_PATH=/usr/bin/python3
    """

    model_config = SettingsConfigDict(
        env_prefix="MCP_DAP_",
        env_nested_delimiter="__",
        toml_file=[
            Path("mcp-dap.toml"),
            Path.home() / ".config" / "mcp-dap" / "config.toml",
        ],
        extra="ignore",
    )

    # Dynamic adapter settings: adapter_name -> settings_dict
    adapters: dict[str, dict[str, Any]] = Field(
        default_factory=dict,
        description="Configuration for debug adapters.",
    )

    # Server settings
    log_level: str = Field(
        default="INFO",
        description="Logging level (DEBUG, INFO, WARNING, ERROR).",
    )
    default_adapter: str = Field(
        default="debugpy",
        description="Default adapter when none specified.",
    )

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,  # noqa: ARG003
        file_secret_settings: PydanticBaseSettingsSource,  # noqa: ARG003
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        """Customize settings sources to include TOML config files."""
        return (
            init_settings,
            env_settings,
            TomlConfigSettingsSource(settings_cls),
        )

    def build_adapter_registry(self) -> dict[str, AdapterConfig]:
        """Build the adapter registry based on configuration."""
        from mcp_dap.adapters.base import get_registered_adapters

        registry: dict[str, AdapterConfig] = {}
        registered_classes = get_registered_adapters()

        for name, cls in registered_classes.items():
            # Get settings for this adapter
            # Case-insensitive lookup (Pydantic env vars/TOML might vary)
            settings = None
            for key, val in self.adapters.items():
                if key.lower() == name.lower():
                    settings = val
                    break

            if settings is None:
                settings = {"enabled": True}  # Default if not mentioned

            if settings.get("enabled", True):
                adapter_instance = cls.from_config(settings)
                registry[name] = adapter_instance
                # Add aliases
                for alias in adapter_instance.aliases:
                    registry[alias] = adapter_instance

        return registry

    def get_adapter_info(self) -> dict[str, Any]:
        """Get information about configured adapters for MCP resource."""
        from mcp_dap.adapters.base import get_registered_adapters

        adapters_info: list[dict[str, Any]] = []
        registry = self.build_adapter_registry()
        registered_classes = get_registered_adapters()

        # Track processed adapters to avoid duplicates from aliases
        processed_names: set[str] = set()

        for name, cls in registered_classes.items():
            adapter_instance = registry.get(name)
            if adapter_instance:
                info = adapter_instance.get_info()
                info["enabled"] = True
                adapters_info.append(info)
                processed_names.add(name)
            else:
                # Disabled adapter
                # We need an instance just to call get_info(), or we can use the class
                # But get_info() is an instance method. Let's create a temporary instance.
                # Use default settings for metadata extraction
                try:
                    temp_instance = cls()
                    info = temp_instance.get_info()
                    info["enabled"] = False
                    adapters_info.append(info)
                    processed_names.add(name)
                except Exception:
                    # If constructor fails without args, provide minimal info
                    adapters_info.append({
                        "name": name,
                        "enabled": False,
                        "description": cls.__doc__ or "Disabled adapter",
                    })

        return {
            "adapters": adapters_info,
            "default": self.default_adapter,
            "config_sources": self._get_config_sources(),
        }

    def _get_config_sources(self) -> list[str]:
        """Get list of configuration sources that were loaded."""
        sources: list[str] = ["defaults"]

        # Check for config files
        config_paths = [
            Path("mcp-dap.toml"),
            Path.home() / ".config" / "mcp-dap" / "config.toml",
        ]
        for path in config_paths:
            if path.exists():
                sources.append(f"file:{path}")

        # Check for env vars
        for key in os.environ:
            if key.startswith("MCP_DAP_"):
                sources.append("environment")
                break

        return sources


def load_config() -> ServerConfig:
    """Load server configuration."""
    return ServerConfig()


# Global config instance (lazily loaded)
_config: ServerConfig | None = None


def get_config() -> ServerConfig:
    """Get the global configuration instance."""
    global _config
    if _config is None:
        _config = load_config()
    return _config


def reset_config() -> None:
    """Reset the global configuration (for testing)."""
    global _config
    _config = None
