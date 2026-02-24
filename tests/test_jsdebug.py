"""Tests for the js-debug (JavaScript/TypeScript) adapter."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from unittest import mock

import pytest

from mcp_dap.adapters.base import get_adapter_aliases
from mcp_dap.adapters.base import get_registered_adapters
from mcp_dap.adapters.jsdebug import JsDebugAdapter
from mcp_dap.adapters.jsdebug import JsDebugAttachConfig
from mcp_dap.adapters.jsdebug import JsDebugLaunchConfig
from mcp_dap.dap.transport import SubprocessSocketTransport
from mcp_dap.exceptions import AdapterNotFoundError
from mcp_dap.exceptions import DAPConnectionError


class TestJsDebugRegistration:
    """Tests for adapter registration via @adapter decorator."""

    def test_registered_in_global_registry(self) -> None:
        """Test that jsdebug is registered in the adapter registry."""
        registry = get_registered_adapters()
        assert "jsdebug" in registry
        assert registry["jsdebug"] is JsDebugAdapter

    def test_aliases_registered(self) -> None:
        """Test that all aliases are registered."""
        aliases = get_adapter_aliases()
        for alias in ["node", "javascript", "typescript", "js", "ts"]:
            assert alias in aliases
            assert aliases[alias] == "jsdebug"

    def test_adapter_metadata(self) -> None:
        """Test adapter class metadata set by decorator."""
        assert JsDebugAdapter.name == "jsdebug"
        assert JsDebugAdapter.adapter_id == "pwa-node"
        assert ".js" in JsDebugAdapter.file_extensions
        assert ".ts" in JsDebugAdapter.file_extensions
        assert ".mjs" in JsDebugAdapter.file_extensions
        assert ".cjs" in JsDebugAdapter.file_extensions
        assert ".mts" in JsDebugAdapter.file_extensions
        assert ".cts" in JsDebugAdapter.file_extensions

    def test_adapter_description(self) -> None:
        """Test adapter description from class docstring."""
        adapter = JsDebugAdapter()
        desc = adapter.description
        assert "JavaScript" in desc or "Node.js" in desc


class TestJsDebugLaunchConfig:
    """Tests for JsDebugLaunchConfig Pydantic model."""

    def test_defaults(self) -> None:
        """Test default values for launch config."""
        config = JsDebugLaunchConfig()
        assert config.program is None
        assert config.args == []
        assert config.cwd is None
        assert config.env == {}
        assert config.stop_on_entry is False
        assert config.runtime_executable is None
        assert config.runtime_args == []
        assert config.source_maps is True
        assert config.out_files == []
        assert config.skip_files == []
        assert config.resolve_source_map_locations == []

    def test_with_values(self) -> None:
        """Test creating launch config with explicit values."""
        config = JsDebugLaunchConfig(
            program="/app/index.js",
            args=["--port", "3000"],
            cwd="/app",
            env={"NODE_ENV": "development"},
            stop_on_entry=True,
            runtime_executable="/usr/local/bin/node",
            runtime_args=["--loader", "ts-node/esm"],
            source_maps=True,
            out_files=["dist/**/*.js"],
            skip_files=["<node_internals>/**"],
        )
        assert config.program == "/app/index.js"
        assert config.args == ["--port", "3000"]
        assert config.runtime_executable == "/usr/local/bin/node"
        assert config.runtime_args == ["--loader", "ts-node/esm"]
        assert config.skip_files == ["<node_internals>/**"]

    def test_schema_has_expected_fields(self) -> None:
        """Test JSON schema includes all expected properties."""
        schema = JsDebugLaunchConfig.model_json_schema()
        props = schema["properties"]
        assert "program" in props
        assert "runtime_executable" in props
        assert "runtime_args" in props
        assert "source_maps" in props
        assert "out_files" in props
        assert "skip_files" in props
        assert "resolve_source_map_locations" in props


class TestJsDebugAttachConfig:
    """Tests for JsDebugAttachConfig Pydantic model."""

    def test_defaults(self) -> None:
        """Test default values for attach config."""
        config = JsDebugAttachConfig()
        assert config.host == "127.0.0.1"
        assert config.port == 9229
        assert config.source_maps is True
        assert config.skip_files == []
        assert config.restart is False

    def test_with_values(self) -> None:
        """Test creating attach config with explicit values."""
        config = JsDebugAttachConfig(
            host="192.168.1.10",
            port=9230,
            source_maps=False,
            skip_files=["<node_internals>/**"],
            restart=True,
        )
        assert config.host == "192.168.1.10"
        assert config.port == 9230
        assert config.source_maps is False
        assert config.restart is True


class TestJsDebugAdapter:
    """Tests for JsDebugAdapter class."""

    def test_launch_config_class(self) -> None:
        """Test that launch_config_class returns JsDebugLaunchConfig."""
        adapter = JsDebugAdapter()
        assert adapter.launch_config_class is JsDebugLaunchConfig

    def test_attach_config_class(self) -> None:
        """Test that attach_config_class returns JsDebugAttachConfig."""
        adapter = JsDebugAdapter()
        assert adapter.attach_config_class is JsDebugAttachConfig

    def test_from_config_default(self) -> None:
        """Test creating adapter with default config."""
        adapter = JsDebugAdapter.from_config({})
        assert isinstance(adapter, JsDebugAdapter)

    def test_from_config_with_paths(self) -> None:
        """Test creating adapter with explicit paths."""
        adapter = JsDebugAdapter.from_config({
            "jsdebug_path": "/custom/dapDebugServer.js",
            "node_path": "/custom/node",
        })
        assert isinstance(adapter, JsDebugAdapter)
        assert adapter._jsdebug_path == "/custom/dapDebugServer.js"
        assert adapter._node_path == "/custom/node"


class TestJsDebugFindNode:
    """Tests for Node.js binary discovery."""

    def test_find_node_explicit_path(self) -> None:
        """Test finding Node.js with explicit path."""
        with tempfile.NamedTemporaryFile(suffix="node", delete=False) as f:
            f.write(b"#!/bin/sh\n")
            node_path = f.name

        try:
            adapter = JsDebugAdapter(node_path=node_path)
            assert adapter.find_node() == node_path
        finally:
            Path(node_path).unlink()

    def test_find_node_explicit_path_not_found(self) -> None:
        """Test error when explicit Node.js path doesn't exist."""
        adapter = JsDebugAdapter(node_path="/nonexistent/node")
        with pytest.raises(AdapterNotFoundError, match=r"Node\.js not found at"):
            adapter.find_node()

    def test_find_node_on_path(self) -> None:
        """Test finding Node.js on PATH."""
        adapter = JsDebugAdapter()
        with mock.patch("shutil.which", return_value="/usr/bin/node"):
            assert adapter.find_node() == "/usr/bin/node"

    def test_find_node_not_found(self) -> None:
        """Test error when Node.js is not found anywhere."""
        adapter = JsDebugAdapter()
        with (
            mock.patch("shutil.which", return_value=None),
            pytest.raises(AdapterNotFoundError, match=r"Node\.js not found"),
        ):
            adapter.find_node()


