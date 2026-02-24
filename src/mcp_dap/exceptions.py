"""Custom exceptions for mcp-dap."""

from __future__ import annotations


class MCPDAPError(Exception):
    """Base exception for all mcp-dap errors."""


class DAPError(MCPDAPError):
    """Error from DAP protocol communication."""


class DAPConnectionError(DAPError):
    """Failed to connect to debug adapter."""


class DAPTimeoutError(DAPError):
    """Timeout waiting for DAP response."""


class DAPProtocolError(DAPError):
    """Invalid DAP message or protocol violation."""


class SessionError(MCPDAPError):
    """Error related to debug session management."""


class SessionNotFoundError(SessionError):
    """Debug session not found."""


class SessionAlreadyExistsError(SessionError):
    """Debug session already exists with this ID."""


class AdapterError(MCPDAPError):
    """Error related to debug adapter configuration or launch."""


class AdapterNotFoundError(AdapterError):
    """Debug adapter not found or not configured."""


class AdapterLaunchError(AdapterError):
    """Failed to launch debug adapter process."""
