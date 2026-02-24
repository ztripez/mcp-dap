"""Java debug adapter using java-debug-core with a standalone launcher."""

from __future__ import annotations

import shutil
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


# Path to the bundled StandaloneLauncher.java source
_LAUNCHER_SOURCE = Path(__file__).parent / "java_resources" / "StandaloneLauncher.java"

# VS Code extension directory for java-debug
_VSCODE_JAVA_DEBUG_PATTERN = "vscjava.vscode-java-debug-*"

# JAR names needed from the java-debug extension
_CORE_JAR_PREFIX = "com.microsoft.java.debug.plugin-"
_REQUIRED_LIBS = [
    "com.microsoft.java.debug.core-",
    "rxjava-",
    "reactive-streams-",
    "commons-io-",
]

# Gson can come from various VS Code extensions
_GSON_PATTERNS = [
    "vscjava.vscode-gradle-*/lib/gson-*.jar",
    "vscjava.vscode-java-test-*/lib/gson-*.jar",
    "vscjava.vscode-java-dependency-*/lib/gson-*.jar",
]


class JavaDebugLaunchConfig(BaseLaunchConfig):
    """Launch configuration for Java debugging.

    For launch mode, the adapter compiles (if needed) and starts the JVM
    with JDWP enabled, then connects the debugger.
    """

    main_class: str | None = Field(
        default=None,
        description="Fully qualified main class name (e.g., 'com.example.Main'). "
        "Auto-detected from 'program' if not specified.",
    )
    class_paths: list[str] = Field(
        default_factory=list,
        description="Classpath entries (directories or JAR files).",
    )
    module_paths: list[str] = Field(
        default_factory=list,
        description="Module path entries (for Java 9+ modules).",
    )
    vm_args: str = Field(
        default="",
        description="JVM arguments (e.g., '-Xmx512m -ea').",
    )
    project_name: str | None = Field(
        default=None,
        description="Project name for source lookup.",
    )
    encoding: str = Field(
        default="UTF-8",
        description="File encoding for the JVM.",
    )


class JavaDebugAttachConfig(BaseAttachConfig):
    """Attach configuration for Java debugging.

    Connects to a JVM that was started with JDWP:
    ``java -agentlib:jdwp=transport=dt_socket,server=y,address=*:5005 ...``
    """

    host: str | None = Field(
        default="127.0.0.1",
        description="Host where the JVM's JDWP agent is listening.",
    )
    port: int | None = Field(
        default=5005,
        description="Port where the JVM's JDWP agent is listening (default: 5005).",
    )
    project_name: str | None = Field(
        default=None,
        description="Project name for source lookup.",
    )


