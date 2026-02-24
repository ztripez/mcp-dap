"""Tests for type models."""

from __future__ import annotations

from mcp_dap.types import Breakpoint
from mcp_dap.types import SessionState
from mcp_dap.types import StackFrame
from mcp_dap.types import StopReason
from mcp_dap.types import Variable


class TestSessionState:
    """Tests for SessionState enum."""

    def test_states_exist(self) -> None:
        """Test that all expected states exist."""
        assert SessionState.INITIALIZING == "initializing"
        assert SessionState.RUNNING == "running"
        assert SessionState.STOPPED == "stopped"
        assert SessionState.TERMINATED == "terminated"


class TestStopReason:
    """Tests for StopReason enum."""

    def test_common_reasons(self) -> None:
        """Test common stop reasons."""
        assert StopReason.BREAKPOINT == "breakpoint"
        assert StopReason.STEP == "step"
        assert StopReason.EXCEPTION == "exception"
        assert StopReason.PAUSE == "pause"


class TestBreakpoint:
    """Tests for Breakpoint model."""

    def test_minimal_breakpoint(self) -> None:
        """Test creating a minimal breakpoint."""
        bp = Breakpoint(verified=True)
        assert bp.verified is True
        assert bp.id is None
        assert bp.line is None

    def test_full_breakpoint(self) -> None:
        """Test creating a fully specified breakpoint."""
        bp = Breakpoint(
            id=1,
            verified=True,
            source_path="/test.py",
            line=42,
            column=1,
        )
        assert bp.id == 1
        assert bp.line == 42
        assert bp.source_path == "/test.py"


class TestStackFrame:
    """Tests for StackFrame model."""

    def test_stack_frame(self) -> None:
        """Test creating a stack frame."""
        frame = StackFrame(
            id=1,
            name="main",
            line=10,
            column=0,
        )
        assert frame.id == 1
        assert frame.name == "main"
        assert frame.line == 10


class TestVariable:
    """Tests for Variable model."""

    def test_simple_variable(self) -> None:
        """Test creating a simple variable."""
        var = Variable(name="x", value="42", type="int")
        assert var.name == "x"
        assert var.value == "42"
        assert var.type == "int"
        assert var.variables_reference == 0

    def test_expandable_variable(self) -> None:
        """Test creating an expandable variable."""
        var = Variable(
            name="data",
            value="{'a': 1, 'b': 2}",
            type="dict",
            variables_reference=100,
            named_variables=2,
        )
        assert var.variables_reference == 100
        assert var.named_variables == 2
