"""Tests for the Delve (Go) adapter."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from unittest import mock

import pytest

from mcp_dap.adapters.base import get_adapter_aliases
from mcp_dap.adapters.base import get_registered_adapters
from mcp_dap.adapters.godlv import DelveAdapter
from mcp_dap.adapters.godlv import DelveAttachConfig
from mcp_dap.adapters.godlv import DelveLaunchConfig
from mcp_dap.dap.transport import SubprocessSocketTransport
from mcp_dap.exceptions import AdapterNotFoundError
from mcp_dap.exceptions import MCPDAPError


class TestDelveRegistration:
    """Tests for adapter registration via @adapter decorator."""

    def test_registered_in_global_registry(self) -> None:
        """Test that godlv is registered in the adapter registry."""
        registry = get_registered_adapters()
        assert "godlv" in registry
        assert registry["godlv"] is DelveAdapter

    def test_aliases_registered(self) -> None:
        """Test that all aliases are registered."""
        aliases = get_adapter_aliases()
        for alias in ["go", "delve", "dlv"]:
            assert alias in aliases
            assert aliases[alias] == "godlv"

    def test_adapter_metadata(self) -> None:
        """Test adapter class metadata set by decorator."""
        assert DelveAdapter.name == "godlv"
        assert DelveAdapter.adapter_id == "go"
        assert ".go" in DelveAdapter.file_extensions

    def test_adapter_description(self) -> None:
        """Test adapter description from class docstring."""
        adapter = DelveAdapter()
        desc = adapter.description
        assert "Go" in desc or "Delve" in desc


class TestDelveLaunchConfig:
    """Tests for DelveLaunchConfig Pydantic model."""

    def test_defaults(self) -> None:
        """Test default values for launch config."""
        config = DelveLaunchConfig()
        assert config.program is None
        assert config.args == []
        assert config.cwd is None
        assert config.env == {}
        assert config.stop_on_entry is False
        assert config.mode == "debug"
        assert config.build_flags == ""
        assert config.dlv_flags == []
        assert config.substitue_path == []
        assert config.show_global_variables is False

    def test_with_values(self) -> None:
        """Test creating launch config with explicit values."""
        config = DelveLaunchConfig(
            program="/app/cmd/server",
            args=["--port", "8080"],
            cwd="/app",
            env={"GO_ENV": "development"},
            stop_on_entry=True,
            mode="debug",
            build_flags="-tags=integration -race",
        )
        assert config.program == "/app/cmd/server"
        assert config.args == ["--port", "8080"]
        assert config.mode == "debug"
        assert config.build_flags == "-tags=integration -race"

    def test_test_mode(self) -> None:
        """Test launch config for test mode."""
        config = DelveLaunchConfig(
            program="/app/pkg/handler",
            mode="test",
            build_flags="-run TestHandler",
        )
        assert config.mode == "test"

    def test_exec_mode(self) -> None:
        """Test launch config for exec mode."""
        config = DelveLaunchConfig(
            program="/app/bin/server",
            mode="exec",
        )
        assert config.mode == "exec"

    def test_schema_has_expected_fields(self) -> None:
        """Test JSON schema includes all expected properties."""
        schema = DelveLaunchConfig.model_json_schema()
        props = schema["properties"]
        assert "program" in props
        assert "mode" in props
        assert "build_flags" in props
        assert "dlv_flags" in props
        assert "show_global_variables" in props


class TestDelveAttachConfig:
    """Tests for DelveAttachConfig Pydantic model."""

    def test_defaults(self) -> None:
        """Test default values for attach config."""
        config = DelveAttachConfig()
        assert config.mode == "local"
        assert config.process_id is None
        assert config.host is None
        assert config.port is None

    def test_local_attach(self) -> None:
        """Test local attach configuration."""
        config = DelveAttachConfig(
            mode="local",
            process_id=12345,
        )
        assert config.mode == "local"
        assert config.process_id == 12345

    def test_remote_attach(self) -> None:
        """Test remote attach configuration."""
        config = DelveAttachConfig(
            mode="remote",
            host="192.168.1.10",
            port=2345,
        )
        assert config.mode == "remote"
        assert config.host == "192.168.1.10"
        assert config.port == 2345


class TestDelveAdapter:
    """Tests for DelveAdapter class."""

    def test_launch_config_class(self) -> None:
        """Test that launch_config_class returns DelveLaunchConfig."""
        adapter = DelveAdapter()
        assert adapter.launch_config_class is DelveLaunchConfig

    def test_attach_config_class(self) -> None:
        """Test that attach_config_class returns DelveAttachConfig."""
        adapter = DelveAdapter()
        assert adapter.attach_config_class is DelveAttachConfig

    def test_from_config_default(self) -> None:
        """Test creating adapter with default config."""
        adapter = DelveAdapter.from_config({})
        assert isinstance(adapter, DelveAdapter)

    def test_from_config_with_path(self) -> None:
        """Test creating adapter with explicit dlv path."""
        adapter = DelveAdapter.from_config({"dlv_path": "/custom/dlv"})
        assert isinstance(adapter, DelveAdapter)
        assert adapter._dlv_path == "/custom/dlv"


class TestDelveFindDlv:
    """Tests for dlv binary discovery."""

    def test_find_dlv_explicit_path(self) -> None:
        """Test finding dlv with explicit path."""
        with tempfile.NamedTemporaryFile(suffix="dlv", delete=False) as f:
            f.write(b"#!/bin/sh\n")
            dlv_path = f.name

        try:
            adapter = DelveAdapter(dlv_path=dlv_path)
            assert adapter.find_dlv() == dlv_path
        finally:
            Path(dlv_path).unlink()

    def test_find_dlv_explicit_path_not_found(self) -> None:
        """Test error when explicit dlv path doesn't exist."""
        adapter = DelveAdapter(dlv_path="/nonexistent/dlv")
        with pytest.raises(AdapterNotFoundError, match="Delve not found at"):
            adapter.find_dlv()

    def test_find_dlv_on_path(self) -> None:
        """Test finding dlv on PATH."""
        adapter = DelveAdapter()
        with (
            mock.patch.object(adapter, "_find_gobin", return_value=None),
            mock.patch("shutil.which", return_value="/usr/local/bin/dlv"),
        ):
            assert adapter.find_dlv() == "/usr/local/bin/dlv"

    def test_find_dlv_in_gobin(self) -> None:
        """Test finding dlv in GOBIN directory."""
        with tempfile.TemporaryDirectory() as gobin:
            dlv_path = Path(gobin) / "dlv"
            dlv_path.touch()

            adapter = DelveAdapter()
            with mock.patch.object(adapter, "_find_gobin", return_value=gobin):
                assert adapter.find_dlv() == str(dlv_path)

    def test_find_dlv_not_found(self) -> None:
        """Test error when dlv is not found anywhere."""
        adapter = DelveAdapter()
        with (
            mock.patch.object(adapter, "_find_gobin", return_value=None),
            mock.patch("shutil.which", return_value=None),
            pytest.raises(AdapterNotFoundError, match=r"Delve \(dlv\) not found"),
        ):
            adapter.find_dlv()


