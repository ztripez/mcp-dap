"""MCP server implementation for DAP bridge."""

from __future__ import annotations

import asyncio
import json
from typing import TYPE_CHECKING
from typing import Any

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import EmbeddedResource
from mcp.types import Resource
from mcp.types import TextContent
from mcp.types import Tool
from pydantic import BaseModel
from pydantic import ConfigDict
from pydantic import Field

from mcp_dap.exceptions import MCPDAPError
from mcp_dap.exceptions import SessionNotFoundError
from mcp_dap.session import SessionManager
from mcp_dap.types import SessionState

if TYPE_CHECKING:
    from mcp_dap.dap.messages import DAPEvent

# === Tool Input Models ===


class LaunchInput(BaseModel):
    """Input for debug_launch tool."""

    adapter: str = Field(default="debugpy", description="Debug adapter to use")
    program: str | None = Field(
        default=None,
        description="Path to the program to debug. Required unless cargo_args is provided.",
    )
    args: list[str] = Field(default_factory=list, description="Command line arguments")
    cwd: str | None = Field(default=None, description="Working directory")
    env: dict[str, str] = Field(default_factory=dict, description="Environment variables")
    stop_on_entry: bool = Field(default=False, description="Stop on entry point")
    # Rust/Cargo-specific options
    cargo_args: list[str] | None = Field(
        default=None,
        description="Cargo build arguments (e.g., ['build', '--bin', 'myapp']). "
        "If provided, builds with cargo and debugs the result.",
    )


class AttachInput(BaseModel):
    """Input for debug_attach tool."""

    model_config = ConfigDict(extra="allow")

    adapter: str = Field(default="debugpy", description="Debug adapter to use")
    host: str | None = Field(default=None, description="Host to connect to (remote attach)")
    port: int | None = Field(default=None, description="Port to connect to (remote attach)")
    pid: int | None = Field(default=None, description="Process ID to attach to (local attach)")


class SessionInput(BaseModel):
    """Input requiring session_id."""

    session_id: str = Field(description="Debug session ID")


class SetBreakpointsInput(BaseModel):
    """Input for debug_set_breakpoints tool."""

    session_id: str = Field(description="Debug session ID")
    file: str = Field(description="Path to source file")
    breakpoints: list[dict[str, Any]] = Field(
        description="List of breakpoints: [{line: int, condition?: str}]"
    )


class ClearBreakpointsInput(BaseModel):
    """Input for debug_clear_breakpoints tool."""

    session_id: str = Field(description="Debug session ID")
    file: str = Field(description="Path to source file")


class ExecutionInput(BaseModel):
    """Input for execution control tools."""

    session_id: str = Field(description="Debug session ID")
    thread_id: int | None = Field(
        default=None, description="Thread ID (uses stopped thread if not specified)"
    )


class StackTraceInput(BaseModel):
    """Input for debug_get_stack_trace tool."""

    session_id: str = Field(description="Debug session ID")
    thread_id: int | None = Field(default=None, description="Thread ID")
    levels: int = Field(default=20, description="Number of frames to retrieve")


class ScopesInput(BaseModel):
    """Input for debug_get_scopes tool."""

    session_id: str = Field(description="Debug session ID")
    frame_id: int = Field(description="Stack frame ID")


class VariablesInput(BaseModel):
    """Input for debug_get_variables tool."""

    session_id: str = Field(description="Debug session ID")
    variables_reference: int = Field(description="Variables reference from scope or variable")
    filter: str | None = Field(default=None, description="Filter: 'indexed' or 'named'")


class EvaluateInput(BaseModel):
    """Input for debug_evaluate tool."""

    session_id: str = Field(description="Debug session ID")
    expression: str = Field(description="Expression to evaluate")
    frame_id: int | None = Field(default=None, description="Stack frame context")
    context: str = Field(default="repl", description="Context: repl, watch, hover")


# === Server Implementation ===


