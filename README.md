# mcp-dap

MCP-DAP bridge for enabling code agents to debug processes via the Debug Adapter Protocol (DAP).

## Overview

This package provides an MCP (Model Context Protocol) server that exposes debugging capabilities through DAP. It allows AI coding agents to:

- Launch and attach to debug sessions
- Set breakpoints and step through code
- Inspect variables and evaluate expressions
- Control execution flow (continue, step over, step into, step out)

## Installation

```bash
pip install mcp-dap
```

## Run with uvx

Run directly from this repo:

```bash
uvx --from . mcp-dap
```

Run directly from GitHub:

```bash
uvx --from git+https://github.com/ztripez/mcp-dap mcp-dap
```

For MCP client config, point the server command at `uvx`:

```json
{
  "mcpServers": {
    "dap": {
      "command": "uvx",
      "args": ["--from", "git+https://github.com/ztripez/mcp-dap", "mcp-dap"]
    }
  }
}
```

## Debug adapters

`mcp-dap` is the MCP bridge; language DAP servers are separate runtime tools.

- Python (`debugpy`): included as a Python dependency.
- Rust/C/C++ (`codelldb`): install CodeLLDB (`vadimcn.vscode-lldb`) or `codelldb` on PATH.
- JavaScript/TypeScript (`jsdebug`): install Node.js and `js-debug-dap` (or have VS Code js-debug).
- Java (`javadebug`): install JDK + VS Code Java Debug extension (`vscjava.vscode-java-debug`).
- Go (`godlv`): install Delve (`go install github.com/go-delve/delve/cmd/dlv@latest`).

You can configure adapter paths with environment variables or `mcp-dap.toml`.

Example:

```toml
[adapters.codelldb]
enabled = true
codelldb_path = "/path/to/codelldb"

[adapters.jsdebug]
enabled = true
node_path = "/usr/bin/node"
jsdebug_path = "/home/user/.local/share/mcp-dap/js-debug/src/dapDebugServer.js"
```

## Development

```bash
# Install with dev dependencies
pip install -e ".[dev]"

# Run tests
pytest

# Run linting
ruff check .
ruff format --check .

# Run type checking
mypy src
```

## Usage

Configure in your MCP client:

```json
{
  "mcpServers": {
    "dap": {
      "command": "mcp-dap"
    }
  }
}
```

## License

MIT
