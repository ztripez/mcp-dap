"""MCP-DAP bridge for enabling code agents to debug processes via DAP."""

from __future__ import annotations

from mcp_dap.config import ServerConfig
from mcp_dap.config import get_config
from mcp_dap.config import load_config
from mcp_dap.exceptions import DAPConnectionError
from mcp_dap.exceptions import DAPError
from mcp_dap.exceptions import DAPProtocolError
from mcp_dap.exceptions import DAPTimeoutError
from mcp_dap.exceptions import MCPDAPError
from mcp_dap.exceptions import SessionError
from mcp_dap.exceptions import SessionNotFoundError
from mcp_dap.session import DebugSession
from mcp_dap.session import SessionManager

__version__ = "0.1.0"

__all__ = [
    "DAPConnectionError",
    "DAPError",
    "DAPProtocolError",
    "DAPTimeoutError",
    "DebugSession",
    "MCPDAPError",
    "ServerConfig",
    "SessionError",
    "SessionManager",
    "SessionNotFoundError",
    "get_config",
    "load_config",
]
