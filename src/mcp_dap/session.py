"""Debug session management."""

from __future__ import annotations

import asyncio
import contextlib
import uuid
from typing import TYPE_CHECKING
from typing import Any

from mcp_dap.dap.client import DAPClient
from mcp_dap.exceptions import AdapterNotFoundError
from mcp_dap.exceptions import MCPDAPError
from mcp_dap.exceptions import SessionAlreadyExistsError
from mcp_dap.exceptions import SessionNotFoundError
from mcp_dap.types import Breakpoint
from mcp_dap.types import EvaluateResult
from mcp_dap.types import OutputEvent
from mcp_dap.types import Scope
from mcp_dap.types import SessionInfo
from mcp_dap.types import SessionState
from mcp_dap.types import StackFrame
from mcp_dap.types import StoppedEvent
from mcp_dap.types import StopReason
from mcp_dap.types import Thread
from mcp_dap.types import Variable

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from mcp_dap.adapters.base import AdapterConfig
    from mcp_dap.config import ServerConfig
    from mcp_dap.dap.messages import DAPEvent


class DebugSession:
    """A debug session with a single debug adapter."""

    def __init__(
        self,
        session_id: str,
        adapter: AdapterConfig,
        client: DAPClient,
    ) -> None:
        """Initialize debug session.

        Args:
            session_id: Unique session identifier
            adapter: Adapter configuration
            client: DAP client instance
        """
        self.session_id = session_id
        self.adapter = adapter
        self.client = client

        self._state = SessionState.INITIALIZING
        self._program: str | None = None
        self._threads: list[Thread] = []
        self._stopped_thread_id: int | None = None
        self._stop_reason: StopReason | None = None

        # Event storage
        self._pending_events: list[DAPEvent] = []
        self._output_buffer: list[OutputEvent] = []
        self._stop_event: asyncio.Event = asyncio.Event()

        # Breakpoints by source path
        self._breakpoints: dict[str, list[Breakpoint]] = {}

        # Event callbacks
        self._event_callbacks: list[Callable[[str, DAPEvent], Any]] = []

        # Register event handler
        self.client.add_event_handler(self._handle_event)

    async def initialize(self) -> dict[str, Any]:
        """Initialize the debug session.

        Returns:
            Adapter capabilities
        """
        capabilities = await self.client.initialize()
        return capabilities

    async def launch(
        self,
        program: str | None = None,
        args: list[str] | None = None,
        cwd: str | None = None,
        env: dict[str, str] | None = None,
        stop_on_entry: bool = False,
        cargo_args: list[str] | None = None,
        **kwargs: Any,
    ) -> None:
        """Launch a program for debugging.

        Args:
            program: Program to debug (required unless cargo_args is provided)
            args: Command line arguments for the program
            cwd: Working directory
            env: Environment variables
            stop_on_entry: Stop on entry point
            cargo_args: Cargo build arguments (e.g., ["build", "--bin", "myapp"]).
                       If provided, builds with cargo and debugs the result.
                       Only works with CodeLLDB adapter.
            **kwargs: Additional adapter-specific arguments
        """
        # Handle cargo build if cargo_args provided
        if cargo_args is not None:
            from mcp_dap.adapters.codelldb import CodeLLDBAdapter

            if not isinstance(self.adapter, CodeLLDBAdapter):
                raise MCPDAPError("cargo_args is only supported with CodeLLDB adapter (rust)")

            launch_args = self.adapter.get_cargo_launch_arguments(
                cargo_args=cargo_args,
                program_args=args,
                cwd=cwd,
                env=env,
                stop_on_entry=stop_on_entry,
                **kwargs,
            )
            self._program = launch_args.get("program")
        else:
            if program is None:
                raise MCPDAPError("Either 'program' or 'cargo_args' must be provided")

            self._program = program
            launch_args = self.adapter.get_launch_arguments(
                program=program,
                args=args,
                cwd=cwd,
                env=env,
                stop_on_entry=stop_on_entry,
                **kwargs,
            )

        # DAP launch sequence: launch → wait for initialized → configurationDone → launch response
        await self.client.launch(launch_args, wait_for_initialized=True)
        await self.client.configuration_done()
        await self.client.complete_launch()
        self._state = SessionState.RUNNING

    async def attach(
        self,
        host: str | None = None,
        port: int | None = None,
        **kwargs: Any,
    ) -> None:
        """Attach to a running process.

        Args:
            host: Host where debuggee is running
            port: Debug port
            **kwargs: Additional adapter-specific arguments
        """
        # Type narrowing for adapter methods: they expect host/port or other kwargs
        # but we'll let the adapter handle the validation
        attach_args = self.adapter.get_attach_arguments(
            host=host,  # type: ignore[arg-type]
            port=port,  # type: ignore[arg-type]
            **kwargs,
        )

        # DAP attach sequence: attach → wait for initialized → configurationDone → attach response
        await self.client.attach(attach_args, wait_for_initialized=True)
        await self.client.configuration_done()
        await self.client.complete_launch()  # Also works for attach
        self._state = SessionState.RUNNING

    async def disconnect(self, terminate: bool = True) -> None:
        """Disconnect from the debug session.

        Args:
            terminate: Whether to terminate the debuggee
        """
        self._state = SessionState.TERMINATED
        await self.client.disconnect_debuggee(terminate=terminate)
        await self.client.disconnect()

    async def set_breakpoints(
        self,
        source_path: str,
        breakpoints: list[dict[str, Any]],
    ) -> list[Breakpoint]:
        """Set breakpoints in a source file.

        Args:
            source_path: Path to source file
            breakpoints: List of breakpoint specs (line, condition, etc.)

        Returns:
            List of verified breakpoints
        """
        result = await self.client.set_breakpoints(source_path, breakpoints)

        # Store and convert to our types
        bps = [
            Breakpoint(
                id=bp.get("id"),
                verified=bp.get("verified", False),
                message=bp.get("message"),
                source_path=source_path,
                line=bp.get("line"),
                column=bp.get("column"),
                end_line=bp.get("endLine"),
                end_column=bp.get("endColumn"),
            )
            for bp in result
        ]

        self._breakpoints[source_path] = bps
        return bps

    async def clear_breakpoints(self, source_path: str) -> None:
        """Clear all breakpoints in a source file.

        Args:
            source_path: Path to source file
        """
        await self.client.set_breakpoints(source_path, [])
        self._breakpoints.pop(source_path, None)

    async def continue_execution(
        self,
        thread_id: int | None = None,
        wait: bool = True,
    ) -> StoppedEvent | None:
        """Continue execution.

        Args:
            thread_id: Thread to continue (or all if None)
            wait: Wait for execution to stop

        Returns:
            StoppedEvent if wait=True and execution stopped, None otherwise
        """
        tid = thread_id or self._stopped_thread_id or 1
        self._stop_event.clear()
        self._state = SessionState.RUNNING
        self._stopped_thread_id = None
        self._stop_reason = None

        await self.client.continue_execution(tid)

        if wait:
            return await self._wait_for_stop()
        return None

    async def step_over(
        self,
        thread_id: int | None = None,
        wait: bool = True,
    ) -> StoppedEvent | None:
        """Step over (next line).

        Args:
            thread_id: Thread to step
            wait: Wait for step to complete

        Returns:
            StoppedEvent if wait=True, None otherwise
        """
        tid = thread_id or self._stopped_thread_id or 1
        self._stop_event.clear()
        self._state = SessionState.RUNNING

        await self.client.next(tid)

        if wait:
            return await self._wait_for_stop()
        return None

    async def step_into(
        self,
        thread_id: int | None = None,
        wait: bool = True,
    ) -> StoppedEvent | None:
        """Step into function.

        Args:
            thread_id: Thread to step
            wait: Wait for step to complete

        Returns:
            StoppedEvent if wait=True, None otherwise
        """
        tid = thread_id or self._stopped_thread_id or 1
        self._stop_event.clear()
        self._state = SessionState.RUNNING

        await self.client.step_in(tid)

        if wait:
            return await self._wait_for_stop()
        return None

    async def step_out(
        self,
        thread_id: int | None = None,
        wait: bool = True,
    ) -> StoppedEvent | None:
        """Step out of function.

        Args:
            thread_id: Thread to step
            wait: Wait for step to complete

        Returns:
            StoppedEvent if wait=True, None otherwise
        """
        tid = thread_id or self._stopped_thread_id or 1
        self._stop_event.clear()
        self._state = SessionState.RUNNING

        await self.client.step_out(tid)

        if wait:
            return await self._wait_for_stop()
        return None

    async def pause(self, thread_id: int | None = None) -> None:
        """Pause execution.

        Args:
            thread_id: Thread to pause (or all if None)
        """
        tid = thread_id or 1
        await self.client.pause(tid)

    async def get_threads(self) -> list[Thread]:
        """Get all threads.

        Returns:
            List of threads
        """
        result = await self.client.threads()
        self._threads = [
            Thread(id=t["id"], name=t.get("name", f"Thread {t['id']}")) for t in result
        ]
        return self._threads

    async def get_stack_trace(
        self,
        thread_id: int | None = None,
        start_frame: int = 0,
        levels: int = 20,
    ) -> list[StackFrame]:
        """Get stack trace for a thread.

        Args:
            thread_id: Thread to get stack trace for
            start_frame: Starting frame index
            levels: Number of frames to fetch

        Returns:
            List of stack frames
        """
        tid = thread_id or self._stopped_thread_id or 1
        frames, _ = await self.client.stack_trace(tid, start_frame, levels)

        return [
            StackFrame(
                id=f["id"],
                name=f.get("name", ""),
                source=f.get("source"),
                line=f.get("line", 0),
                column=f.get("column", 0),
                end_line=f.get("endLine"),
                end_column=f.get("endColumn"),
                module_id=f.get("moduleId"),
            )
            for f in frames
        ]

    async def get_scopes(self, frame_id: int) -> list[Scope]:
        """Get scopes for a stack frame.

        Args:
            frame_id: Stack frame ID

        Returns:
            List of scopes
        """
        result = await self.client.scopes(frame_id)

        return [
            Scope(
                name=s.get("name", ""),
                presentation_hint=s.get("presentationHint"),
                variables_reference=s["variablesReference"],
                named_variables=s.get("namedVariables"),
                indexed_variables=s.get("indexedVariables"),
                expensive=s.get("expensive", False),
                source=s.get("source"),
                line=s.get("line"),
                column=s.get("column"),
                end_line=s.get("endLine"),
                end_column=s.get("endColumn"),
            )
            for s in result
        ]

    async def get_variables(
        self,
        variables_reference: int,
        filter_type: str | None = None,
    ) -> list[Variable]:
        """Get variables for a scope or variable.

        Args:
            variables_reference: Reference to fetch variables for
            filter_type: "indexed" or "named" to filter

        Returns:
            List of variables
        """
        result = await self.client.variables(variables_reference, filter_type)

        return [
            Variable(
                name=v.get("name", ""),
                value=v.get("value", ""),
                type=v.get("type"),
                presentation_hint=v.get("presentationHint"),
                evaluate_name=v.get("evaluateName"),
                variables_reference=v.get("variablesReference", 0),
                named_variables=v.get("namedVariables"),
                indexed_variables=v.get("indexedVariables"),
            )
            for v in result
        ]

    async def evaluate(
        self,
        expression: str,
        frame_id: int | None = None,
        context: str = "repl",
    ) -> EvaluateResult:
        """Evaluate an expression.

        Args:
            expression: Expression to evaluate
            frame_id: Stack frame context
            context: Evaluation context

        Returns:
            Evaluation result
        """
        result = await self.client.evaluate(expression, frame_id, context)

        return EvaluateResult(
            result=result.get("result", ""),
            type=result.get("type"),
            presentation_hint=result.get("presentationHint"),
            variables_reference=result.get("variablesReference", 0),
            named_variables=result.get("namedVariables"),
            indexed_variables=result.get("indexedVariables"),
        )

    def get_pending_events(self) -> list[DAPEvent]:
        """Get and clear pending events.

        Returns:
            List of pending events
        """
        events = self._pending_events[:]
        self._pending_events.clear()
        return events

    def get_output(self) -> list[OutputEvent]:
        """Get and clear output buffer.

        Returns:
            List of output events
        """
        output = self._output_buffer[:]
        self._output_buffer.clear()
        return output

    def get_info(self) -> SessionInfo:
        """Get session information.

        Returns:
            Session info object
        """
        return SessionInfo(
            session_id=self.session_id,
            adapter=self.adapter.name,
            state=self._state,
            program=self._program,
            threads=self._threads,
            stopped_thread_id=self._stopped_thread_id,
            stop_reason=self._stop_reason,
        )

    def add_event_callback(
        self,
        callback: Callable[[str, DAPEvent], Any],
    ) -> None:
        """Add callback for debug events.

        Args:
            callback: Callback receiving (session_id, event)
        """
        self._event_callbacks.append(callback)

    async def _wait_for_stop(self, timeout: float = 300.0) -> StoppedEvent | None:
        """Wait for execution to stop.

        Args:
            timeout: Timeout in seconds

        Returns:
            StoppedEvent when stopped, None on timeout
        """
        try:
            await asyncio.wait_for(self._stop_event.wait(), timeout)
        except TimeoutError:
            return None

        if self._stopped_thread_id and self._stop_reason:
            return StoppedEvent(
                reason=self._stop_reason,
                thread_id=self._stopped_thread_id,
            )
        return None

    def _handle_event(self, event: DAPEvent) -> None:
        """Handle DAP events."""
        self._pending_events.append(event)

        if event.event == "stopped":
            self._handle_stopped(event)
        elif event.event == "continued":
            self._handle_continued(event)
        elif event.event == "terminated":
            self._handle_terminated(event)
        elif event.event == "output":
            self._handle_output(event)
        elif event.event == "thread":
            self._handle_thread(event)

        # Notify callbacks
        for callback in self._event_callbacks:
            with contextlib.suppress(Exception):
                callback(self.session_id, event)

    def _handle_stopped(self, event: DAPEvent) -> None:
        """Handle stopped event."""
        body = event.body or {}
        self._state = SessionState.STOPPED
        self._stopped_thread_id = body.get("threadId")

        reason_str = body.get("reason", "unknown")
        try:
            self._stop_reason = StopReason(reason_str)
        except ValueError:
            self._stop_reason = StopReason.BREAKPOINT  # Default

        self._stop_event.set()

    def _handle_continued(self, _event: DAPEvent) -> None:
        """Handle continued event."""
        self._state = SessionState.RUNNING
        self._stopped_thread_id = None
        self._stop_reason = None
        self._stop_event.clear()

    def _handle_terminated(self, _event: DAPEvent) -> None:
        """Handle terminated event."""
        self._state = SessionState.TERMINATED
        self._stop_event.set()

    def _handle_output(self, event: DAPEvent) -> None:
        """Handle output event."""
        body = event.body or {}
        self._output_buffer.append(
            OutputEvent(
                category=body.get("category", "console"),
                output=body.get("output", ""),
                group=body.get("group"),
                variables_reference=body.get("variablesReference"),
                source=body.get("source"),
                line=body.get("line"),
                column=body.get("column"),
            )
        )

    def _handle_thread(self, event: DAPEvent) -> None:
        """Handle thread event."""
        # Thread started/exited - we'll refresh on next get_threads call
        pass

    @property
    def state(self) -> SessionState:
        """Current session state."""
        return self._state

    @property
    def stopped_thread_id(self) -> int | None:
        """ID of the stopped thread, if any."""
        return self._stopped_thread_id

    @property
    def breakpoints(self) -> dict[str, list[Breakpoint]]:
        """All breakpoints by source path."""
        return self._breakpoints.copy()