@adapter(
    name="javadebug",
    adapter_id="java",
    file_extensions=[".java"],
    aliases=["java", "jvm"],
)
class JavaDebugAdapter(AdapterConfig):
    """Java debugger. Use for .java files. Requires java-debug VS Code extension JARs."""

    def __init__(
        self,
        java_home: str | None = None,
        java_debug_jar_dir: str | None = None,
    ) -> None:
        """Initialize Java debug adapter.

        Args:
            java_home: Path to JDK home. If not provided, uses JAVA_HOME or PATH.
            java_debug_jar_dir: Directory containing java-debug-core JARs.
                               If not provided, searches VS Code extensions.
        """
        self._java_home = java_home
        self._java_debug_jar_dir = java_debug_jar_dir
        self._compiled_launcher_dir: Path | None = None

    @property
    def launch_config_class(self) -> type[BaseLaunchConfig]:
        """Pydantic model class for launch configuration."""
        return JavaDebugLaunchConfig

    @property
    def attach_config_class(self) -> type[BaseAttachConfig]:
        """Pydantic model class for attach configuration."""
        return JavaDebugAttachConfig

    def get_info(self) -> dict[str, Any]:
        """Get adapter info including Java and JAR paths."""
        info = super().get_info()
        try:
            info["java_path"] = self.find_java()
        except AdapterNotFoundError:
            info["java_path"] = None
        try:
            info["jar_dir"] = str(self.find_java_debug_jars())
        except AdapterNotFoundError:
            info["jar_dir"] = None
            info["install_instructions"] = (
                "Install the Java Debugger VS Code extension: "
                "ext install vscjava.vscode-java-debug"
            )
        return info

    def find_java(self) -> str:
        """Find the Java binary (must be JDK, not JRE).

        Returns:
            Path to the java binary.

        Raises:
            AdapterNotFoundError: If Java is not found.
        """
        # 1. Explicit java_home
        if self._java_home:
            java_bin = Path(self._java_home) / "bin" / "java"
            if java_bin.exists():
                return str(java_bin)
            raise AdapterNotFoundError(f"Java not found at: {java_bin}")

        # 2. JAVA_HOME environment variable
        import os

        java_home = os.environ.get("JAVA_HOME")
        if java_home:
            java_bin = Path(java_home) / "bin" / "java"
            if java_bin.exists():
                return str(java_bin)

        # 3. PATH
        java_in_path = shutil.which("java")
        if java_in_path:
            return java_in_path

        raise AdapterNotFoundError(
            "Java (JDK) not found.\n\n"
            "Install a JDK and set JAVA_HOME, or add java to PATH."
        )

    def find_javac(self) -> str:
        """Find the javac compiler binary.

        Returns:
            Path to the javac binary.

        Raises:
            AdapterNotFoundError: If javac is not found.
        """
        java_path = self.find_java()
        javac_path = str(Path(java_path).parent / "javac")
        if Path(javac_path).exists():
            return javac_path

        javac_in_path = shutil.which("javac")
        if javac_in_path:
            return javac_in_path

        raise AdapterNotFoundError(
            "javac not found. Make sure you have a JDK (not just a JRE) installed."
        )

    def find_java_debug_jars(self) -> Path:
        """Find the java-debug-core JARs.

        Returns:
            Path to directory containing the required JARs.

        Raises:
            AdapterNotFoundError: If JARs are not found.
        """
        # 1. Explicit directory
        if self._java_debug_jar_dir:
            jar_dir = Path(self._java_debug_jar_dir)
            if jar_dir.is_dir():
                return jar_dir
            raise AdapterNotFoundError(
                f"Java debug JARs not found at: {self._java_debug_jar_dir}"
            )

        # 2. Cached extraction directory
        cache_dir = Path.home() / ".cache" / "mcp-dap" / "java-debug"
        if cache_dir.is_dir() and self._has_required_jars(cache_dir):
            return cache_dir

        # 3. Extract from VS Code extension
        extracted = self._extract_jars_from_extension(cache_dir)
        if extracted:
            return cache_dir

        raise AdapterNotFoundError(
            "java-debug-core JARs not found.\n\n"
            "Install the Java Debugger VS Code extension:\n"
            "  code --install-extension vscjava.vscode-java-debug\n\n"
            "Or set 'java_debug_jar_dir' config to a directory containing the JARs."
        )

    def _has_required_jars(self, jar_dir: Path) -> bool:
        """Check if directory has all required JARs."""
        jars = [f.name for f in jar_dir.glob("*.jar")]
        for prefix in _REQUIRED_LIBS:
            if not any(j.startswith(prefix) for j in jars):
                return False
        # Also need gson
        return any("gson" in j for j in jars)

    def _extract_jars_from_extension(self, target_dir: Path) -> bool:
        """Extract required JARs from VS Code java-debug extension.

        Args:
            target_dir: Directory to extract JARs to.

        Returns:
            True if extraction succeeded.
        """
        import zipfile

        vscode_dirs = [
            Path.home() / ".vscode" / "extensions",
            Path.home() / ".vscode-server" / "extensions",
            Path.home() / ".vscode-oss" / "extensions",
        ]

        # Find the java-debug extension
        plugin_jar: Path | None = None
        for vscode_dir in vscode_dirs:
            if not vscode_dir.exists():
                continue
            ext_dirs = sorted(
                vscode_dir.glob(_VSCODE_JAVA_DEBUG_PATTERN),
                key=lambda p: p.name,
                reverse=True,
            )
            for ext_dir in ext_dirs:
                server_dir = ext_dir / "server"
                if server_dir.exists():
                    jars = list(server_dir.glob(f"{_CORE_JAR_PREFIX}*.jar"))
                    if jars:
                        plugin_jar = jars[0]
                        break
            if plugin_jar:
                break

        if plugin_jar is None:
            return False

        # Extract lib/ JARs from the plugin JAR
        target_dir.mkdir(parents=True, exist_ok=True)
        try:
            with zipfile.ZipFile(plugin_jar) as zf:
                for entry in zf.namelist():
                    if entry.startswith("lib/") and entry.endswith(".jar"):
                        data = zf.read(entry)
                        jar_name = Path(entry).name
                        (target_dir / jar_name).write_bytes(data)
        except (zipfile.BadZipFile, OSError):
            return False

        # Find and copy gson from other VS Code extensions
        if not any("gson" in f.name for f in target_dir.glob("*.jar")):
            for vscode_dir in vscode_dirs:
                if not vscode_dir.exists():
                    continue
                for pattern in _GSON_PATTERNS:
                    gsons = list(vscode_dir.glob(pattern))
                    if gsons:
                        # Use newest version
                        gson_jar = sorted(gsons, key=lambda p: p.name, reverse=True)[0]
                        shutil.copy2(gson_jar, target_dir / gson_jar.name)
                        break
                if any("gson" in f.name for f in target_dir.glob("*.jar")):
                    break

        return self._has_required_jars(target_dir)

    def _ensure_launcher_compiled(self) -> Path:
        """Compile the StandaloneLauncher.java if not already compiled.

        Returns:
            Path to the directory containing the compiled .class file.

        Raises:
            MCPDAPError: If compilation fails.
        """
        if self._compiled_launcher_dir and (
            self._compiled_launcher_dir / "StandaloneLauncher.class"
        ).exists():
            return self._compiled_launcher_dir

        cache_dir = Path.home() / ".cache" / "mcp-dap" / "java-debug"
        class_file = cache_dir / "StandaloneLauncher.class"

        # Check if already compiled and up to date
        if (
            class_file.exists()
            and _LAUNCHER_SOURCE.exists()
            and class_file.stat().st_mtime > _LAUNCHER_SOURCE.stat().st_mtime
        ):
            self._compiled_launcher_dir = cache_dir
            return cache_dir

        # Compile
        javac_path = self.find_javac()
        jar_dir = self.find_java_debug_jars()
        classpath = ":".join(str(j) for j in jar_dir.glob("*.jar"))

        result = subprocess.run(
            [
                javac_path,
                "--add-modules", "jdk.jdi",
                "-cp", classpath,
                "-d", str(cache_dir),
                str(_LAUNCHER_SOURCE),
            ],
            capture_output=True,
            text=True,
            check=False,
        )

        if result.returncode != 0:
            raise MCPDAPError(
                f"Failed to compile Java debug launcher:\n{result.stderr}"
            )

        self._compiled_launcher_dir = cache_dir
        return cache_dir

    def _build_classpath(self) -> str:
        """Build the full classpath for the standalone launcher."""
        jar_dir = self.find_java_debug_jars()
        launcher_dir = self._ensure_launcher_compiled()

        parts = [str(launcher_dir)]
        parts.extend(str(j) for j in jar_dir.glob("*.jar"))
        return ":".join(parts)

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
        """Create a transport for the Java debug adapter.

        Spawns the StandaloneLauncher as a subprocess communicating via stdio.
        """
        java_path = self.find_java()
        classpath = self._build_classpath()

        command = [
            java_path,
            "--add-modules", "jdk.jdi",
            "-Dfile.encoding=UTF-8",
            "-cp", classpath,
            "StandaloneLauncher",
        ]

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
        """Get launch arguments for Java debugging.

        Args:
            program: Path to the .java file or project directory.
            args: Command line arguments for the program.
            cwd: Working directory for the program.
            env: Environment variables for the program.
            stop_on_entry: Stop at the entry point of the program.
            **kwargs: Additional options (main_class, class_paths, vm_args, etc.).

        Returns:
            DAP launch request arguments dict.
        """
        main_class = kwargs.pop("main_class", None)
        class_paths = kwargs.pop("class_paths", None)
        module_paths = kwargs.pop("module_paths", None)
        vm_args = kwargs.pop("vm_args", "")
        encoding = kwargs.pop("encoding", "UTF-8")
        project_name = kwargs.pop("project_name", None)

        arguments: dict[str, Any] = {
            "type": "java",
            "request": "launch",
            "stopOnEntry": stop_on_entry,
        }

        # Determine main class from program path if not explicitly provided
        if main_class:
            arguments["mainClass"] = main_class
        else:
            arguments["mainClass"] = self._infer_main_class(program)

        if class_paths:
            arguments["classPaths"] = class_paths
        else:
            # Default: use the program's parent directory
            arguments["classPaths"] = [str(Path(program).parent)]

        if module_paths:
            arguments["modulePaths"] = module_paths

        arguments["args"] = " ".join(args) if args else ""

        if cwd is not None:
            arguments["cwd"] = cwd
        if env is not None:
            arguments["env"] = env
        if vm_args:
            arguments["vmArgs"] = vm_args

        arguments["encoding"] = encoding

        if project_name:
            arguments["projectName"] = project_name

        # Pass through remaining kwargs
        arguments.update(kwargs)

        return arguments

    def get_attach_arguments(
        self,
        host: str,
        port: int,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Get attach arguments for Java debugging.

        Args:
            host: Host where the JVM's JDWP agent is listening.
            port: Port where the JVM's JDWP agent is listening.
            **kwargs: Additional options (project_name, etc.).

        Returns:
            DAP attach request arguments dict.
        """
        arguments: dict[str, Any] = {
            "type": "java",
            "request": "attach",
            "hostName": host,
            "port": port,
        }

        project_name = kwargs.pop("project_name", None)
        if project_name:
            arguments["projectName"] = project_name

        # Pass through remaining kwargs
        arguments.update(kwargs)

        return arguments

    @staticmethod
    def _infer_main_class(program: str) -> str:
        """Infer the main class name from a .java file path.

        Reads the file's package declaration to build the fully qualified name.

        Args:
            program: Path to a .java file.

        Returns:
            Fully qualified class name.
        """
        path = Path(program)
        class_name = path.stem  # filename without .java

        # Try to read the package declaration
        try:
            source = path.read_text(encoding="utf-8")
            for line in source.splitlines():
                stripped = line.strip()
                if stripped.startswith("package "):
                    package = stripped[8:].rstrip(";").strip()
                    return f"{package}.{class_name}"
                if stripped.startswith(("import ", "public ", "class ", "abstract ")):
                    break
        except OSError:
            pass

        return class_name