class TestDelveGobin:
    """Tests for GOBIN/GOPATH discovery."""

    def test_find_gobin_from_env(self) -> None:
        """Test finding GOBIN from environment variable."""
        with (
            tempfile.TemporaryDirectory() as gobin,
            mock.patch.dict(os.environ, {"GOBIN": gobin}, clear=False),
        ):
            result = DelveAdapter._find_gobin()
            assert result == gobin

    def test_find_gobin_from_gopath(self) -> None:
        """Test finding Go bin from GOPATH."""
        with tempfile.TemporaryDirectory() as gopath:
            bin_dir = Path(gopath) / "bin"
            bin_dir.mkdir()
            with mock.patch.dict(
                os.environ, {"GOPATH": gopath}, clear=False
            ):
                # Clear GOBIN to test GOPATH fallback
                env = os.environ.copy()
                env.pop("GOBIN", None)
                env["GOPATH"] = gopath
                with mock.patch.dict(os.environ, env, clear=True):
                    result = DelveAdapter._find_gobin()
                    assert result == str(bin_dir)

    def test_find_gobin_not_found(self) -> None:
        """Test when Go bin directory is not found."""
        with (
            mock.patch.dict(os.environ, {}, clear=True),
            mock.patch("pathlib.Path.home", return_value=Path("/nonexistent")),
        ):
            result = DelveAdapter._find_gobin()
            assert result is None


class TestDelveLaunchArguments:
    """Tests for get_launch_arguments method."""

    def test_basic_debug_launch(self) -> None:
        """Test basic debug mode launch arguments."""
        adapter = DelveAdapter()
        args = adapter.get_launch_arguments(
            program="/app/cmd/server",
        )

        assert args["request"] == "launch"
        assert args["mode"] == "debug"
        assert args["program"] == "/app/cmd/server"
        assert args["args"] == []
        assert args["stopOnEntry"] is False

    def test_test_mode_launch(self) -> None:
        """Test test mode launch arguments."""
        adapter = DelveAdapter()
        args = adapter.get_launch_arguments(
            program="/app/pkg/handler",
            mode="test",
            build_flags="-run TestHandler",
        )

        assert args["mode"] == "test"
        assert args["buildFlags"] == "-run TestHandler"

    def test_exec_mode_launch(self) -> None:
        """Test exec mode launch arguments."""
        adapter = DelveAdapter()
        args = adapter.get_launch_arguments(
            program="/app/bin/server",
            args=["--port", "8080"],
            cwd="/app",
            env={"GO_ENV": "prod"},
            stop_on_entry=True,
            mode="exec",
        )

        assert args["mode"] == "exec"
        assert args["program"] == "/app/bin/server"
        assert args["args"] == ["--port", "8080"]
        assert args["cwd"] == "/app"
        assert args["env"] == {"GO_ENV": "prod"}
        assert args["stopOnEntry"] is True

    def test_launch_with_substitute_path(self) -> None:
        """Test launch with source path substitution."""
        adapter = DelveAdapter()
        sub_path = [{"from": "/build", "to": "/local"}]
        args = adapter.get_launch_arguments(
            program="/app",
            substitute_path=sub_path,
        )
        assert args["substitutePath"] == sub_path

    def test_launch_passthrough_kwargs(self) -> None:
        """Test that unknown kwargs are passed through."""
        adapter = DelveAdapter()
        args = adapter.get_launch_arguments(
            program="/app",
            stackTraceDepth=50,
        )
        assert args["stackTraceDepth"] == 50


