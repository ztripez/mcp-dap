"""DAP transport implementations.

Supports two transport modes:
- StdioTransport: Spawn adapter as subprocess, communicate via stdin/stdout
- SocketTransport: Connect to adapter running on a TCP socket
"""

from __future__ import annotations

import asyncio
from abc import ABC
from abc import abstractmethod
from typing import TYPE_CHECKING
from typing import Any

import anyio
from anyio.streams.buffered import BufferedByteReceiveStream

from mcp_dap.dap.protocol import HEADER_SEPARATOR
from mcp_dap.dap.protocol import decode_message
from mcp_dap.dap.protocol import encode_message
from mcp_dap.dap.protocol import parse_content_length
from mcp_dap.exceptions import DAPConnectionError
from mcp_dap.exceptions import DAPProtocolError

if TYPE_CHECKING:
    from pathlib import Path

    from anyio.abc import ByteSendStream


class DAPTransport(ABC):
    """Abstract base class for DAP transports."""

    @abstractmethod
    async def connect(self) -> None:
        """Establish connection to the debug adapter."""

    @abstractmethod
    async def disconnect(self) -> None:
        """Close connection to the debug adapter."""

    @abstractmethod
    async def send(self, message: dict[str, Any]) -> None:
        """Send a message to the debug adapter."""

    @abstractmethod
    async def receive(self) -> dict[str, Any]:
        """Receive a message from the debug adapter."""

    @property
    @abstractmethod
    def is_connected(self) -> bool:
        """Check if the transport is connected."""


class StdioTransport(DAPTransport):
    """Transport that spawns adapter as subprocess and uses stdio."""

    def __init__(
        self,
        command: list[str],
        cwd: Path | str | None = None,
        env: dict[str, str] | None = None,
    ) -> None:
        """Initialize stdio transport.

        Args:
            command: Command to spawn the adapter (e.g., ["python", "-m", "debugpy.adapter"])
            cwd: Working directory for the subprocess
            env: Environment variables for the subprocess
        """
        self._command = command
        self._cwd = cwd
        self._env = env
        self._process: anyio.abc.Process | None = None
        self._stdin: ByteSendStream | None = None
        self._stdout: BufferedByteReceiveStream | None = None
        self._connected = False
        self._read_buffer = b""  # Persistent buffer for excess data

    async def connect(self) -> None:
        """Spawn the debug adapter subprocess."""
        if self._connected:
            return

        try:
            self._process = await anyio.open_process(
                self._command,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=self._cwd,
                env=self._env,
            )
            # Type assertions for mypy
            assert self._process.stdin is not None
            assert self._process.stdout is not None
            self._stdin = self._process.stdin
            self._stdout = BufferedByteReceiveStream(self._process.stdout)
            self._connected = True
        except OSError as e:
            raise DAPConnectionError(f"Failed to spawn adapter: {e}") from e

    async def disconnect(self) -> None:
        """Terminate the adapter subprocess."""
        import contextlib

        if self._process is not None:
            with contextlib.suppress(ProcessLookupError):
                self._process.terminate()
            try:
                # Wait briefly for graceful shutdown
                with anyio.move_on_after(2):
                    await self._process.wait()
            except Exception:
                # Force kill if still running
                with contextlib.suppress(ProcessLookupError):
                    self._process.kill()
            self._process = None

        self._stdin = None
        self._stdout = None
        self._connected = False
        self._read_buffer = b""

    async def send(self, message: dict[str, Any]) -> None:
        """Send a message to the adapter via stdin."""
        if self._stdin is None:
            raise DAPConnectionError("Transport not connected")

        data = encode_message(message)
        await self._stdin.send(data)

    async def receive(self) -> dict[str, Any]:
        """Receive a message from the adapter via stdout."""
        if self._stdout is None:
            raise DAPConnectionError("Transport not connected")

        # Read until we find the header separator
        header_data = await self._read_until_separator()

        # Parse content length
        content_length = parse_content_length(header_data)

        # Read the exact content from buffer + stream
        content = await self._read_exactly(content_length)

        return decode_message(content)

    async def _read_until_separator(self) -> bytes:
        """Read bytes until the header separator is found.

        Uses persistent buffer to avoid losing data read past the separator.
        """
        if self._stdout is None:
            raise DAPConnectionError("Transport not connected")

        while HEADER_SEPARATOR not in self._read_buffer:
            chunk = await self._stdout.receive(4096)
            if not chunk:
                raise DAPProtocolError("Connection closed while reading header")
            self._read_buffer += chunk

        # Split at separator
        header_end = self._read_buffer.index(HEADER_SEPARATOR)
        header = self._read_buffer[:header_end]
        # Keep everything after separator in buffer for content read
        self._read_buffer = self._read_buffer[header_end + len(HEADER_SEPARATOR) :]
        return header

    async def _read_exactly(self, n: int) -> bytes:
        """Read exactly n bytes from buffer + stream."""
        if self._stdout is None:
            raise DAPConnectionError("Transport not connected")

        # First consume from buffer
        while len(self._read_buffer) < n:
            chunk = await self._stdout.receive(4096)
            if not chunk:
                raise DAPProtocolError("Connection closed while reading content")
            self._read_buffer += chunk

        # Extract exactly n bytes
        result = self._read_buffer[:n]
        self._read_buffer = self._read_buffer[n:]
        return result

    @property
    def is_connected(self) -> bool:
        """Check if the subprocess is running."""
        return self._connected and self._process is not None


