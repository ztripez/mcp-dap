"""DAP client implementation.

Handles async communication with debug adapters.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING
from typing import Any

import anyio

from mcp_dap.dap.messages import DAPEvent
from mcp_dap.dap.messages import DAPRequest
from mcp_dap.dap.messages import DAPResponse
from mcp_dap.dap.messages import InitializeArguments
from mcp_dap.exceptions import DAPError
from mcp_dap.exceptions import DAPProtocolError
from mcp_dap.exceptions import DAPTimeoutError

if TYPE_CHECKING:
    from collections.abc import Callable

    from mcp_dap.dap.transport import DAPTransport


class DAPClient:
    """Async DAP client for communicating with debug adapters."""

    def __init__(
        self,
        transport: DAPTransport,
        adapter_id: str = "mcp-dap",
    ) -> None:
        """Initialize DAP client.

        Args:
            transport: Transport to use for communication
            adapter_id: Adapter ID for initialization
        """
        self._transport = transport
        self._adapter_id = adapter_id
        self._seq = 0
        self._pending_requests: dict[int, asyncio.Future[DAPResponse]] = {}
        self._event_handlers: list[Callable[[DAPEvent], Any]] = []
        self._receive_task: asyncio.Task[None] | None = None
        self._capabilities: dict[str, Any] = {}
        self._initialized = False
        self._configuration_done = False
        # Events are created lazily to ensure they're in the right event loop
        self._initialized_event: asyncio.Event | None = None
        self._stopped_event: asyncio.Event | None = None
        self._last_stop_info: dict[str, Any] = {}

    async def connect(self) -> None:
        """Connect to the debug adapter and start receiving messages."""
        await self._transport.connect()
        # Create event objects now that we're in an event loop
        self._ensure_events()
        self._receive_task = asyncio.create_task(self._receive_loop())

    async def disconnect(self) -> None:
        """Disconnect from the debug adapter."""
        if self._receive_task is not None:
            self._receive_task.cancel()
            with anyio.move_on_after(1):
                await asyncio.gather(self._receive_task, return_exceptions=True)
            self._receive_task = None

        await self._transport.disconnect()

        # Cancel any pending requests
        for future in self._pending_requests.values():
            if not future.done():
                future.cancel()
        self._pending_requests.clear()

    def add_event_handler(self, handler: Callable[[DAPEvent], Any]) -> None:
        """Add an event handler.

        Args:
            handler: Callback function that receives DAPEvent objects
        """
        self._event_handlers.append(handler)

    def remove_event_handler(self, handler: Callable[[DAPEvent], Any]) -> None:
        """Remove an event handler.

        Args:
            handler: The handler to remove
        """
        self._event_handlers.remove(handler)

    async def initialize(self) -> dict[str, Any]:
        """Send initialize request and return adapter capabilities.

        Returns:
            The capabilities dict from the adapter.
        """
        args = InitializeArguments.model_validate(
            {
                "adapterID": self._adapter_id,
                "clientID": "mcp-dap",
                "clientName": "MCP-DAP Bridge",
                "linesStartAt1": True,
                "columnsStartAt1": True,
                "pathFormat": "path",
                "supportsVariableType": True,
                "supportsVariablePaging": True,
                "supportsRunInTerminalRequest": False,
                "supportsMemoryReferences": False,
                "supportsProgressReporting": False,
                "supportsInvalidatedEvent": True,
            }
        )

        response = await self.request(
            "initialize", args.model_dump(by_alias=True, exclude_none=True)
        )

        if response.body:
            self._capabilities = response.body

        self._initialized = True
        return self._capabilities

    async def configuration_done(self) -> None:
        """Send configurationDone request."""
        await self.request("configurationDone")
        self._configuration_done = True

    async def launch(
        self,
        arguments: dict[str, Any],
        wait_for_initialized: bool = True,
    ) -> None:
        """Send launch request.

        The DAP launch sequence is:
        1. Client sends launch request (response deferred)
        2. Adapter sends initialized event
        3. Client sets breakpoints
        4. Client sends configurationDone
        5. Adapter sends launch response
        6. Execution begins

        Args:
            arguments: Launch configuration arguments
            wait_for_initialized: If True, wait for initialized event before returning.
                                  Caller should then set breakpoints and call configuration_done().
        """
        # Reset state
        self._ensure_events()
        self._initialized_event.clear()  # type: ignore[union-attr]
        self._stopped_event.clear()  # type: ignore[union-attr]
        self._configuration_done = False

        # Send launch request - it won't respond until configurationDone
        self._seq += 1
        seq = self._seq
        request = DAPRequest(
            seq=seq,
            command="launch",
            arguments=arguments,
        )

        # Create future for eventual response
        future: asyncio.Future[DAPResponse] = asyncio.get_event_loop().create_future()
        self._pending_requests[seq] = future

        # Send the request
        await self._transport.send(request.model_dump(by_alias=True))

        if wait_for_initialized:
            # Wait for initialized event (not the launch response)
            try:
                await asyncio.wait_for(
                    self._initialized_event.wait(),  # type: ignore[union-attr]
                    timeout=30.0,
                )
            except TimeoutError as e:
                self._pending_requests.pop(seq, None)
                raise DAPTimeoutError("Timeout waiting for initialized event") from e

        # Store the pending launch future for later completion
        self._launch_future = future
        self._launch_seq = seq

    async def complete_launch(self, timeout: float = 30.0) -> None:
        """Complete the launch sequence after configurationDone.

        Call this after setting breakpoints and calling configuration_done().
        It waits for the launch response to confirm the launch succeeded.
        """
        if not hasattr(self, "_launch_future"):
            raise DAPError("No pending launch request")

        future = self._launch_future
        seq = self._launch_seq

        try:
            async with asyncio.timeout(timeout):
                response = await future
        except TimeoutError as e:
            raise DAPTimeoutError("Timeout waiting for launch response") from e
        finally:
            self._pending_requests.pop(seq, None)
            del self._launch_future
            del self._launch_seq

        if not response.success:
            raise DAPError(f"Launch failed: {response.message or 'Unknown error'}")

    async def attach(
        self,
        arguments: dict[str, Any],
        wait_for_initialized: bool = True,
    ) -> None:
        """Send attach request.

        Similar to launch(), the attach response is deferred until configurationDone.

        Args:
            arguments: Attach configuration arguments
            wait_for_initialized: If True, wait for initialized event before returning.
        """
        # Reset state
        self._ensure_events()
        self._initialized_event.clear()  # type: ignore[union-attr]
        self._stopped_event.clear()  # type: ignore[union-attr]
        self._configuration_done = False

        # Send attach request
        self._seq += 1
        seq = self._seq
        request = DAPRequest(
            seq=seq,
            command="attach",
            arguments=arguments,
        )

        future: asyncio.Future[DAPResponse] = asyncio.get_event_loop().create_future()
        self._pending_requests[seq] = future

        await self._transport.send(request.model_dump(by_alias=True))

        if wait_for_initialized:
            try:
                await asyncio.wait_for(
                    self._initialized_event.wait(),  # type: ignore[union-attr]
                    timeout=30.0,
                )
            except TimeoutError as e:
                self._pending_requests.pop(seq, None)
                raise DAPTimeoutError("Timeout waiting for initialized event") from e

        self._launch_future = future
        self._launch_seq = seq

    async def launch_and_wait(
        self,
        arguments: dict[str, Any],
        breakpoints: dict[str, list[dict[str, Any]]] | None = None,
        wait_for_stop: bool = True,
    ) -> dict[str, Any] | None:
        """Convenience method: launch, set breakpoints, and optionally wait for stop.

        This handles the full DAP launch sequence:
        1. Send launch request
        2. Wait for initialized event
        3. Set breakpoints (if provided)
        4. Send configurationDone
        5. Wait for launch response
        6. Optionally wait for stop event

        Args:
            arguments: Launch configuration arguments
            breakpoints: Dict mapping source paths to breakpoint lists.
                         Each breakpoint: {"line": int, "condition"?: str}
            wait_for_stop: If True, wait for execution to stop before returning.

        Returns:
            Stop info dict if wait_for_stop=True, else None.
        """
        # Launch and wait for initialized
        await self.launch(arguments, wait_for_initialized=True)

        # Set breakpoints
        if breakpoints:
            for source_path, bps in breakpoints.items():
                await self.set_breakpoints(source_path, bps)

        # Send configurationDone and complete launch
        await self.configuration_done()
        await self.complete_launch()

        # Optionally wait for stop
        if wait_for_stop:
            return await self.wait_for_stop()
        return None

    async def disconnect_debuggee(
        self,
        terminate: bool = False,
        restart: bool = False,
    ) -> None:
        """Send disconnect request.

        Args:
            terminate: Whether to terminate the debuggee
            restart: Whether to restart debugging
        """
        await self.request(
            "disconnect",
            {
                "terminateDebuggee": terminate,
                "restart": restart,
            },
        )

    async def set_breakpoints(
        self,
        source_path: str,
        breakpoints: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Set breakpoints in a source file.

        Args:
            source_path: Path to the source file
            breakpoints: List of breakpoint specifications

        Returns:
            List of verified breakpoint objects
        """
        response = await self.request(
            "setBreakpoints",
            {
                "source": {"path": source_path},
                "breakpoints": breakpoints,
            },
        )
        return response.body.get("breakpoints", []) if response.body else []

    async def set_exception_breakpoints(
        self,
        filters: list[str],
    ) -> None:
        """Set exception breakpoints.

        Args:
            filters: List of exception filter IDs (e.g., ["raised", "uncaught"])
        """
        await self.request(
            "setExceptionBreakpoints",
            {"filters": filters},
        )

    async def continue_execution(
        self,
        thread_id: int,
        single_thread: bool = False,
    ) -> bool:
        """Continue execution.

        Args:
            thread_id: Thread to continue
            single_thread: Only continue this thread

        Returns:
            Whether all threads were continued
        """
        response = await self.request(
            "continue",
            {
                "threadId": thread_id,
                "singleThread": single_thread,
            },
        )
        return response.body.get("allThreadsContinued", True) if response.body else True

    async def next(self, thread_id: int) -> None:
        """Step over (next line).

        Args:
            thread_id: Thread to step
        """
        await self.request("next", {"threadId": thread_id})

    async def step_in(self, thread_id: int) -> None:
        """Step into function.

        Args:
            thread_id: Thread to step
        """
        await self.request("stepIn", {"threadId": thread_id})

    async def step_out(self, thread_id: int) -> None:
        """Step out of function.

        Args:
            thread_id: Thread to step
        """
        await self.request("stepOut", {"threadId": thread_id})

    async def pause(self, thread_id: int) -> None:
        """Pause execution.

        Args:
            thread_id: Thread to pause
        """
        await self.request("pause", {"threadId": thread_id})

    async def threads(self) -> list[dict[str, Any]]:
        """Get all threads.

        Returns:
            List of thread objects
        """
        response = await self.request("threads")
        return response.body.get("threads", []) if response.body else []

    async def stack_trace(
        self,
        thread_id: int,
        start_frame: int = 0,
        levels: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        """Get stack trace for a thread.

        Args:
            thread_id: Thread to get stack trace for
            start_frame: Starting frame index
            levels: Number of frames to fetch

        Returns:
            Tuple of (stack frames list, total frames count)
        """
        response = await self.request(
            "stackTrace",
            {
                "threadId": thread_id,
                "startFrame": start_frame,
                "levels": levels,
            },
        )
        body = response.body or {}
        return body.get("stackFrames", []), body.get("totalFrames", 0)

    async def scopes(self, frame_id: int) -> list[dict[str, Any]]:
        """Get scopes for a stack frame.

        Args:
            frame_id: Stack frame ID

        Returns:
            List of scope objects
        """
        response = await self.request("scopes", {"frameId": frame_id})
        return response.body.get("scopes", []) if response.body else []

    async def variables(
        self,
        variables_reference: int,
        filter_type: str | None = None,
        start: int | None = None,
        count: int | None = None,
    ) -> list[dict[str, Any]]:
        """Get variables for a scope or variable.

        Args:
            variables_reference: Reference to fetch variables for
            filter_type: "indexed" or "named" to filter variable types
            start: Start index for paging
            count: Number of variables to fetch

        Returns:
            List of variable objects
        """
        args: dict[str, Any] = {"variablesReference": variables_reference}
        if filter_type:
            args["filter"] = filter_type
        if start is not None:
            args["start"] = start
        if count is not None:
            args["count"] = count

        response = await self.request("variables", args)
        return response.body.get("variables", []) if response.body else []

    async def evaluate(
        self,
        expression: str,
        frame_id: int | None = None,
        context: str = "repl",
    ) -> dict[str, Any]:
        """Evaluate an expression.

        Args:
            expression: Expression to evaluate
            frame_id: Stack frame context for evaluation
            context: Evaluation context ("watch", "repl", "hover", "clipboard")

        Returns:
            Evaluation result object
        """
        args: dict[str, Any] = {
            "expression": expression,
            "context": context,
        }
        if frame_id is not None:
            args["frameId"] = frame_id

        response = await self.request("evaluate", args)
        return response.body or {}

    async def request(
        self,
        command: str,
        arguments: dict[str, Any] | None = None,
        timeout: float = 30.0,
    ) -> DAPResponse:
        """Send a DAP request and wait for response.

        Args:
            command: DAP command name
            arguments: Command arguments
            timeout: Timeout in seconds

        Returns:
            The DAP response

        Raises:
            DAPTimeoutError: If the request times out
            DAPError: If the request fails
        """
        self._seq += 1
        seq = self._seq

        request = DAPRequest(
            seq=seq,
            command=command,
            arguments=arguments,
        )

        # Create future for response
        future: asyncio.Future[DAPResponse] = asyncio.get_event_loop().create_future()
        self._pending_requests[seq] = future

        try:
            # Send request
            await self._transport.send(request.model_dump(by_alias=True))

            # Wait for response with timeout
            try:
                async with asyncio.timeout(timeout):
                    response = await future
            except TimeoutError as e:
                raise DAPTimeoutError(f"Timeout waiting for response to '{command}'") from e

            # Check for error response
            if not response.success:
                raise DAPError(
                    f"DAP request '{command}' failed: {response.message or 'Unknown error'}"
                )

            return response

        finally:
            self._pending_requests.pop(seq, None)

    async def _receive_loop(self) -> None:
        """Background task to receive and dispatch messages."""
        try:
            while self._transport.is_connected:
                try:
                    message = await self._transport.receive()
                except Exception:
                    # Connection closed or protocol error
                    if self._transport.is_connected:
                        # Unexpected error
                        raise
                    # Expected disconnection
                    break

                msg_type = message.get("type")

                if msg_type == "response":
                    await self._handle_response(message)
                elif msg_type == "event":
                    await self._handle_event(message)
                else:
                    # Unknown message type, ignore
                    pass

        except asyncio.CancelledError:
            pass
        except Exception:
            # Log error but don't crash
            # In production, we'd want proper logging here
            pass

    async def _handle_response(self, message: dict[str, Any]) -> None:
        """Handle a response message."""
        try:
            response = DAPResponse.model_validate(message)
        except Exception as e:
            raise DAPProtocolError(f"Invalid response message: {e}") from e

        future = self._pending_requests.get(response.request_seq)
        if future and not future.done():
            future.set_result(response)

    def _ensure_events(self) -> None:
        """Ensure event objects exist (created in current event loop)."""
        if self._initialized_event is None:
            self._initialized_event = asyncio.Event()
        if self._stopped_event is None:
            self._stopped_event = asyncio.Event()

    async def _handle_event(self, message: dict[str, Any]) -> None:
        """Handle an event message."""
        try:
            event = DAPEvent.model_validate(message)
        except Exception as e:
            raise DAPProtocolError(f"Invalid event message: {e}") from e

        # Ensure events are initialized
        self._ensure_events()

        # Handle internal state tracking
        if event.event == "initialized":
            self._initialized_event.set()  # type: ignore[union-attr]
        elif event.event == "stopped":
            self._last_stop_info = event.body or {}
            self._stopped_event.set()  # type: ignore[union-attr]

        # Dispatch to all handlers
        for handler in self._event_handlers:
            try:
                result = handler(event)
                if asyncio.iscoroutine(result):
                    await result
            except Exception:
                # Don't let one handler crash others
                # In production, we'd want proper logging here
                pass

    async def wait_for_stop(self, timeout: float = 30.0) -> dict[str, Any]:
        """Wait for the debuggee to stop (breakpoint, exception, etc.).

        Args:
            timeout: Maximum time to wait in seconds.

        Returns:
            Stop information dict with 'reason', 'threadId', etc.

        Raises:
            DAPTimeoutError: If no stop event within timeout.
        """
        self._ensure_events()
        self._stopped_event.clear()  # type: ignore[union-attr]
        try:
            await asyncio.wait_for(
                self._stopped_event.wait(),  # type: ignore[union-attr]
                timeout=timeout,
            )
        except TimeoutError as e:
            raise DAPTimeoutError("Timeout waiting for stop event") from e
        return self._last_stop_info.copy()

    @property
    def last_stop_info(self) -> dict[str, Any]:
        """Get info from the most recent stop event."""
        return self._last_stop_info.copy()

    @property
    def capabilities(self) -> dict[str, Any]:
        """Get adapter capabilities (available after initialize)."""
        return self._capabilities.copy()

    @property
    def is_connected(self) -> bool:
        """Check if connected to adapter."""
        return self._transport.is_connected

    @property
    def is_initialized(self) -> bool:
        """Check if initialized."""
        return self._initialized

    @property
    def is_configuration_done(self) -> bool:
        """Check if configurationDone has been sent."""
        return self._configuration_done
