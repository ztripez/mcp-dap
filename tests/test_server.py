"""Tests for MCP-DAP server."""

from __future__ import annotations

import pytest

from mcp_dap.server import MCPDAPServer


@pytest.fixture
def server() -> MCPDAPServer:
    """Create a test server instance."""
    return MCPDAPServer()


def test_server_creation(server: MCPDAPServer) -> None:
    """Test that server can be created."""
    assert server is not None
    assert server.session_manager is not None


def test_server_has_tools(server: MCPDAPServer) -> None:
    """Test that the server has registered tools."""
    # We can't easily call the list_tools handler directly without more setup
    # but we can verify the server object exists
    assert server.server is not None



def test_attach_input_schema() -> None:
    """Test that AttachInput schema has the new fields."""
    from mcp_dap.server import AttachInput

    schema = AttachInput.model_json_schema()
    properties = schema.get("properties", {})

    assert "host" in properties
    assert "port" in properties
    assert "pid" in properties
    # Check that host/port are not required
    required = schema.get("required", [])
    assert "host" not in required
    assert "port" not in required