class SocketTransport(DAPTransport):
    """Transport that connects to adapter via TCP socket."""

    def __init__(self, host: str, port: int) -> None:
        """Initialize socket transport.

        Args:
            host: Host to connect to
            port: Port to connect to
        """
        self._host = host
        self._port = port
        self._reader: BufferedByteReceiveStream | None = None
        self._writer: ByteSendStream | None = None
        self._connected = False
        self._read_buffer = b""  # Persistent buffer for excess data

    async def connect(self) -> None:
        """Connect to the debug adapter socket."""
        if self._connected:
            return

        try:
            stream = await anyio.connect_tcp(self._host, self._port)
            self._reader = BufferedByteReceiveStream(stream)
            self._writer = stream
            self._connected = True
        except OSError as e:
            raise DAPConnectionError(f"Failed to connect to {self._host}:{self._port}: {e}") from e

    async def disconnect(self) -> None:
        """Close the socket connection."""
        if self._writer is not None:
            await self._writer.aclose()
            self._writer = None

        self._reader = None
        self._connected = False

    async def send(self, message: dict[str, Any]) -> None:
        """Send a message to the adapter via socket."""
        if self._writer is None:
            raise DAPConnectionError("Transport not connected")

        data = encode_message(message)
        await self._writer.send(data)

    async def receive(self) -> dict[str, Any]:
        """Receive a message from the adapter via socket."""
        if self._reader is None:
            raise DAPConnectionError("Transport not connected")

        # Read until we find the header separator
        header_data = await self._read_until_separator()

        # Parse content length
        content_length = parse_content_length(header_data)

        # Read the exact content from buffer + stream
        content = await self._read_exactly(content_length)

        return decode_message(content)

    async def _read_until_separator(self) -> bytes:
        """Read bytes until the header separator is found.

        Uses persistent buffer to avoid losing data read past the separator.
        """
        if self._reader is None:
            raise DAPConnectionError("Transport not connected")

        while HEADER_SEPARATOR not in self._read_buffer:
            chunk = await self._reader.receive(4096)
            if not chunk:
                raise DAPProtocolError("Connection closed while reading header")
            self._read_buffer += chunk

        # Split at separator
        header_end = self._read_buffer.index(HEADER_SEPARATOR)
        header = self._read_buffer[:header_end]
        # Keep everything after separator in buffer for content read
        self._read_buffer = self._read_buffer[header_end + len(HEADER_SEPARATOR) :]
        return header

    async def _read_exactly(self, n: int) -> bytes:
        """Read exactly n bytes from buffer + stream."""
        if self._reader is None:
            raise DAPConnectionError("Transport not connected")

        # First consume from buffer
        while len(self._read_buffer) < n:
            chunk = await self._reader.receive(4096)
            if not chunk:
                raise DAPProtocolError("Connection closed while reading content")
            self._read_buffer += chunk

        # Extract exactly n bytes
        result = self._read_buffer[:n]
        self._read_buffer = self._read_buffer[n:]
        return result

    @property
    def is_connected(self) -> bool:
        """Check if the socket is connected."""
        return self._connected


