"""Debugpy (Python) adapter configuration."""

from __future__ import annotations

import sys
from typing import TYPE_CHECKING
from typing import Any

from pydantic import Field

from mcp_dap.adapters.base import AdapterConfig
from mcp_dap.adapters.base import BaseAttachConfig
from mcp_dap.adapters.base import BaseLaunchConfig
from mcp_dap.adapters.base import adapter
from mcp_dap.dap.transport import SocketTransport
from mcp_dap.dap.transport import StdioTransport

if TYPE_CHECKING:
    from pathlib import Path

    from mcp_dap.dap.transport import DAPTransport


class DebugpyLaunchConfig(BaseLaunchConfig):
    """Launch configuration for Python debugpy adapter.

    Requires 'program' (path to .py file) from base config.
    """

    python_path: str | None = Field(
        default=None,
        description="Path to Python interpreter. Defaults to current interpreter.",
    )
    module: str | None = Field(
        default=None,
        description="Python module to run (alternative to program). Use -m style.",
    )
    just_my_code: bool = Field(
        default=True,
        description="Only debug user code, skip library code.",
    )
    django: bool = Field(
        default=False,
        description="Enable Django framework debugging support.",
    )
    flask: bool = Field(
        default=False,
        description="Enable Flask framework debugging support.",
    )


class DebugpyAttachConfig(BaseAttachConfig):
    """Attach configuration for Python debugpy adapter.

    Requires 'host' and 'port' from base config.
    """

    host: str | None = Field(
        default="127.0.0.1",
        description="Host to connect to (for remote attach).",
    )
    port: int | None = Field(
        default=None,
        description="Port to connect to (for remote attach).",
    )
    just_my_code: bool = Field(
        default=True,
        description="Only debug user code, skip library code.",
    )


@adapter(
    name="debugpy",
    adapter_id="debugpy",
    file_extensions=[".py", ".pyw"],
    aliases=["python"],
)
class DebugpyAdapter(AdapterConfig):
    """Python debugger. Use for .py files."""

    def __init__(self, python_path: str | None = None) -> None:
        """Initialize debugpy adapter.

        Args:
            python_path: Custom Python interpreter path. If not provided,
                        uses sys.executable.
        """
        self._python_path = python_path

    @property
    def launch_config_class(self) -> type[BaseLaunchConfig]:
        """Pydantic model class for launch configuration."""
        return DebugpyLaunchConfig

    @property
    def attach_config_class(self) -> type[BaseAttachConfig]:
        """Pydantic model class for attach configuration."""
        return DebugpyAttachConfig


    def get_info(self) -> dict[str, Any]:
        """Get adapter info including Python path."""
        info = super().get_info()
        info["python_path"] = self._python_path or sys.executable
        return info

    def create_transport(
        self,
        *,
        program: str | None = None,  # noqa: ARG002
        cwd: Path | str | None = None,
        env: dict[str, str] | None = None,
        host: str | None = None,
        port: int | None = None,
        **kwargs: Any,  # noqa: ARG002
    ) -> DAPTransport:
        """Create a transport for debugpy.

        For launch mode: spawns debugpy adapter subprocess
        For attach mode: connects to running debugpy server
        """
        if host is not None and port is not None:
            # Attach mode: connect to existing debugpy
            return SocketTransport(host, port)

        # Launch mode: spawn debugpy adapter
        # Use configured Python or fall back to current interpreter
        python = self._python_path or sys.executable
        command = [python, "-m", "debugpy.adapter"]

        return StdioTransport(
            command=command,
            cwd=cwd,
            env=env,
        )

    def get_launch_arguments(
        self,
        program: str,
        args: list[str] | None = None,
        cwd: str | None = None,
        env: dict[str, str] | None = None,
        stop_on_entry: bool = False,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Get launch arguments for debugpy."""
        arguments: dict[str, Any] = {
            "program": program,
            "args": args or [],
            # Use internalConsole for headless/MCP operation (no runInTerminal needed)
            "console": "internalConsole",
            "stopOnEntry": stop_on_entry,
            # Redirect output so we can capture it
            "redirectOutput": True,
        }

        if cwd is not None:
            arguments["cwd"] = cwd
        if env is not None:
            arguments["env"] = env

        # Add any additional debugpy-specific options
        arguments.update(kwargs)

        return arguments

    def get_attach_arguments(
        self,
        host: str,
        port: int,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Get attach arguments for debugpy."""
        return {
            "connect": {
                "host": host,
                "port": port,
            },
            **kwargs,
        }
