"""Delve adapter for Go debugging."""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import TYPE_CHECKING
from typing import Any

from pydantic import Field

from mcp_dap.adapters.base import AdapterConfig
from mcp_dap.adapters.base import BaseAttachConfig
from mcp_dap.adapters.base import BaseLaunchConfig
from mcp_dap.adapters.base import adapter
from mcp_dap.dap.transport import SubprocessSocketTransport
from mcp_dap.exceptions import AdapterNotFoundError
from mcp_dap.exceptions import MCPDAPError

if TYPE_CHECKING:
    from mcp_dap.dap.transport import DAPTransport


class DelveLaunchConfig(BaseLaunchConfig):
    """Launch configuration for Go debugging via Delve.

    Supports three modes:
    - debug: Build and debug a Go package (default).
    - test: Build and debug a Go test binary.
    - exec: Debug a pre-built Go binary (requires 'program' to be the binary path).
    """

    mode: str = Field(
        default="debug",
        description="Launch mode: 'debug' (build+debug package), 'test' (build+debug tests), "
        "'exec' (debug pre-built binary).",
    )
    build_flags: str = Field(
        default="",
        description="Flags passed to 'go build' (e.g., '-tags=integration -race').",
    )
    dlv_flags: list[str] = Field(
        default_factory=list,
        description="Extra flags passed to the dlv command (e.g., ['--check-go-version=false']).",
    )
    substitue_path: list[dict[str, str]] = Field(
        default_factory=list,
        description=(
            "Source path substitution rules. "
            "List of {'from': '/build/path', 'to': '/local/path'} dicts."
        ),
    )
    show_global_variables: bool = Field(
        default=False,
        description="Show global package variables in the variables pane.",
    )


class DelveAttachConfig(BaseAttachConfig):
    """Attach configuration for Go debugging via Delve.

    Supports two modes:
    - local: Attach to a running process by PID on the local machine.
    - remote: Connect to a headless Delve server (host:port).
    """

    mode: str = Field(
        default="local",
        description="Attach mode: 'local' (attach by PID) or 'remote' (connect to headless dlv).",
    )
    process_id: int | None = Field(
        default=None,
        description="Process ID to attach to (for local mode).",
    )


