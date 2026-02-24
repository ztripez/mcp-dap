# AGENTS.md - Coding Agent Instructions

This file contains instructions for AI coding agents working on the mcp-dap codebase.

## Project Overview

MCP-DAP is a bridge that enables code agents to debug processes using the Debug Adapter
Protocol (DAP). It exposes DAP capabilities through an MCP (Model Context Protocol) server.

## Build & Development Commands

### Setup

```bash
uv venv && source .venv/bin/activate && uv sync
```

### Testing

```bash
uv run pytest                                    # Run all tests
uv run pytest tests/test_server.py               # Run a single test file
uv run pytest tests/test_server.py::test_serve   # Run a single test function
uv run pytest -k "test_serve"                    # Run tests matching pattern
uv run pytest --cov=src/mcp_dap                  # Run with coverage
uv run pytest -m "not slow"                      # Exclude slow tests
```

### Linting & Formatting

```bash
uv run ruff check .              # Check linting
uv run ruff check --fix .        # Auto-fix linting
uv run ruff format .             # Apply formatting
uv run mypy src                  # Type checking
```

### Dependency Management

```bash
uv add <package>                 # Add a dependency
uv add --dev <package>           # Add a dev dependency
uv lock                          # Update lock file
uv sync                          # Sync dependencies from lock file
```

## Code Style Guidelines

### Imports

- Use `from __future__ import annotations` at the top of every module
- One import per line (enforced by ruff isort)
- Order: stdlib → third-party → first-party (mcp_dap)
- Use `TYPE_CHECKING` block for type-only imports

```python
from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from pydantic import BaseModel

from mcp_dap.types import DebugSession

if TYPE_CHECKING:
    from mcp_dap.protocol import DAPClient
```

### Formatting

- Line length: 100 characters max
- Indent: 4 spaces (no tabs)
- Quote style: double quotes
- Use pathlib.Path instead of os.path

### Type Annotations

- **All functions must have complete type annotations** (mypy strict mode)
- Use modern syntax: `list[str]` not `List[str]`, `str | None` not `Optional[str]`
- Always annotate return types including `-> None`

```python
def process_events(self, events: list[Event]) -> list[Result]: ...
async def connect(self, timeout: float | None = None) -> Self: ...
```

### Naming Conventions

- Modules: `snake_case.py`
- Classes: `PascalCase`
- Functions/methods: `snake_case`
- Constants: `UPPER_SNAKE_CASE`
- Private: prefix with `_`

### Error Handling

- **Fail loudly**: never silently swallow exceptions
- Define exceptions in `mcp_dap.exceptions`
- Use `raise ... from e` to preserve exception chains

```python
try:
    await self._connect()
except ConnectionError as e:
    raise DAPConnectionError(f"Failed to connect to {self.host}:{self.port}") from e
```

### Async Patterns

- Use `async/await` for all I/O operations
- Prefer `anyio` over `asyncio` for cross-compatibility
- Use structured concurrency with task groups

```python
async with anyio.create_task_group() as tg:
    tg.start_soon(self._read_loop)
    tg.start_soon(self._write_loop)
```

### Pydantic Models

- Use Pydantic v2 for all data models at boundaries
- Use `model_validate()` and `model_dump()` (not dict/parse_obj)
- Validate all external input immediately

```python
class BreakpointRequest(BaseModel):
    source: str
    line: int
    condition: str | None = None
```

### Docstrings

Use Google-style docstrings for all public functions. For adapter classes, the **class docstring** is used as the adapter's description in the MCP resource.

```python
def set_breakpoint(self, source: str, line: int) -> Breakpoint:
    """Set a breakpoint at the specified location.

    Args:
        source: Path to the source file.
        line: Line number (1-indexed).

    Returns:
        The created Breakpoint object.

    Raises:
        DAPError: If the debug adapter rejects the breakpoint.
    """
```

### Testing

- Test files: `tests/test_<module>.py`
- Test functions: `test_<behavior>` or `test_<function>_<scenario>`
- Use `pytest.mark.asyncio` for async tests
- Mark slow tests with `@pytest.mark.slow`

## Project Structure

```
mcp-dap/
  src/mcp_dap/       # Main package
    server.py        # MCP server entry point
    session.py       # SessionManager, DebugSession
    config.py        # Server configuration (Pydantic Settings)
    types.py         # Pydantic models
    exceptions.py    # Custom exceptions
    dap/             # DAP protocol implementation
      client.py      # DAPClient - async DAP communication
      transport.py   # StdioTransport, SocketTransport
      messages.py    # DAP message types
      protocol.py    # Message framing (Content-Length)
    adapters/        # Debug adapter configurations
      base.py        # AdapterConfig base class and @adapter decorator
      debugpy.py     # Python debugpy adapter
      codelldb.py    # Rust/C++ CodeLLDB adapter
  tests/             # Test suite
  pyproject.toml     # Project config
```

## Common Tasks

### Adding a new Debug Adapter

1. Create a new module in `src/mcp_dap/adapters/`.
2. Define Pydantic models for launch and attach configurations (inheriting from `BaseLaunchConfig` and `BaseAttachConfig`).
3. Define the adapter class inheriting from `AdapterConfig`.
4. Use the `@adapter` decorator to register the class and set metadata.
5. Provide a clear class docstring (it will be used as the adapter's description).
6. Implement abstract methods: `launch_config_class`, `attach_config_class`, `create_transport`, `get_launch_arguments`, and `get_attach_arguments`.

Example:
```python
@adapter(
    name="myadapter",
    adapter_id="myid",
    file_extensions=[".ext"],
    aliases=["alias"],
)
class MyAdapter(AdapterConfig):
    """My clear description of the adapter."""
    # ...
```

### Configuring the Server

Configuration can be set via:
- **Environment Variables**: Prefixed with `MCP_DAP_` (e.g., `MCP_DAP_LOG_LEVEL=DEBUG`). Nested settings use `__` (e.g., `MCP_DAP_ADAPTERS__DEBUGPY__PYTHON_PATH=/usr/bin/python3`).
- **TOML File**: `mcp-dap.toml` in the working directory or `~/.config/mcp-dap/config.toml`.

### Adding a new MCP tool

1. Define the tool in `server.py` using MCP SDK decorators.
2. Create request/response models in `server.py` (input schemas).
3. Implement handler in `MCPDAPServer._handle_tool` with proper error handling.
4. Add tests in `tests/test_server.py`.

### Adding DAP protocol support

1. Implement message types in `dap/messages.py`.
2. Add handler in `dap/client.py`.
3. Wire up to MCP tool in `server.py`.
4. Test with a real debug adapter.