class TestJsDebugFindJsdebug:
    """Tests for dapDebugServer.js discovery."""

    def test_find_jsdebug_explicit_path(self) -> None:
        """Test finding js-debug with explicit path."""
        with tempfile.NamedTemporaryFile(suffix=".js", delete=False) as f:
            f.write(b"// dapDebugServer.js\n")
            jsdebug_path = f.name

        try:
            adapter = JsDebugAdapter(jsdebug_path=jsdebug_path)
            assert adapter.find_jsdebug() == jsdebug_path
        finally:
            Path(jsdebug_path).unlink()

    def test_find_jsdebug_explicit_path_not_found(self) -> None:
        """Test error when explicit js-debug path doesn't exist."""
        adapter = JsDebugAdapter(jsdebug_path="/nonexistent/dapDebugServer.js")
        with pytest.raises(AdapterNotFoundError, match="js-debug not found at"):
            adapter.find_jsdebug()

    def test_find_jsdebug_not_found(self) -> None:
        """Test error with install instructions when js-debug not found."""
        adapter = JsDebugAdapter()

        fake_path = type("FakePath", (), {"exists": staticmethod(lambda: False)})()

        with (
            mock.patch("mcp_dap.adapters.jsdebug._JSDEBUG_SEARCH_PATHS", []),
            mock.patch("mcp_dap.adapters.jsdebug._VSCODE_EXTENSION_DIRS", []),
            mock.patch("mcp_dap.adapters.jsdebug._SYSTEM_VSCODE_JSDEBUG", fake_path),
            pytest.raises(AdapterNotFoundError, match=r"js-debug.*not found"),
        ):
            adapter.find_jsdebug()