class SessionManager:
    """Manages multiple debug sessions."""

    def __init__(self, config: ServerConfig | None = None) -> None:
        """Initialize session manager.

        Args:
            config: Server configuration. If not provided, loads default config.
        """
        if config is None:
            from mcp_dap.config import get_config

            config = get_config()

        self._config = config
        self._adapters = config.build_adapter_registry()
        self._sessions: dict[str, DebugSession] = {}
        self._event_callbacks: list[Callable[[str, DAPEvent], Any]] = []

    @property
    def adapters(self) -> dict[str, AdapterConfig]:
        """Get the adapter registry."""
        return self._adapters

    @property
    def config(self) -> ServerConfig:
        """Get the server configuration."""
        return self._config

    async def create_session(
        self,
        adapter_name: str,
        *,
        program: str | None = None,
        cwd: Path | str | None = None,
        env: dict[str, str] | None = None,
        host: str | None = None,
        port: int | None = None,
        session_id: str | None = None,
        **kwargs: Any,
    ) -> DebugSession:
        """Create a new debug session.

        Args:
            adapter_name: Name of adapter to use (e.g., "debugpy")
            program: Program to debug (for launch mode)
            cwd: Working directory
            env: Environment variables
            host: Host to connect to (for attach mode)
            port: Port to connect to (for attach mode)
            session_id: Optional session ID (generated if not provided)
            **kwargs: Additional adapter-specific arguments

        Returns:
            The created debug session

        Raises:
            AdapterNotFoundError: If adapter is not registered or disabled
            SessionAlreadyExistsError: If session_id already exists
        """
        adapter = self._adapters.get(adapter_name)
        if adapter is None:
            # Provide helpful error message
            available = list(self._adapters.keys())
            raise AdapterNotFoundError(
                f"Unknown or disabled adapter: {adapter_name}. "
                f"Available adapters: {available}"
            )

        sid = session_id or str(uuid.uuid4())
        if sid in self._sessions:
            raise SessionAlreadyExistsError(f"Session already exists: {sid}")

        # Create transport
        transport = adapter.create_transport(
            program=program,
            cwd=cwd,
            env=env,
            host=host,
            port=port,
            **kwargs,
        )

        # Create client and session
        client = DAPClient(transport, adapter.adapter_id)
        session = DebugSession(sid, adapter, client)

        # Register global event callbacks
        for callback in self._event_callbacks:
            session.add_event_callback(callback)

        # Connect and initialize
        await client.connect()
        await session.initialize()

        self._sessions[sid] = session
        return session

    async def get_session(self, session_id: str) -> DebugSession:
        """Get an existing session.

        Args:
            session_id: Session ID

        Returns:
            The debug session

        Raises:
            SessionNotFoundError: If session not found
        """
        session = self._sessions.get(session_id)
        if session is None:
            raise SessionNotFoundError(f"Session not found: {session_id}")
        return session

    async def close_session(self, session_id: str, terminate: bool = True) -> None:
        """Close a debug session.

        Args:
            session_id: Session ID
            terminate: Whether to terminate the debuggee
        """
        session = self._sessions.pop(session_id, None)
        if session is not None:
            await session.disconnect(terminate=terminate)

    async def close_all(self) -> None:
        """Close all debug sessions."""
        for session_id in list(self._sessions.keys()):
            await self.close_session(session_id)

    def list_sessions(self) -> list[SessionInfo]:
        """List all active sessions.

        Returns:
            List of session info objects
        """
        return [session.get_info() for session in self._sessions.values()]

    def add_event_callback(
        self,
        callback: Callable[[str, DAPEvent], Any],
    ) -> None:
        """Add callback for debug events from all sessions.

        Args:
            callback: Callback receiving (session_id, event)
        """
        self._event_callbacks.append(callback)
        # Add to existing sessions
        for session in self._sessions.values():
            session.add_event_callback(callback)

    def __len__(self) -> int:
        """Number of active sessions."""
        return len(self._sessions)

    def __contains__(self, session_id: str) -> bool:
        """Check if session exists."""
        return session_id in self._sessions
