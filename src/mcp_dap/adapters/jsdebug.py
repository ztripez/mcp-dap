"""js-debug adapter for JavaScript/TypeScript (Node.js) debugging."""

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

if TYPE_CHECKING:
    from mcp_dap.dap.transport import DAPTransport


class JsDebugLaunchConfig(BaseLaunchConfig):
    """Launch configuration for JavaScript/TypeScript debugging via js-debug.

    Requires 'program' (path to .js/.ts file) from base config.
    Uses the standalone js-debug-dap DAP server from vscode-js-debug.
    """

    runtime_executable: str | None = Field(
        default=None,
        description="Path to Node.js runtime. Defaults to 'node' on PATH.",
    )
    runtime_args: list[str] = Field(
        default_factory=list,
        description=(
            "Arguments passed to the runtime before the program. "
            "E.g., ['--loader', 'ts-node/esm'] for TypeScript."
        ),
    )
    source_maps: bool = Field(
        default=True,
        description="Enable source maps for TypeScript / transpiled code.",
    )
    out_files: list[str] = Field(
        default_factory=list,
        description=(
            "Glob patterns for compiled output files (for TypeScript). "
            "E.g., ['${workspaceFolder}/dist/**/*.js']."
        ),
    )
    skip_files: list[str] = Field(
        default_factory=list,
        description="Glob patterns for files to skip during debugging. E.g., ['<node_internals>/**'].",
    )
    resolve_source_map_locations: list[str] = Field(
        default_factory=list,
        description="Glob patterns for locations to search for source maps.",
    )


class JsDebugAttachConfig(BaseAttachConfig):
    """Attach configuration for JavaScript/TypeScript debugging via js-debug.

    Connects to a Node.js process started with --inspect or --inspect-brk.
    Default inspect port is 9229.
    """

    host: str | None = Field(
        default="127.0.0.1",
        description="Host where the Node.js inspector is listening.",
    )
    port: int | None = Field(
        default=9229,
        description="Port where the Node.js inspector is listening (default: 9229).",
    )
    source_maps: bool = Field(
        default=True,
        description="Enable source maps for TypeScript / transpiled code.",
    )
    skip_files: list[str] = Field(
        default_factory=list,
        description="Glob patterns for files to skip during debugging.",
    )
    restart: bool = Field(
        default=False,
        description="Automatically reconnect if the debuggee restarts.",
    )


# Search paths for the standalone js-debug-dap installation.
# The entry point is dapDebugServer.js inside the extracted tarball.
_JSDEBUG_SEARCH_PATHS = [
    # Standard user-level install for mcp-dap
    Path.home() / ".local" / "share" / "mcp-dap" / "js-debug" / "src" / "dapDebugServer.js",
    # XDG data home
    Path.home() / ".local" / "share" / "js-debug-dap" / "js-debug" / "src" / "dapDebugServer.js",
    # Extracted tarball in home directory
    Path.home() / "js-debug" / "src" / "dapDebugServer.js",
]

# VS Code extension directories to search for the bundled js-debug
_VSCODE_EXTENSION_DIRS = [
    Path.home() / ".vscode" / "extensions",
    Path.home() / ".vscode-server" / "extensions",
    Path.home() / ".vscode-oss" / "extensions",
]

# System-level VS Code bundled extension
_SYSTEM_VSCODE_JSDEBUG = Path(
    "/opt/visual-studio-code/resources/app/extensions/ms-vscode.js-debug/src/dapDebugServer.js"
)