class TestJsDebugLaunchArguments:
    """Tests for get_launch_arguments method."""

    def test_basic_launch_arguments(self) -> None:
        """Test basic launch arguments."""
        adapter = JsDebugAdapter()
        args = adapter.get_launch_arguments(
            program="/app/index.js",
        )

        assert args["type"] == "pwa-node"
        assert args["request"] == "launch"
        assert args["program"] == "/app/index.js"
        assert args["args"] == []
        assert args["stopOnEntry"] is False
        assert args["console"] == "internalConsole"
        assert args["sourceMaps"] is True

    def test_launch_arguments_with_all_options(self) -> None:
        """Test launch arguments with all options specified."""
        adapter = JsDebugAdapter()
        args = adapter.get_launch_arguments(
            program="/app/index.ts",
            args=["--port", "3000"],
            cwd="/app",
            env={"NODE_ENV": "production"},
            stop_on_entry=True,
            runtime_executable="/usr/local/bin/node",
            runtime_args=["--loader", "ts-node/esm"],
            source_maps=True,
            out_files=["dist/**/*.js"],
            skip_files=["<node_internals>/**"],
        )

        assert args["program"] == "/app/index.ts"
        assert args["args"] == ["--port", "3000"]
        assert args["cwd"] == "/app"
        assert args["env"] == {"NODE_ENV": "production"}
        assert args["stopOnEntry"] is True
        assert args["runtimeExecutable"] == "/usr/local/bin/node"
        assert args["runtimeArgs"] == ["--loader", "ts-node/esm"]
        assert args["sourceMaps"] is True
        assert args["outFiles"] == ["dist/**/*.js"]
        assert args["skipFiles"] == ["<node_internals>/**"]

    def test_launch_arguments_passthrough_kwargs(self) -> None:
        """Test that unknown kwargs are passed through."""
        adapter = JsDebugAdapter()
        args = adapter.get_launch_arguments(
            program="/app/index.js",
            timeout=60000,
        )
        assert args["timeout"] == 60000


class TestJsDebugAttachArguments:
    """Tests for get_attach_arguments method."""

    def test_basic_attach_arguments(self) -> None:
        """Test basic attach arguments."""
        adapter = JsDebugAdapter()
        args = adapter.get_attach_arguments(
            host="127.0.0.1",
            port=9229,
        )

        assert args["type"] == "pwa-node"
        assert args["request"] == "attach"
        assert args["address"] == "127.0.0.1"
        assert args["port"] == 9229
        assert args["sourceMaps"] is True

    def test_attach_arguments_with_options(self) -> None:
        """Test attach arguments with extra options."""
        adapter = JsDebugAdapter()
        args = adapter.get_attach_arguments(
            host="192.168.1.10",
            port=9230,
            skip_files=["<node_internals>/**"],
            restart=True,
        )

        assert args["address"] == "192.168.1.10"
        assert args["port"] == 9230
        assert args["skipFiles"] == ["<node_internals>/**"]
        assert args["restart"] is True


