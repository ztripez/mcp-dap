"""Base adapter configuration."""

from __future__ import annotations

import inspect
from abc import ABC
from abc import abstractmethod
from typing import TYPE_CHECKING
from typing import Any
from typing import TypeVar

from pydantic import BaseModel
from pydantic import Field

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from mcp_dap.dap.transport import DAPTransport

T = TypeVar("T", bound="AdapterConfig")

# Global registry of adapter classes
_ADAPTER_REGISTRY: dict[str, type[AdapterConfig]] = {}
_ADAPTER_ALIASES: dict[str, str] = {}


def adapter(
    name: str,
    adapter_id: str,
    file_extensions: list[str],
    aliases: list[str] | None = None,
) -> Callable[[type[T]], type[T]]:
    """Decorator to register a debug adapter class.

    Args:
        name: Primary name of the adapter.
        adapter_id: DAP adapter ID (e.g., 'debugpy', 'lldb').
        file_extensions: List of file extensions this adapter handles.
        aliases: Optional list of alternate names for this adapter.
    """

    def decorator(cls: type[T]) -> type[T]:
        cls.name = name
        cls.adapter_id = adapter_id
        cls.file_extensions = file_extensions
        cls.aliases = aliases or []

        _ADAPTER_REGISTRY[name] = cls
        for alias in cls.aliases:
            _ADAPTER_ALIASES[alias] = name

        return cls

    return decorator


def get_registered_adapters() -> dict[str, type[AdapterConfig]]:
    """Get all registered adapter classes."""
    return _ADAPTER_REGISTRY.copy()


def get_adapter_aliases() -> dict[str, str]:
    """Get mapping of aliases to primary adapter names."""
    return _ADAPTER_ALIASES.copy()


class BaseLaunchConfig(BaseModel):
    """Base launch configuration shared by all adapters."""

    program: str | None = Field(
        default=None,
        description="Path to the program to debug.",
    )
    args: list[str] = Field(
        default_factory=list,
        description="Command line arguments for the program.",
    )
    cwd: str | None = Field(
        default=None,
        description="Working directory for the program.",
    )
    env: dict[str, str] = Field(
        default_factory=dict,
        description="Environment variables for the program.",
    )
    stop_on_entry: bool = Field(
        default=False,
        description="Stop at the entry point of the program.",
    )


class BaseAttachConfig(BaseModel):
    """Base attach configuration shared by all adapters."""

    host: str | None = Field(
        default=None,
        description="Host to connect to (for remote attach).",
    )
    port: int | None = Field(
        default=None,
        description="Port to connect to (for remote attach).",
    )
    pid: int | None = Field(
        default=None,
        description="Process ID to attach to (for local attach).",
    )


class AdapterConfig(ABC):
    """Abstract base class for debug adapter configurations."""

    # These are set by the @adapter decorator
    name: str
    adapter_id: str
    file_extensions: list[str]
    aliases: list[str]

    @property
    def description(self) -> str:
        """Human-readable description taken from the class docstring."""
        doc = self.__class__.__doc__
        return inspect.cleandoc(doc) if doc else ""

    @property
    @abstractmethod
    def launch_config_class(self) -> type[BaseLaunchConfig]:
        """Pydantic model class for launch configuration."""

    @property
    @abstractmethod
    def attach_config_class(self) -> type[BaseAttachConfig]:
        """Pydantic model class for attach configuration."""

    @classmethod
    def from_config(cls, config: dict[str, Any]) -> AdapterConfig:
        """Create an adapter instance from a configuration dictionary.

        Default implementation passes all keys (except 'enabled') to the constructor.
        """
        cfg = config.copy()
        cfg.pop("enabled", None)
        return cls(**cfg)

    def get_info(self) -> dict[str, Any]:
        """Get adapter info for MCP resource exposure.

        Returns:
            Dict with name, description, file_extensions, config schema, and capabilities.
        """
        return {
            "name": self.name,
            "adapter_id": self.adapter_id,
            "description": self.description,
            "file_extensions": self.file_extensions,
            "aliases": self.aliases,
            "launch_config": self.launch_config_class.model_json_schema(),
            "attach_config": self.attach_config_class.model_json_schema(),
        }

    @abstractmethod
    def create_transport(
        self,
        *,
        program: str | None = None,
        cwd: Path | str | None = None,
        env: dict[str, str] | None = None,
        host: str | None = None,
        port: int | None = None,
        **kwargs: Any,
    ) -> DAPTransport:
        """Create a transport for this adapter."""

    @abstractmethod
    def get_launch_arguments(
        self,
        program: str,
        args: list[str] | None = None,
        cwd: str | None = None,
        env: dict[str, str] | None = None,
        stop_on_entry: bool = False,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Get launch request arguments for this adapter."""

    @abstractmethod
    def get_attach_arguments(
        self,
        host: str,
        port: int,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Get attach request arguments for this adapter."""