class SubprocessSocketTransport(DAPTransport):
    """Transport that spawns adapter as subprocess and connects via TCP socket.

    Used by adapters like js-debug that run a DAP server on a port
    rather than communicating via stdin/stdout.
    """

    def __init__(
        self,
        command: list[str],
        port: int | None = None,
        host: str = "127.0.0.1",
        cwd: Path | str | None = None,
        env: dict[str, str] | None = None,
        startup_timeout: float = 10.0,
        port_arg_template: str = "{port}",
    ) -> None:
        """Initialize subprocess socket transport.

        Args:
            command: Command to spawn the adapter. A port argument is appended.
            port: Port for the DAP server. If None, a free port is found automatically.
            host: Host for the DAP server.
            cwd: Working directory for the subprocess.
            env: Environment variables for the subprocess.
            startup_timeout: Seconds to wait for the server to start listening.
            port_arg_template: Format template for the port argument appended to the
                command. Receives ``{port}`` and ``{host}`` placeholders.
                Examples: ``"{port}"`` (default), ``"--listen={host}:{port}"``.
        """
        self._command = command
        self._host = host
        self._cwd = cwd
        self._env = env
        self._startup_timeout = startup_timeout
        self._port_arg_template = port_arg_template
        self._process: anyio.abc.Process | None = None
        self._socket: SocketTransport | None = None
        self._port = port

    @property
    def port(self) -> int | None:
        """The port the DAP server is listening on."""
        return self._port

    async def connect(self) -> None:
        """Spawn the adapter subprocess and connect via socket."""
        if self._socket is not None and self._socket.is_connected:
            return

        # Find a free port if none specified
        if self._port is None:
            self._port = await self._find_free_port()

        # Spawn the subprocess with port argument
        port_arg = self._port_arg_template.format(port=self._port, host=self._host)
        cmd = [*self._command, port_arg]
        try:
            self._process = await anyio.open_process(
                cmd,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=self._cwd,
                env=self._env,
            )
        except OSError as e:
            raise DAPConnectionError(f"Failed to spawn adapter: {e}") from e

        # Wait for the server to start listening
        await self._wait_for_server()

        # Connect via socket
        self._socket = SocketTransport(self._host, self._port)
        await self._socket.connect()

    async def disconnect(self) -> None:
        """Close socket and terminate the subprocess."""
        import contextlib

        if self._socket is not None:
            await self._socket.disconnect()
            self._socket = None

        if self._process is not None:
            with contextlib.suppress(ProcessLookupError):
                self._process.terminate()
            try:
                with anyio.move_on_after(2):
                    await self._process.wait()
            except Exception:
                with contextlib.suppress(ProcessLookupError):
                    self._process.kill()
            self._process = None

    async def send(self, message: dict[str, Any]) -> None:
        """Send a message via the socket connection."""
        if self._socket is None:
            raise DAPConnectionError("Transport not connected")
        await self._socket.send(message)

    async def receive(self) -> dict[str, Any]:
        """Receive a message via the socket connection."""
        if self._socket is None:
            raise DAPConnectionError("Transport not connected")
        return await self._socket.receive()

    @property
    def is_connected(self) -> bool:
        """Check if the socket is connected and subprocess is running."""
        return self._socket is not None and self._socket.is_connected

    async def _find_free_port(self) -> int:
        """Find a free TCP port."""
        import socket

        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(("127.0.0.1", 0))
            return s.getsockname()[1]  # type: ignore[no-any-return]

    async def _wait_for_server(self) -> None:
        """Wait for the DAP server to start accepting connections."""
        import socket

        assert self._port is not None

        deadline = asyncio.get_event_loop().time() + self._startup_timeout
        while asyncio.get_event_loop().time() < deadline:
            # Check if process died
            if self._process is not None and self._process.returncode is not None:
                stderr_output = ""
                if self._process.stderr is not None:
                    try:
                        raw = await self._process.stderr.receive(4096)
                        stderr_output = raw.decode("utf-8", errors="replace")
                    except Exception:
                        pass
                raise DAPConnectionError(
                    f"Adapter process exited with code {self._process.returncode}"
                    f"{': ' + stderr_output if stderr_output else ''}"
                )

            # Try connecting
            try:
                with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                    s.settimeout(0.1)
                    s.connect((self._host, self._port))
                    return  # Server is ready
            except (ConnectionRefusedError, OSError):
                await anyio.sleep(0.05)

        raise DAPConnectionError(
            f"Adapter server did not start within {self._startup_timeout}s "
            f"on {self._host}:{self._port}"
        )