class MCPDAPServer:
    """MCP server exposing DAP debugging capabilities."""

    def __init__(self) -> None:
        """Initialize the MCP-DAP server."""
        self.server = Server("mcp-dap")
        self.session_manager = SessionManager()

        # Register event callback for logging
        self.session_manager.add_event_callback(self._on_debug_event)

        # Register handlers
        self._register_tools()
        self._register_resources()

    def _register_tools(self) -> None:
        """Register all MCP tools."""

        @self.server.list_tools()  # type: ignore[no-untyped-call, untyped-decorator]
        async def list_tools() -> list[Tool]:
            return [
                Tool(
                    name="debug_launch",
                    description=(
                        "Launch a program for debugging. Returns session_id for subsequent operations. "
                        "For Rust: use adapter='rust' with either 'program' (pre-built binary) or "
                        "'cargo_args' (e.g., ['build', '--bin', 'myapp']) to build and debug."
                    ),
                    inputSchema=LaunchInput.model_json_schema(),
                ),
                Tool(
                    name="debug_attach",
                    description=(
                        "Attach to a running debug server or process. Returns session_id for subsequent operations. "
                        "For Python: provide host/port. For Rust: provide pid or program name."
                    ),
                    inputSchema=AttachInput.model_json_schema(),
                ),
                Tool(
                    name="debug_disconnect",
                    description="Disconnect from a debug session and optionally terminate the debuggee.",
                    inputSchema=SessionInput.model_json_schema(),
                ),
                Tool(
                    name="debug_set_breakpoints",
                    description="Set breakpoints in a source file. Replaces all existing breakpoints in that file.",
                    inputSchema=SetBreakpointsInput.model_json_schema(),
                ),
                Tool(
                    name="debug_clear_breakpoints",
                    description="Clear all breakpoints in a source file.",
                    inputSchema=ClearBreakpointsInput.model_json_schema(),
                ),
                Tool(
                    name="debug_continue",
                    description="Continue execution. Blocks until execution stops (breakpoint, exception, etc.).",
                    inputSchema=ExecutionInput.model_json_schema(),
                ),
                Tool(
                    name="debug_step_over",
                    description="Step over to the next line. Blocks until step completes.",
                    inputSchema=ExecutionInput.model_json_schema(),
                ),
                Tool(
                    name="debug_step_into",
                    description="Step into function call. Blocks until step completes.",
                    inputSchema=ExecutionInput.model_json_schema(),
                ),
                Tool(
                    name="debug_step_out",
                    description="Step out of current function. Blocks until step completes.",
                    inputSchema=ExecutionInput.model_json_schema(),
                ),
                Tool(
                    name="debug_pause",
                    description="Pause execution.",
                    inputSchema=ExecutionInput.model_json_schema(),
                ),
                Tool(
                    name="debug_get_threads",
                    description="Get all threads in the debuggee.",
                    inputSchema=SessionInput.model_json_schema(),
                ),
                Tool(
                    name="debug_get_stack_trace",
                    description="Get the call stack for a thread.",
                    inputSchema=StackTraceInput.model_json_schema(),
                ),
                Tool(
                    name="debug_get_scopes",
                    description="Get variable scopes for a stack frame (locals, globals, etc.).",
                    inputSchema=ScopesInput.model_json_schema(),
                ),
                Tool(
                    name="debug_get_variables",
                    description="Get variables for a scope or expandable variable.",
                    inputSchema=VariablesInput.model_json_schema(),
                ),
                Tool(
                    name="debug_evaluate",
                    description="Evaluate an expression in the debuggee context.",
                    inputSchema=EvaluateInput.model_json_schema(),
                ),
                Tool(
                    name="debug_get_pending_events",
                    description="Get pending debug events (stopped, output, etc.) since last call.",
                    inputSchema=SessionInput.model_json_schema(),
                ),
                Tool(
                    name="debug_get_output",
                    description="Get debuggee output (stdout/stderr) since last call.",
                    inputSchema=SessionInput.model_json_schema(),
                ),
            ]

        @self.server.call_tool()  # type: ignore[untyped-decorator]
        async def call_tool(
            name: str, arguments: dict[str, Any]
        ) -> list[TextContent | EmbeddedResource]:
            try:
                result = await self._handle_tool(name, arguments)
                return [TextContent(type="text", text=json.dumps(result, indent=2))]
            except MCPDAPError as e:
                return [TextContent(type="text", text=json.dumps({"error": str(e)}))]
            except Exception as e:
                return [
                    TextContent(type="text", text=json.dumps({"error": f"Internal error: {e}"}))
                ]

    async def _handle_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        """Handle a tool call."""

        if name == "debug_launch":
            launch_inp = LaunchInput.model_validate(arguments)

            # Validate: either program or cargo_args must be provided
            if launch_inp.program is None and launch_inp.cargo_args is None:
                raise MCPDAPError("Either 'program' or 'cargo_args' must be provided")

            session = await self.session_manager.create_session(
                adapter_name=launch_inp.adapter,
                program=launch_inp.program,
                cwd=launch_inp.cwd,
                env=launch_inp.env or None,
            )
            await session.launch(
                program=launch_inp.program,
                args=launch_inp.args,
                cwd=launch_inp.cwd,
                env=launch_inp.env or None,
                stop_on_entry=launch_inp.stop_on_entry,
                cargo_args=launch_inp.cargo_args,
            )
            return {
                "session_id": session.session_id,
                "adapter": launch_inp.adapter,
                "program": session._program,  # Use actual program (may be from cargo build)
                "state": session.state.value,
            }

        if name == "debug_attach":
            attach_inp = AttachInput.model_validate(arguments)
            # Extract any extra arguments for the adapter
            kwargs = attach_inp.model_dump(exclude={"adapter", "host", "port"})

            session = await self.session_manager.create_session(
                adapter_name=attach_inp.adapter,
                host=attach_inp.host,
                port=attach_inp.port,
                **kwargs,
            )
            await session.attach(
                host=attach_inp.host,
                port=attach_inp.port,
                **kwargs,
            )
            return {
                "session_id": session.session_id,
                "adapter": attach_inp.adapter,
                "host": attach_inp.host,
                "port": attach_inp.port,
                "pid": attach_inp.pid,
                "state": session.state.value,
            }

        if name == "debug_disconnect":
            session_inp = SessionInput.model_validate(arguments)
            await self.session_manager.close_session(session_inp.session_id)
            return {"success": True, "session_id": session_inp.session_id}

        if name == "debug_set_breakpoints":
            bp_inp = SetBreakpointsInput.model_validate(arguments)
            session = await self.session_manager.get_session(bp_inp.session_id)
            breakpoints = await session.set_breakpoints(bp_inp.file, bp_inp.breakpoints)
            return {
                "file": bp_inp.file,
                "breakpoints": [bp.model_dump() for bp in breakpoints],
            }

        if name == "debug_clear_breakpoints":
            clear_inp = ClearBreakpointsInput.model_validate(arguments)
            session = await self.session_manager.get_session(clear_inp.session_id)
            await session.clear_breakpoints(clear_inp.file)
            return {"file": clear_inp.file, "cleared": True}

        if name == "debug_continue":
            exec_inp = ExecutionInput.model_validate(arguments)
            session = await self.session_manager.get_session(exec_inp.session_id)
            stopped = await session.continue_execution(exec_inp.thread_id, wait=True)
            return self._stopped_result(session, stopped)

        if name == "debug_step_over":
            exec_inp = ExecutionInput.model_validate(arguments)
            session = await self.session_manager.get_session(exec_inp.session_id)
            stopped = await session.step_over(exec_inp.thread_id, wait=True)
            return self._stopped_result(session, stopped)

        if name == "debug_step_into":
            exec_inp = ExecutionInput.model_validate(arguments)
            session = await self.session_manager.get_session(exec_inp.session_id)
            stopped = await session.step_into(exec_inp.thread_id, wait=True)
            return self._stopped_result(session, stopped)

        if name == "debug_step_out":
            exec_inp = ExecutionInput.model_validate(arguments)
            session = await self.session_manager.get_session(exec_inp.session_id)
            stopped = await session.step_out(exec_inp.thread_id, wait=True)
            return self._stopped_result(session, stopped)

        if name == "debug_pause":
            exec_inp = ExecutionInput.model_validate(arguments)
            session = await self.session_manager.get_session(exec_inp.session_id)
            await session.pause(exec_inp.thread_id)
            return {"paused": True}

        if name == "debug_get_threads":
            session_inp = SessionInput.model_validate(arguments)
            session = await self.session_manager.get_session(session_inp.session_id)
            threads = await session.get_threads()
            return {"threads": [t.model_dump() for t in threads]}

        if name == "debug_get_stack_trace":
            stack_inp = StackTraceInput.model_validate(arguments)
            session = await self.session_manager.get_session(stack_inp.session_id)
            frames = await session.get_stack_trace(stack_inp.thread_id, levels=stack_inp.levels)
            return {"frames": [f.model_dump() for f in frames]}

        if name == "debug_get_scopes":
            scopes_inp = ScopesInput.model_validate(arguments)
            session = await self.session_manager.get_session(scopes_inp.session_id)
            scopes = await session.get_scopes(scopes_inp.frame_id)
            return {"scopes": [s.model_dump() for s in scopes]}

        if name == "debug_get_variables":
            vars_inp = VariablesInput.model_validate(arguments)
            session = await self.session_manager.get_session(vars_inp.session_id)
            variables = await session.get_variables(vars_inp.variables_reference, vars_inp.filter)
            return {"variables": [v.model_dump() for v in variables]}

        if name == "debug_evaluate":
            eval_inp = EvaluateInput.model_validate(arguments)
            session = await self.session_manager.get_session(eval_inp.session_id)
            result = await session.evaluate(
                eval_inp.expression, eval_inp.frame_id, eval_inp.context
            )
            return result.model_dump()

        if name == "debug_get_pending_events":
            session_inp = SessionInput.model_validate(arguments)
            session = await self.session_manager.get_session(session_inp.session_id)
            events = session.get_pending_events()
            return {"events": [{"event": e.event, "body": e.body} for e in events]}

        if name == "debug_get_output":
            session_inp = SessionInput.model_validate(arguments)
            session = await self.session_manager.get_session(session_inp.session_id)
            output = session.get_output()
            return {"output": [o.model_dump() for o in output]}

        raise MCPDAPError(f"Unknown tool: {name}")

    def _stopped_result(self, session: Any, stopped: Any) -> dict[str, Any]:
        """Build result for stopped execution."""
        result: dict[str, Any] = {"state": session.state.value}

        if session.state == SessionState.TERMINATED:
            result["terminated"] = True
            return result

        if stopped:
            result["reason"] = stopped.reason.value
            result["thread_id"] = stopped.thread_id
        else:
            result["timeout"] = True

        return result

    def _get_adapter_info(self) -> dict[str, Any]:
        """Get information about available debug adapters."""
        return self.session_manager.config.get_adapter_info()

    def _register_resources(self) -> None:
        """Register MCP resources."""

        @self.server.list_resources()  # type: ignore[no-untyped-call, untyped-decorator]
        async def list_resources() -> list[Resource]:
            resources: list[Resource] = [
                Resource(
                    uri="debug://adapters",  # type: ignore[arg-type]
                    name="Available Debug Adapters",
                    description="List of available debug adapters and their capabilities",
                    mimeType="application/json",
                ),
                Resource(
                    uri="debug://sessions",  # type: ignore[arg-type]
                    name="Debug Sessions",
                    description="List of active debug sessions",
                    mimeType="application/json",
                ),
            ]

            # Add per-session resources
            for session_info in self.session_manager.list_sessions():
                sid = session_info.session_id
                resources.extend(
                    [
                        Resource(
                            uri=f"debug://{sid}/state",  # type: ignore[arg-type]
                            name=f"Session {sid[:8]} State",
                            description="Current debug session state",
                            mimeType="application/json",
                        ),
                        Resource(
                            uri=f"debug://{sid}/threads",  # type: ignore[arg-type]
                            name=f"Session {sid[:8]} Threads",
                            description="Threads in debug session",
                            mimeType="application/json",
                        ),
                        Resource(
                            uri=f"debug://{sid}/breakpoints",  # type: ignore[arg-type]
                            name=f"Session {sid[:8]} Breakpoints",
                            description="Active breakpoints",
                            mimeType="application/json",
                        ),
                    ]
                )

            return resources

        @self.server.read_resource()  # type: ignore[no-untyped-call, untyped-decorator]
        async def read_resource(uri: str) -> str:
            if uri == "debug://adapters":
                return json.dumps(self._get_adapter_info(), indent=2)

            if uri == "debug://sessions":
                sessions = self.session_manager.list_sessions()
                return json.dumps([s.model_dump() for s in sessions], indent=2)

            # Parse session-specific URIs
            if uri.startswith("debug://"):
                parts = uri[8:].split("/")
                if len(parts) >= 2:
                    session_id = parts[0]
                    resource_type = parts[1]

                    try:
                        session = await self.session_manager.get_session(session_id)
                    except SessionNotFoundError:
                        return json.dumps({"error": f"Session not found: {session_id}"})

                    if resource_type == "state":
                        return json.dumps(session.get_info().model_dump(), indent=2)
                    elif resource_type == "threads":
                        threads = await session.get_threads()
                        return json.dumps([t.model_dump() for t in threads], indent=2)
                    elif resource_type == "breakpoints":
                        return json.dumps(
                            {
                                path: [bp.model_dump() for bp in bps]
                                for path, bps in session.breakpoints.items()
                            },
                            indent=2,
                        )

            return json.dumps({"error": f"Unknown resource: {uri}"})

    def _on_debug_event(self, session_id: str, event: DAPEvent) -> None:
        """Handle debug events for logging/notifications."""
        # In a full implementation, we'd send MCP notifications here
        # For now, events are cached in the session for polling
        pass

    async def run(self) -> None:
        """Run the MCP server."""
        async with stdio_server() as (read_stream, write_stream):
            await self.server.run(
                read_stream,
                write_stream,
                self.server.create_initialization_options(),
            )


async def serve() -> None:
    """Start the MCP-DAP server."""
    server = MCPDAPServer()
    await server.run()


def main() -> None:
    """Entry point for mcp-dap command."""
    asyncio.run(serve())


if __name__ == "__main__":
    main()
