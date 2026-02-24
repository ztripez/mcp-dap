"""DAP message types.

DAP has three message types:
- Request: client → adapter (with seq, command, arguments)
- Response: adapter → client (with request_seq, success, body)
- Event: adapter → client (with event, body)
"""

from __future__ import annotations

from typing import Any
from typing import Literal

from pydantic import BaseModel
from pydantic import Field


class DAPMessage(BaseModel):
    """Base class for all DAP messages."""

    seq: int


class DAPRequest(DAPMessage):
    """A DAP request message from client to adapter."""

    type: Literal["request"] = "request"
    command: str
    arguments: dict[str, Any] | None = None


class DAPResponse(DAPMessage):
    """A DAP response message from adapter to client."""

    type: Literal["response"] = "response"
    request_seq: int
    success: bool
    command: str
    message: str | None = None
    body: dict[str, Any] | None = None


class DAPEvent(DAPMessage):
    """A DAP event message from adapter to client."""

    type: Literal["event"] = "event"
    event: str
    body: dict[str, Any] | None = None


# === Request argument types ===


class InitializeArguments(BaseModel):
    """Arguments for the initialize request."""

    client_id: str | None = Field(default=None, alias="clientID")
    client_name: str | None = Field(default=None, alias="clientName")
    adapter_id: str = Field(alias="adapterID")
    locale: str | None = None
    lines_start_at1: bool = Field(default=True, alias="linesStartAt1")
    columns_start_at1: bool = Field(default=True, alias="columnsStartAt1")
    path_format: str | None = Field(default=None, alias="pathFormat")
    supports_variable_type: bool = Field(default=False, alias="supportsVariableType")
    supports_variable_paging: bool = Field(default=False, alias="supportsVariablePaging")
    supports_run_in_terminal_request: bool = Field(
        default=False, alias="supportsRunInTerminalRequest"
    )
    supports_memory_references: bool = Field(default=False, alias="supportsMemoryReferences")
    supports_progress_reporting: bool = Field(default=False, alias="supportsProgressReporting")
    supports_invalidated_event: bool = Field(default=False, alias="supportsInvalidatedEvent")

    model_config = {"populate_by_name": True}


class LaunchArguments(BaseModel):
    """Arguments for the launch request."""

    no_debug: bool = Field(False, alias="noDebug")
    restart: Any | None = Field(None, alias="__restart")

    # Common debugpy-specific arguments
    program: str | None = None
    args: list[str] = Field(default_factory=list)
    cwd: str | None = None
    env: dict[str, str] = Field(default_factory=dict)
    stop_on_entry: bool = Field(False, alias="stopOnEntry")
    console: str = "integratedTerminal"

    model_config = {"populate_by_name": True, "extra": "allow"}


class AttachArguments(BaseModel):
    """Arguments for the attach request."""

    restart: Any | None = Field(None, alias="__restart")

    # Common debugpy-specific arguments
    host: str = "127.0.0.1"
    port: int
    connect: dict[str, Any] | None = None

    model_config = {"populate_by_name": True, "extra": "allow"}


class SetBreakpointsArguments(BaseModel):
    """Arguments for the setBreakpoints request."""

    source: dict[str, Any]
    breakpoints: list[dict[str, Any]] | None = None
    lines: list[int] | None = None
    source_modified: bool = Field(False, alias="sourceModified")

    model_config = {"populate_by_name": True}


class StackTraceArguments(BaseModel):
    """Arguments for the stackTrace request."""

    thread_id: int = Field(alias="threadId")
    start_frame: int | None = Field(None, alias="startFrame")
    levels: int | None = None
    format: dict[str, Any] | None = None

    model_config = {"populate_by_name": True}


class ScopesArguments(BaseModel):
    """Arguments for the scopes request."""

    frame_id: int = Field(alias="frameId")

    model_config = {"populate_by_name": True}


class VariablesArguments(BaseModel):
    """Arguments for the variables request."""

    variables_reference: int = Field(alias="variablesReference")
    filter: str | None = None  # "indexed", "named"
    start: int | None = None
    count: int | None = None
    format: dict[str, Any] | None = None

    model_config = {"populate_by_name": True}


class EvaluateArguments(BaseModel):
    """Arguments for the evaluate request."""

    expression: str
    frame_id: int | None = Field(None, alias="frameId")
    context: str | None = None  # "watch", "repl", "hover", "clipboard"
    format: dict[str, Any] | None = None

    model_config = {"populate_by_name": True}


class ContinueArguments(BaseModel):
    """Arguments for the continue request."""

    thread_id: int = Field(alias="threadId")
    single_thread: bool = Field(False, alias="singleThread")

    model_config = {"populate_by_name": True}


class StepArguments(BaseModel):
    """Arguments for step requests (next, stepIn, stepOut)."""

    thread_id: int = Field(alias="threadId")
    single_thread: bool = Field(False, alias="singleThread")
    granularity: str | None = None  # "statement", "line", "instruction"

    model_config = {"populate_by_name": True}


class PauseArguments(BaseModel):
    """Arguments for the pause request."""

    thread_id: int = Field(alias="threadId")

    model_config = {"populate_by_name": True}


class DisconnectArguments(BaseModel):
    """Arguments for the disconnect request."""

    restart: bool = False
    terminate_debuggee: bool = Field(False, alias="terminateDebuggee")
    suspend_debuggee: bool = Field(False, alias="suspendDebuggee")

    model_config = {"populate_by_name": True}