class TestDelveAttachArguments:
    """Tests for get_attach_arguments method."""

    def test_local_attach_by_pid(self) -> None:
        """Test local attach with process ID."""
        adapter = DelveAdapter()
        args = adapter.get_attach_arguments(
            host="127.0.0.1",
            port=0,
            mode="local",
            process_id=12345,
        )

        assert args["request"] == "attach"
        assert args["mode"] == "local"
        assert args["processId"] == 12345

    def test_local_attach_by_pid_kwarg(self) -> None:
        """Test local attach using 'pid' kwarg (alias for process_id)."""
        adapter = DelveAdapter()
        args = adapter.get_attach_arguments(
            host="127.0.0.1",
            port=0,
            mode="local",
            pid=12345,
        )
        assert args["processId"] == 12345

    def test_local_attach_missing_pid_raises(self) -> None:
        """Test error when local attach is missing PID."""
        adapter = DelveAdapter()
        with pytest.raises(MCPDAPError, match="process_id"):
            adapter.get_attach_arguments(
                host="127.0.0.1",
                port=0,
                mode="local",
            )

    def test_remote_attach(self) -> None:
        """Test remote attach to headless Delve."""
        adapter = DelveAdapter()
        args = adapter.get_attach_arguments(
            host="192.168.1.10",
            port=2345,
            mode="remote",
        )

        assert args["request"] == "attach"
        assert args["mode"] == "remote"
        assert args["host"] == "192.168.1.10"
        assert args["port"] == 2345


class TestDelveTransport:
    """Tests for transport creation."""

    def test_create_transport_returns_subprocess_socket(self) -> None:
        """Test that create_transport returns SubprocessSocketTransport."""
        adapter = DelveAdapter()

        with mock.patch.object(adapter, "find_dlv", return_value="/usr/local/bin/dlv"):
            transport = adapter.create_transport()

        assert isinstance(transport, SubprocessSocketTransport)


class TestDelveGetInfo:
    """Tests for get_info method."""

    def test_info_structure(self) -> None:
        """Test that get_info returns expected structure."""
        adapter = DelveAdapter()
        info = adapter.get_info()

        assert info["name"] == "godlv"
        assert info["adapter_id"] == "go"
        assert "description" in info
        assert "file_extensions" in info
        assert "aliases" in info
        assert "launch_config" in info
        assert "attach_config" in info
        assert "supported_modes" in info
        assert info["supported_modes"]["launch"] == ["debug", "test", "exec"]
        assert info["supported_modes"]["attach"] == ["local", "remote"]

    def test_info_with_missing_dlv(self) -> None:
        """Test get_info when dlv is not installed."""
        adapter = DelveAdapter()
        with mock.patch.object(adapter, "find_dlv", side_effect=AdapterNotFoundError("nope")):
            info = adapter.get_info()

        assert info["dlv_path"] is None
        assert "install_instructions" in info


class TestDelveInConfigSystem:
    """Tests for Delve integration with the config system."""

    def test_godlv_in_default_registry(self) -> None:
        """Test that godlv appears in default adapter registry."""
        from mcp_dap.config import ServerConfig
        from mcp_dap.config import reset_config

        reset_config()
        config = ServerConfig()
        registry = config.build_adapter_registry()

        assert "godlv" in registry
        assert "go" in registry
        assert "delve" in registry
        assert "dlv" in registry
        reset_config()

    def test_godlv_can_be_disabled(self) -> None:
        """Test that godlv can be disabled via env var."""
        from mcp_dap.config import ServerConfig
        from mcp_dap.config import reset_config

        reset_config()
        with mock.patch.dict(
            os.environ, {"MCP_DAP_ADAPTERS__GODLV__ENABLED": "false"}
        ):
            config = ServerConfig()
            registry = config.build_adapter_registry()

            assert "godlv" not in registry
            assert "go" not in registry
            assert "delve" not in registry
        reset_config()
