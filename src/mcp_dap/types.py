"""Pydantic models for mcp-dap."""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel
from pydantic import Field

# === Session State ===


class SessionState(StrEnum):
    """Debug session state."""

    INITIALIZING = "initializing"
    RUNNING = "running"
    STOPPED = "stopped"
    TERMINATED = "terminated"


class StopReason(StrEnum):
    """Reason why execution stopped."""

    BREAKPOINT = "breakpoint"
    STEP = "step"
    EXCEPTION = "exception"
    PAUSE = "pause"
    ENTRY = "entry"
    GOTO = "goto"
    FUNCTION_BREAKPOINT = "function breakpoint"
    DATA_BREAKPOINT = "data breakpoint"


# === Breakpoints ===


class SourceBreakpoint(BaseModel):
    """A breakpoint in source code."""

    line: int
    column: int | None = None
    condition: str | None = None
    hit_condition: str | None = None
    log_message: str | None = None


class Breakpoint(BaseModel):
    """A verified breakpoint returned by the adapter."""

    id: int | None = None
    verified: bool
    message: str | None = None
    source_path: str | None = None
    line: int | None = None
    column: int | None = None
    end_line: int | None = None
    end_column: int | None = None


# === Threads and Stack ===


class Thread(BaseModel):
    """A thread in the debuggee."""

    id: int
    name: str


class Source(BaseModel):
    """Source file information."""

    name: str | None = None
    path: str | None = None
    source_reference: int | None = None


class StackFrame(BaseModel):
    """A stack frame."""

    id: int
    name: str
    source: Source | None = None
    line: int
    column: int
    end_line: int | None = None
    end_column: int | None = None
    module_id: int | str | None = None


# === Variables and Scopes ===


class Scope(BaseModel):
    """A scope containing variables."""

    name: str
    presentation_hint: str | None = None
    variables_reference: int
    named_variables: int | None = None
    indexed_variables: int | None = None
    expensive: bool = False
    source: Source | None = None
    line: int | None = None
    column: int | None = None
    end_line: int | None = None
    end_column: int | None = None


class Variable(BaseModel):
    """A variable."""

    name: str
    value: str
    type: str | None = None
    presentation_hint: dict[str, Any] | None = None
    evaluate_name: str | None = None
    variables_reference: int = 0
    named_variables: int | None = None
    indexed_variables: int | None = None


# === Events ===


class StoppedEvent(BaseModel):
    """Event when execution stops."""

    reason: StopReason
    description: str | None = None
    thread_id: int | None = None
    preserve_focus_hint: bool = False
    text: str | None = None
    all_threads_stopped: bool = False
    hit_breakpoint_ids: list[int] = Field(default_factory=list)


class OutputEvent(BaseModel):
    """Event for debuggee output."""

    category: str = "console"  # console, stdout, stderr, telemetry
    output: str
    group: str | None = None  # start, startCollapsed, end
    variables_reference: int | None = None
    source: Source | None = None
    line: int | None = None
    column: int | None = None


class TerminatedEvent(BaseModel):
    """Event when debug session terminates."""

    restart: bool | dict[str, Any] | None = None


# === Launch/Attach Configuration ===


class LaunchConfig(BaseModel):
    """Configuration for launching a debug session."""

    program: str
    args: list[str] = Field(default_factory=list)
    cwd: str | None = None
    env: dict[str, str] = Field(default_factory=dict)
    stop_on_entry: bool = False
    console: str = "integratedTerminal"  # or externalTerminal, internalConsole


class AttachConfig(BaseModel):
    """Configuration for attaching to a running process."""

    host: str = "127.0.0.1"
    port: int


# === Session Info ===


class SessionInfo(BaseModel):
    """Information about a debug session."""

    session_id: str
    adapter: str
    state: SessionState
    program: str | None = None
    threads: list[Thread] = Field(default_factory=list)
    stopped_thread_id: int | None = None
    stop_reason: StopReason | None = None


# === Evaluate Result ===


class EvaluateResult(BaseModel):
    """Result of expression evaluation."""

    result: str
    type: str | None = None
    presentation_hint: dict[str, Any] | None = None
    variables_reference: int = 0
    named_variables: int | None = None
    indexed_variables: int | None = None