@adapter(
    name="godlv",
    adapter_id="go",
    file_extensions=[".go"],
    aliases=["go", "delve", "dlv"],
)
class DelveAdapter(AdapterConfig):
    """Go debugger (Delve). Use for .go files. Supports debug, test, and exec modes."""

    def __init__(self, dlv_path: str | None = None) -> None:
        """Initialize Delve adapter.

        Args:
            dlv_path: Explicit path to dlv binary. If not provided,
                     searches GOPATH/bin and PATH.
        """
        self._dlv_path = dlv_path

    @property
    def launch_config_class(self) -> type[BaseLaunchConfig]:
        """Pydantic model class for launch configuration."""
        return DelveLaunchConfig

    @property
    def attach_config_class(self) -> type[BaseAttachConfig]:
        """Pydantic model class for attach configuration."""
        return DelveAttachConfig

    def get_info(self) -> dict[str, Any]:
        """Get adapter info including dlv path and supported modes."""
        info = super().get_info()
        info["supported_modes"] = {
            "launch": ["debug", "test", "exec"],
            "attach": ["local", "remote"],
        }
        try:
            info["dlv_path"] = self.find_dlv()
        except AdapterNotFoundError:
            info["dlv_path"] = None
            info["install_instructions"] = (
                "Install Delve: go install github.com/go-delve/delve/cmd/dlv@latest"
            )
        return info

    def find_dlv(self) -> str:
        """Find the dlv binary.

        Returns:
            Path to the dlv binary.

        Raises:
            AdapterNotFoundError: If dlv is not found.
        """
        # 1. Explicit path
        if self._dlv_path:
            path = Path(self._dlv_path)
            if path.exists() and path.is_file():
                return str(path)
            raise AdapterNotFoundError(f"Delve not found at: {self._dlv_path}")

        # 2. GOPATH/bin or GOBIN
        gobin = self._find_gobin()
        if gobin:
            dlv_in_gobin = Path(gobin) / "dlv"
            if dlv_in_gobin.exists():
                return str(dlv_in_gobin)

        # 3. PATH
        dlv_in_path = shutil.which("dlv")
        if dlv_in_path:
            return dlv_in_path

        raise AdapterNotFoundError(
            "Delve (dlv) not found.\n\n"
            "Install Delve:\n"
            "  go install github.com/go-delve/delve/cmd/dlv@latest\n\n"
            "Or set the 'dlv_path' config to point to the dlv binary."
        )

    def create_transport(
        self,
        *,
        program: str | None = None,  # noqa: ARG002
        cwd: Path | str | None = None,
        env: dict[str, str] | None = None,
        host: str | None = None,  # noqa: ARG002
        port: int | None = None,  # noqa: ARG002
        **kwargs: Any,  # noqa: ARG002
    ) -> DAPTransport:
        """Create a transport for Delve.

        Spawns ``dlv dap --listen=host:port`` as a subprocess and connects via TCP.
        """
        dlv_path = self.find_dlv()

        command = [dlv_path, "dap"]

        return SubprocessSocketTransport(
            command=command,
            cwd=cwd,
            env=env,
            port_arg_template="--listen={host}:{port}",
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
        """Get launch arguments for Delve.

        Args:
            program: Path to the Go package directory or pre-built binary.
            args: Command line arguments for the program.
            cwd: Working directory for the program.
            env: Environment variables for the program.
            stop_on_entry: Stop at the entry point of the program.
            **kwargs: Additional Delve-specific options (mode, build_flags, etc.).

        Returns:
            DAP launch request arguments dict.
        """
        mode = kwargs.pop("mode", "debug")

        arguments: dict[str, Any] = {
            "request": "launch",
            "mode": mode,
            "program": program,
            "args": args or [],
            "stopOnEntry": stop_on_entry,
        }

        if cwd is not None:
            arguments["cwd"] = cwd
        if env is not None:
            arguments["env"] = env

        # Map Python-style kwargs to DAP properties
        build_flags = kwargs.pop("build_flags", None)
        if build_flags:
            arguments["buildFlags"] = build_flags

        substitute_path = kwargs.pop("substitute_path", None)
        if substitute_path is not None:
            arguments["substitutePath"] = substitute_path

        show_global_variables = kwargs.pop("show_global_variables", None)
        if show_global_variables is not None:
            arguments["showGlobalVariables"] = show_global_variables

        # Pass through any remaining kwargs directly
        arguments.update(kwargs)

        return arguments

    def get_attach_arguments(
        self,
        host: str,
        port: int,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Get attach arguments for Delve.

        Args:
            host: Host where Delve is running (used for remote mode).
            port: Port where Delve is running (used for remote mode).
            **kwargs: Additional Delve-specific options (mode, process_id, etc.).

        Returns:
            DAP attach request arguments dict.
        """
        mode = kwargs.pop("mode", "local")

        arguments: dict[str, Any] = {
            "request": "attach",
            "mode": mode,
        }

        if mode == "local":
            process_id = kwargs.pop("process_id", None) or kwargs.pop("pid", None)
            if process_id is None:
                raise MCPDAPError("Delve local attach requires 'process_id' or 'pid' argument")
            arguments["processId"] = process_id
        elif mode == "remote":
            arguments["host"] = host
            arguments["port"] = port

        substitute_path = kwargs.pop("substitute_path", None)
        if substitute_path is not None:
            arguments["substitutePath"] = substitute_path

        # Pass through any remaining kwargs directly
        arguments.update(kwargs)

        return arguments

    @staticmethod
    def _find_gobin() -> str | None:
        """Find GOBIN or GOPATH/bin directory.

        Returns:
            Path to the Go binary directory, or None if not found.
        """
        import os

        # Check GOBIN first
        gobin = os.environ.get("GOBIN")
        if gobin and Path(gobin).is_dir():
            return gobin

        # Check GOPATH/bin
        gopath = os.environ.get("GOPATH")
        if gopath:
            gobin_path = Path(gopath) / "bin"
            if gobin_path.is_dir():
                return str(gobin_path)

        # Default GOPATH is ~/go
        default_gobin = Path.home() / "go" / "bin"
        if default_gobin.is_dir():
            return str(default_gobin)

        return None