class TestJsDebugTransport:
    """Tests for transport creation."""

    def test_create_transport_returns_subprocess_socket(self) -> None:
        """Test that create_transport returns SubprocessSocketTransport."""
        adapter = JsDebugAdapter()

        with (
            mock.patch.object(adapter, "find_node", return_value="/usr/bin/node"),
            mock.patch.object(
                adapter, "find_jsdebug", return_value="/path/to/dapDebugServer.js"
            ),
        ):
            transport = adapter.create_transport()

        assert isinstance(transport, SubprocessSocketTransport)


class TestJsDebugGetInfo:
    """Tests for get_info method."""

    def test_info_structure(self) -> None:
        """Test that get_info returns expected structure."""
        adapter = JsDebugAdapter()
        info = adapter.get_info()

        assert info["name"] == "jsdebug"
        assert info["adapter_id"] == "pwa-node"
        assert "description" in info
        assert "file_extensions" in info
        assert "aliases" in info
        assert "launch_config" in info
        assert "attach_config" in info
        assert "node_path" in info

    def test_info_with_missing_jsdebug(self) -> None:
        """Test get_info when js-debug is not installed."""
        adapter = JsDebugAdapter()
        with mock.patch.object(adapter, "find_jsdebug", side_effect=AdapterNotFoundError("nope")):
            info = adapter.get_info()

        assert info["jsdebug_path"] is None
        assert "install_instructions" in info


class TestJsDebugInConfigSystem:
    """Tests for js-debug integration with the config system."""

    def test_jsdebug_in_default_registry(self) -> None:
        """Test that jsdebug appears in default adapter registry."""
        from mcp_dap.config import ServerConfig
        from mcp_dap.config import reset_config

        reset_config()
        config = ServerConfig()
        registry = config.build_adapter_registry()

        assert "jsdebug" in registry
        assert "node" in registry
        assert "javascript" in registry
        assert "typescript" in registry
        assert "js" in registry
        assert "ts" in registry
        reset_config()

    def test_jsdebug_can_be_disabled(self) -> None:
        """Test that jsdebug can be disabled via env var."""
        from mcp_dap.config import ServerConfig
        from mcp_dap.config import reset_config

        reset_config()
        with mock.patch.dict(
            os.environ, {"MCP_DAP_ADAPTERS__JSDEBUG__ENABLED": "false"}
        ):
            config = ServerConfig()
            registry = config.build_adapter_registry()

            assert "jsdebug" not in registry
            assert "node" not in registry
            assert "javascript" not in registry
        reset_config()


class TestSubprocessSocketTransport:
    """Tests for SubprocessSocketTransport (used by js-debug)."""

    def test_transport_init_defaults(self) -> None:
        """Test transport initialization with defaults."""
        transport = SubprocessSocketTransport(
            command=["node", "server.js"],
        )
        assert transport.port is None
        assert transport.is_connected is False

    def test_transport_init_with_port(self) -> None:
        """Test transport initialization with explicit port."""
        transport = SubprocessSocketTransport(
            command=["node", "server.js"],
            port=9999,
        )
        assert transport.port == 9999

    @pytest.mark.asyncio
    async def test_send_without_connect_raises(self) -> None:
        """Test that sending without connecting raises."""
        transport = SubprocessSocketTransport(command=["node", "server.js"])
        with pytest.raises(DAPConnectionError, match="not connected"):
            await transport.send({"type": "request"})

    @pytest.mark.asyncio
    async def test_receive_without_connect_raises(self) -> None:
        """Test that receiving without connecting raises."""
        transport = SubprocessSocketTransport(command=["node", "server.js"])
        with pytest.raises(DAPConnectionError, match="not connected"):
            await transport.receive()

    @pytest.mark.asyncio
    async def test_find_free_port(self) -> None:
        """Test that _find_free_port returns a valid port."""
        transport = SubprocessSocketTransport(command=["echo"])
        port = await transport._find_free_port()
        assert isinstance(port, int)
        assert 1024 <= port <= 65535
