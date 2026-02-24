"""CodeLLDB adapter for Rust/C/C++ debugging."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import TYPE_CHECKING
from typing import Any

from pydantic import Field

from mcp_dap.adapters.base import AdapterConfig
from mcp_dap.adapters.base import BaseAttachConfig
from mcp_dap.adapters.base import BaseLaunchConfig
from mcp_dap.adapters.base import adapter
from mcp_dap.dap.transport import StdioTransport
from mcp_dap.exceptions import AdapterNotFoundError
from mcp_dap.exceptions import MCPDAPError

if TYPE_CHECKING:
    from mcp_dap.dap.transport import DAPTransport


class CodeLLDBLaunchConfig(BaseLaunchConfig):
    """Launch configuration for Rust/C/C++ debugging via CodeLLDB.

    Supports two modes:
    - Direct launch: Provide 'program' (path to pre-built binary)
    - Cargo launch: Provide 'cargo_args' to build with cargo and debug the result
    """

    cargo_args: list[str] | None = Field(
        default=None,
        description=(
            "Cargo build arguments (e.g., ['build', '--bin', 'myapp']). "
            "If provided, builds with cargo and debugs the result. "
            "Mutually exclusive with 'program'."
        ),
    )
    source_languages: list[str] = Field(
        default_factory=lambda: ["rust"],
        description="Source languages for debugging (e.g., ['rust'], ['c', 'cpp']).",
    )
    init_commands: list[str] = Field(
        default_factory=list,
        description="LLDB commands to execute before launching.",
    )
    pre_run_commands: list[str] = Field(
        default_factory=list,
        description="LLDB commands to execute just before running the target.",
    )
    post_run_commands: list[str] = Field(
        default_factory=list,
        description="LLDB commands to execute after the target starts.",
    )
    exit_commands: list[str] = Field(
        default_factory=list,
        description="LLDB commands to execute when the debug session ends.",
    )


class CodeLLDBAttachConfig(BaseAttachConfig):
    """Attach configuration for Rust/C/C++ debugging via CodeLLDB.

    Supports attaching by PID or by executable name.
    """

    program: str | None = Field(
        default=None,
        description="Path to the program to debug.",
    )
    stop_on_entry: bool = Field(
        default=False,
        description="Stop at the entry point of the program.",
    )
    wait_for: bool = Field(
        default=False,
        description="Wait for a process with the specified name to start.",
    )


@adapter(
    name="codelldb",
    adapter_id="lldb",
    file_extensions=[".rs", ".c", ".cpp", ".cc", ".cxx", ".h", ".hpp"],
    aliases=["lldb", "rust"],
)
class CodeLLDBAdapter(AdapterConfig):
    """Rust/C/C++ debugger (LLDB). Use for Rust with cargo_args or pre-built binaries.

    Evaluate tip: in ``debug_evaluate`` with ``context='repl'``, prefix Rust expressions
    with ``?`` (for example, ``? cli.steps``). CodeLLDB treats bare input as an LLDB
    command, which can return command errors instead of expression results.
    """

    def __init__(self, codelldb_path: str | None = None) -> None:
        """Initialize CodeLLDB adapter.

        Args:
            codelldb_path: Explicit path to codelldb binary. If not provided,
                          searches VS Code extensions directory.
        """
        self._codelldb_path = codelldb_path

    @property
    def launch_config_class(self) -> type[BaseLaunchConfig]:
        """Pydantic model class for launch configuration."""
        return CodeLLDBLaunchConfig

    @property
    def attach_config_class(self) -> type[BaseAttachConfig]:
        """Pydantic model class for attach configuration."""
        return CodeLLDBAttachConfig

    def get_info(self) -> dict[str, Any]:
        """Get adapter info including cargo support."""
        info = super().get_info()
        info["supports_cargo"] = True
        info["cargo_args_example"] = ["build", "--bin", "myapp"]
        return info

    def find_codelldb(self) -> str:
        """Find the codelldb binary."""
        # 1. Explicit path
        if self._codelldb_path:
            path = Path(self._codelldb_path)
            if path.exists() and path.is_file():
                return str(path)
            raise AdapterNotFoundError(f"CodeLLDB not found at: {self._codelldb_path}")

        # 2. VS Code extensions directory
        vscode_dirs = [
            Path.home() / ".vscode" / "extensions",
            Path.home() / ".vscode-server" / "extensions",
            Path.home() / ".vscode-oss" / "extensions",
        ]

        for vscode_dir in vscode_dirs:
            if vscode_dir.exists():
                # Find vadimcn.vscode-lldb-* directories, sorted by version (newest first)
                lldb_dirs = sorted(
                    vscode_dir.glob("vadimcn.vscode-lldb-*"),
                    key=lambda p: p.name,
                    reverse=True,
                )
                for lldb_dir in lldb_dirs:
                    codelldb = lldb_dir / "adapter" / "codelldb"
                    if codelldb.exists():
                        return str(codelldb)

        # 3. Check PATH
        import shutil

        codelldb_in_path = shutil.which("codelldb")
        if codelldb_in_path:
            return codelldb_in_path

        raise AdapterNotFoundError(
            "CodeLLDB not found.\n\n"
            "Install the CodeLLDB VS Code extension:\n"
            "  1. Open VS Code\n"
            "  2. Install extension: vadimcn.vscode-lldb\n\n"
            "Or install codelldb manually and add to PATH."
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
        """Create a transport for CodeLLDB.

        Always uses stdio transport (spawns codelldb subprocess).
        """
        codelldb_path = self.find_codelldb()

        # codelldb with no arguments runs in stdio DAP mode
        command = [codelldb_path]

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
        """Get launch arguments for CodeLLDB."""
        arguments: dict[str, Any] = {
            "type": "lldb",
            "request": "launch",
            "program": program,
            "args": args or [],
            "stopOnEntry": stop_on_entry,
            # Enable Rust-specific features
            "sourceLanguages": ["rust"],
        }

        if cwd is not None:
            arguments["cwd"] = cwd
        if env is not None:
            arguments["env"] = env

        # Add any additional CodeLLDB-specific options
        arguments.update(kwargs)

        return arguments

    def get_attach_arguments(
        self,
        host: str,  # noqa: ARG002
        port: int,  # noqa: ARG002
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Get attach arguments for CodeLLDB."""
        pid = kwargs.get("pid")
        if pid is None:
            raise MCPDAPError("CodeLLDB attach requires 'pid' argument")

        return {
            "type": "lldb",
            "request": "attach",
            "pid": pid,
            **kwargs,
        }

    def build_with_cargo(
        self,
        cargo_args: list[str],
        cwd: str | None = None,
        env: dict[str, str] | None = None,
    ) -> str:
        """Build with cargo and return the executable path."""
        # Build the cargo command with JSON message format
        cmd = ["cargo", *cargo_args, "--message-format=json"]

        # Prepare environment
        run_env = dict(env) if env else None

        try:
            result = subprocess.run(
                cmd,
                cwd=cwd,
                env=run_env,
                capture_output=True,
                text=True,
                check=False,
            )
        except FileNotFoundError as e:
            raise MCPDAPError("cargo not found. Is Rust installed?") from e

        if result.returncode != 0:
            # Extract error message from stderr
            error_msg = result.stderr.strip() or "Unknown error"
            raise MCPDAPError(f"Cargo build failed:\n{error_msg}")

        # Parse JSON output to find the executable
        executable: str | None = None
        for line in result.stdout.splitlines():
            try:
                msg = json.loads(line)
            except json.JSONDecodeError:
                continue

            if msg.get("reason") == "compiler-artifact":
                # Check if this is an executable
                target = msg.get("target", {})
                if "bin" in target.get("kind", []) or "test" in target.get("kind", []):
                    # Get the executable path
                    filenames: list[str] = msg.get("filenames", [])
                    for filename in filenames:
                        # On Unix, executables don't have extension
                        # On Windows, they have .exe
                        if not filename.endswith((".rlib", ".rmeta", ".d")):
                            executable = filename
                            break

        if executable is None:
            raise MCPDAPError(
                "No executable found in cargo build output.\n"
                "Make sure you're building a binary target, not a library."
            )

        # Type narrowing: executable is now str (not None)
        return executable

    def get_cargo_launch_arguments(
        self,
        cargo_args: list[str],
        program_args: list[str] | None = None,
        cwd: str | None = None,
        env: dict[str, str] | None = None,
        stop_on_entry: bool = False,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Build with cargo and get launch arguments."""
        # Build with cargo
        executable = self.build_with_cargo(cargo_args, cwd=cwd, env=env)

        # Return launch arguments for the built executable
        return self.get_launch_arguments(
            program=executable,
            args=program_args,
            cwd=cwd,
            env=env,
            stop_on_entry=stop_on_entry,
            **kwargs,
        )