@adapter(
    name="jsdebug",
    adapter_id="pwa-node",
    file_extensions=[".js", ".ts", ".mjs", ".cjs", ".mts", ".cts"],
    aliases=["node", "javascript", "typescript", "js", "ts"],
)
class JsDebugAdapter(AdapterConfig):
    """JavaScript/TypeScript debugger (Node.js). Use for .js/.ts files with Node.js runtime."""

    def __init__(
        self,
        jsdebug_path: str | None = None,
        node_path: str | None = None,
    ) -> None:
        """Initialize js-debug adapter.

        Args:
            jsdebug_path: Explicit path to dapDebugServer.js. If not provided,
                         searches standard locations automatically.
            node_path: Path to Node.js binary. If not provided, uses 'node' from PATH.
        """
        self._jsdebug_path = jsdebug_path
        self._node_path = node_path

    @property
    def launch_config_class(self) -> type[BaseLaunchConfig]:
        """Pydantic model class for launch configuration."""
        return JsDebugLaunchConfig

    @property
    def attach_config_class(self) -> type[BaseAttachConfig]:
        """Pydantic model class for attach configuration."""
        return JsDebugAttachConfig

    def get_info(self) -> dict[str, Any]:
        """Get adapter info including js-debug and Node.js paths."""
        info = super().get_info()
        info["node_path"] = self._node_path or shutil.which("node") or "node"
        try:
            info["jsdebug_path"] = self.find_jsdebug()
        except AdapterNotFoundError:
            info["jsdebug_path"] = None
            info["install_instructions"] = (
                "Download js-debug-dap from "
                "https://github.com/microsoft/vscode-js-debug/releases "
                "and extract to ~/.local/share/mcp-dap/js-debug/"
            )
        return info

    def find_node(self) -> str:
        """Find the Node.js binary.

        Returns:
            Path to the Node.js binary.

        Raises:
            AdapterNotFoundError: If Node.js is not found.
        """
        if self._node_path:
            path = Path(self._node_path)
            if path.exists() and path.is_file():
                return str(path)
            raise AdapterNotFoundError(f"Node.js not found at: {self._node_path}")

        node_in_path = shutil.which("node")
        if node_in_path:
            return node_in_path

        raise AdapterNotFoundError(
            "Node.js not found.\n\n"
            "Install Node.js:\n"
            "  https://nodejs.org/ or via your package manager"
        )

    def find_jsdebug(self) -> str:
        """Find the dapDebugServer.js entry point.

        Returns:
            Path to dapDebugServer.js.

        Raises:
            AdapterNotFoundError: If js-debug-dap is not found.
        """
        # 1. Explicit path
        if self._jsdebug_path:
            path = Path(self._jsdebug_path)
            if path.exists() and path.is_file():
                return str(path)
            raise AdapterNotFoundError(f"js-debug not found at: {self._jsdebug_path}")

        # 2. Standard standalone install paths
        for search_path in _JSDEBUG_SEARCH_PATHS:
            if search_path.exists():
                return str(search_path)

        # 3. VS Code user extensions (look for ms-vscode.js-debug-* with dapDebugServer.js)
        for vscode_dir in _VSCODE_EXTENSION_DIRS:
            if vscode_dir.exists():
                jsdebug_dirs = sorted(
                    vscode_dir.glob("ms-vscode.js-debug-*"),
                    key=lambda p: p.name,
                    reverse=True,
                )
                for jsdebug_dir in jsdebug_dirs:
                    server = jsdebug_dir / "src" / "dapDebugServer.js"
                    if server.exists():
                        return str(server)

        # 4. System VS Code bundled extension
        if _SYSTEM_VSCODE_JSDEBUG.exists():
            return str(_SYSTEM_VSCODE_JSDEBUG)

        raise AdapterNotFoundError(
            "js-debug (dapDebugServer.js) not found.\n\n"
            "Install the standalone js-debug-dap:\n"
            "  1. Download from: https://github.com/microsoft/vscode-js-debug/releases\n"
            "  2. Extract the js-debug-dap-*.tar.gz archive\n"
            "  3. Move the 'js-debug' directory to: ~/.local/share/mcp-dap/js-debug/\n\n"
            "Or set the 'jsdebug_path' config to point to dapDebugServer.js."
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
        """Create a transport for js-debug.

        Spawns dapDebugServer.js as a subprocess and connects via TCP socket.
        The server listens on a dynamically allocated port.
        """
        node_path = self.find_node()
        jsdebug_path = self.find_jsdebug()

        command = [node_path, jsdebug_path]

        return SubprocessSocketTransport(
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
        """Get launch arguments for js-debug (Node.js).

        Args:
            program: Path to the JavaScript/TypeScript file to debug.
            args: Command line arguments for the program.
            cwd: Working directory for the program.
            env: Environment variables for the program.
            stop_on_entry: Stop at the entry point of the program.
            **kwargs: Additional js-debug-specific options (runtime_executable,
                     runtime_args, source_maps, out_files, skip_files, etc.).

        Returns:
            DAP launch request arguments dict.
        """
        arguments: dict[str, Any] = {
            "type": "pwa-node",
            "request": "launch",
            "program": program,
            "args": args or [],
            "stopOnEntry": stop_on_entry,
            # Use internalConsole for headless/MCP operation
            "console": "internalConsole",
            # Enable source maps by default
            "sourceMaps": kwargs.pop("source_maps", True),
        }

        if cwd is not None:
            arguments["cwd"] = cwd
        if env is not None:
            arguments["env"] = env

        # Map Python-style kwargs to camelCase DAP properties
        runtime_executable = kwargs.pop("runtime_executable", None)
        if runtime_executable is not None:
            arguments["runtimeExecutable"] = runtime_executable

        runtime_args = kwargs.pop("runtime_args", None)
        if runtime_args is not None:
            arguments["runtimeArgs"] = runtime_args

        out_files = kwargs.pop("out_files", None)
        if out_files is not None:
            arguments["outFiles"] = out_files

        skip_files = kwargs.pop("skip_files", None)
        if skip_files is not None:
            arguments["skipFiles"] = skip_files

        resolve_source_map_locations = kwargs.pop("resolve_source_map_locations", None)
        if resolve_source_map_locations is not None:
            arguments["resolveSourceMapLocations"] = resolve_source_map_locations

        # Pass through any remaining kwargs directly
        arguments.update(kwargs)

        return arguments

    def get_attach_arguments(
        self,
        host: str,
        port: int,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Get attach arguments for js-debug (Node.js).

        Args:
            host: Host where the Node.js inspector is listening.
            port: Port where the Node.js inspector is listening.
            **kwargs: Additional js-debug-specific options.

        Returns:
            DAP attach request arguments dict.
        """
        arguments: dict[str, Any] = {
            "type": "pwa-node",
            "request": "attach",
            "address": host,
            "port": port,
            # Enable source maps by default
            "sourceMaps": kwargs.pop("source_maps", True),
        }

        skip_files = kwargs.pop("skip_files", None)
        if skip_files is not None:
            arguments["skipFiles"] = skip_files

        restart = kwargs.pop("restart", None)
        if restart is not None:
            arguments["restart"] = restart

        # Pass through any remaining kwargs directly
        arguments.update(kwargs)

        return arguments
