"""Tests for the Java debug adapter."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from unittest import mock

import pytest

from mcp_dap.adapters.base import get_adapter_aliases
from mcp_dap.adapters.base import get_registered_adapters
from mcp_dap.adapters.javadebug import JavaDebugAdapter
from mcp_dap.adapters.javadebug import JavaDebugAttachConfig
from mcp_dap.adapters.javadebug import JavaDebugLaunchConfig
from mcp_dap.dap.transport import StdioTransport
from mcp_dap.exceptions import AdapterNotFoundError


class TestJavaDebugRegistration:
    """Tests for adapter registration via @adapter decorator."""

    def test_registered_in_global_registry(self) -> None:
        """Test that javadebug is registered in the adapter registry."""
        registry = get_registered_adapters()
        assert "javadebug" in registry
        assert registry["javadebug"] is JavaDebugAdapter

    def test_aliases_registered(self) -> None:
        """Test that all aliases are registered."""
        aliases = get_adapter_aliases()
        for alias in ["java", "jvm"]:
            assert alias in aliases
            assert aliases[alias] == "javadebug"

    def test_adapter_metadata(self) -> None:
        """Test adapter class metadata set by decorator."""
        assert JavaDebugAdapter.name == "javadebug"
        assert JavaDebugAdapter.adapter_id == "java"
        assert ".java" in JavaDebugAdapter.file_extensions

    def test_adapter_description(self) -> None:
        """Test adapter description from class docstring."""
        adapter = JavaDebugAdapter()
        desc = adapter.description
        assert "Java" in desc


class TestJavaDebugLaunchConfig:
    """Tests for JavaDebugLaunchConfig Pydantic model."""

    def test_defaults(self) -> None:
        """Test default values for launch config."""
        config = JavaDebugLaunchConfig()
        assert config.program is None
        assert config.args == []
        assert config.cwd is None
        assert config.env == {}
        assert config.stop_on_entry is False
        assert config.main_class is None
        assert config.class_paths == []
        assert config.module_paths == []
        assert config.vm_args == ""
        assert config.project_name is None
        assert config.encoding == "UTF-8"

    def test_with_values(self) -> None:
        """Test creating launch config with explicit values."""
        config = JavaDebugLaunchConfig(
            program="/app/src/Main.java",
            args=["--port", "8080"],
            cwd="/app",
            main_class="com.example.Main",
            class_paths=["target/classes", "lib/*.jar"],
            vm_args="-Xmx512m -ea",
            encoding="UTF-8",
        )
        assert config.main_class == "com.example.Main"
        assert config.class_paths == ["target/classes", "lib/*.jar"]
        assert config.vm_args == "-Xmx512m -ea"

    def test_schema_has_expected_fields(self) -> None:
        """Test JSON schema includes all expected properties."""
        schema = JavaDebugLaunchConfig.model_json_schema()
        props = schema["properties"]
        assert "main_class" in props
        assert "class_paths" in props
        assert "module_paths" in props
        assert "vm_args" in props
        assert "encoding" in props


class TestJavaDebugAttachConfig:
    """Tests for JavaDebugAttachConfig Pydantic model."""

    def test_defaults(self) -> None:
        """Test default values for attach config."""
        config = JavaDebugAttachConfig()
        assert config.host == "127.0.0.1"
        assert config.port == 5005
        assert config.project_name is None

    def test_with_values(self) -> None:
        """Test creating attach config with explicit values."""
        config = JavaDebugAttachConfig(
            host="192.168.1.10",
            port=5006,
            project_name="my-project",
        )
        assert config.host == "192.168.1.10"
        assert config.port == 5006
        assert config.project_name == "my-project"


class TestJavaDebugAdapter:
    """Tests for JavaDebugAdapter class."""

    def test_launch_config_class(self) -> None:
        """Test that launch_config_class returns JavaDebugLaunchConfig."""
        adapter = JavaDebugAdapter()
        assert adapter.launch_config_class is JavaDebugLaunchConfig

    def test_attach_config_class(self) -> None:
        """Test that attach_config_class returns JavaDebugAttachConfig."""
        adapter = JavaDebugAdapter()
        assert adapter.attach_config_class is JavaDebugAttachConfig

    def test_from_config_default(self) -> None:
        """Test creating adapter with default config."""
        adapter = JavaDebugAdapter.from_config({})
        assert isinstance(adapter, JavaDebugAdapter)

    def test_from_config_with_paths(self) -> None:
        """Test creating adapter with explicit paths."""
        adapter = JavaDebugAdapter.from_config({
            "java_home": "/custom/jdk",
            "java_debug_jar_dir": "/custom/jars",
        })
        assert isinstance(adapter, JavaDebugAdapter)
        assert adapter._java_home == "/custom/jdk"
        assert adapter._java_debug_jar_dir == "/custom/jars"


class TestJavaDebugFindJava:
    """Tests for Java binary discovery."""

    def test_find_java_explicit_path(self) -> None:
        """Test finding Java with explicit java_home."""
        with tempfile.TemporaryDirectory() as java_home:
            bin_dir = Path(java_home) / "bin"
            bin_dir.mkdir()
            java_bin = bin_dir / "java"
            java_bin.touch()

            adapter = JavaDebugAdapter(java_home=java_home)
            assert adapter.find_java() == str(java_bin)

    def test_find_java_explicit_path_not_found(self) -> None:
        """Test error when explicit java_home doesn't have java binary."""
        adapter = JavaDebugAdapter(java_home="/nonexistent/jdk")
        with pytest.raises(AdapterNotFoundError, match="Java not found at"):
            adapter.find_java()

    def test_find_java_from_java_home_env(self) -> None:
        """Test finding Java from JAVA_HOME environment variable."""
        with tempfile.TemporaryDirectory() as java_home:
            bin_dir = Path(java_home) / "bin"
            bin_dir.mkdir()
            java_bin = bin_dir / "java"
            java_bin.touch()

            adapter = JavaDebugAdapter()
            with mock.patch.dict(os.environ, {"JAVA_HOME": java_home}):
                assert adapter.find_java() == str(java_bin)

    def test_find_java_from_path(self) -> None:
        """Test finding Java from PATH."""
        adapter = JavaDebugAdapter()
        with (
            mock.patch.dict(os.environ, {}, clear=True),
            mock.patch("shutil.which", return_value="/usr/bin/java"),
        ):
            assert adapter.find_java() == "/usr/bin/java"

    def test_find_java_not_found(self) -> None:
        """Test error when Java is not found anywhere."""
        adapter = JavaDebugAdapter()
        with (
            mock.patch.dict(os.environ, {}, clear=True),
            mock.patch("shutil.which", return_value=None),
            pytest.raises(AdapterNotFoundError, match=r"Java \(JDK\) not found"),
        ):
            adapter.find_java()


class TestJavaDebugFindJars:
    """Tests for java-debug JAR discovery."""

    def test_find_jars_explicit_directory(self) -> None:
        """Test finding JARs from explicit directory."""
        with tempfile.TemporaryDirectory() as jar_dir:
            adapter = JavaDebugAdapter(java_debug_jar_dir=jar_dir)
            result = adapter.find_java_debug_jars()
            assert result == Path(jar_dir)

    def test_find_jars_explicit_not_found(self) -> None:
        """Test error when explicit JAR dir doesn't exist."""
        adapter = JavaDebugAdapter(java_debug_jar_dir="/nonexistent/jars")
        with pytest.raises(AdapterNotFoundError, match="Java debug JARs not found"):
            adapter.find_java_debug_jars()

    def test_find_jars_from_cache(self) -> None:
        """Test finding JARs from cached extraction."""
        with tempfile.TemporaryDirectory() as tmp:
            cache_dir = Path(tmp) / ".cache" / "mcp-dap" / "java-debug"
            cache_dir.mkdir(parents=True)

            # Create required JARs
            for name in [
                "com.microsoft.java.debug.core-0.53.2.jar",
                "rxjava-2.2.21.jar",
                "reactive-streams-1.0.4.jar",
                "commons-io-2.19.0.jar",
                "gson-2.9.1.jar",
            ]:
                (cache_dir / name).touch()

            adapter = JavaDebugAdapter()
            with mock.patch("pathlib.Path.home", return_value=Path(tmp)):
                result = adapter.find_java_debug_jars()
                assert result == cache_dir


class TestJavaDebugInferMainClass:
    """Tests for main class inference from source files."""

    def test_infer_from_package_declaration(self) -> None:
        """Test inferring main class from package declaration."""
        with tempfile.TemporaryDirectory() as tmpdir:
            java_file = Path(tmpdir) / "Main.java"
            java_file.write_text("package com.example;\n\npublic class Main {\n}\n")

            result = JavaDebugAdapter._infer_main_class(str(java_file))
            assert result == "com.example.Main"

    def test_infer_without_package(self) -> None:
        """Test inferring main class without package declaration."""
        with tempfile.TemporaryDirectory() as tmpdir:
            java_file = Path(tmpdir) / "Hello.java"
            java_file.write_text("public class Hello {\n}\n")

            result = JavaDebugAdapter._infer_main_class(str(java_file))
            assert result == "Hello"

    def test_infer_nonexistent_file(self) -> None:
        """Test inference with nonexistent file falls back to stem."""
        result = JavaDebugAdapter._infer_main_class("/nonexistent/MyApp.java")
        assert result == "MyApp"


class TestJavaDebugLaunchArguments:
    """Tests for get_launch_arguments method."""

    def test_basic_launch_arguments(self) -> None:
        """Test basic launch arguments with main class."""
        adapter = JavaDebugAdapter()
        args = adapter.get_launch_arguments(
            program="/app/src/Main.java",
            main_class="com.example.Main",
        )

        assert args["type"] == "java"
        assert args["request"] == "launch"
        assert args["mainClass"] == "com.example.Main"
        assert args["stopOnEntry"] is False

    def test_launch_with_classpath(self) -> None:
        """Test launch with explicit classpath."""
        adapter = JavaDebugAdapter()
        args = adapter.get_launch_arguments(
            program="/app/src/Main.java",
            main_class="com.example.Main",
            class_paths=["target/classes", "lib/dep.jar"],
            vm_args="-Xmx1g",
        )

        assert args["classPaths"] == ["target/classes", "lib/dep.jar"]
        assert args["vmArgs"] == "-Xmx1g"

    def test_launch_infers_main_class(self) -> None:
        """Test that launch infers main class from program path."""
        with tempfile.TemporaryDirectory() as tmpdir:
            java_file = Path(tmpdir) / "App.java"
            java_file.write_text("package org.test;\npublic class App {}\n")

            adapter = JavaDebugAdapter()
            args = adapter.get_launch_arguments(program=str(java_file))
            assert args["mainClass"] == "org.test.App"

    def test_launch_default_classpath(self) -> None:
        """Test that launch uses program parent as default classpath."""
        adapter = JavaDebugAdapter()
        args = adapter.get_launch_arguments(
            program="/app/src/Main.java",
            main_class="Main",
        )
        assert args["classPaths"] == ["/app/src"]

    def test_launch_passthrough_kwargs(self) -> None:
        """Test that unknown kwargs are passed through."""
        adapter = JavaDebugAdapter()
        args = adapter.get_launch_arguments(
            program="/app/Main.java",
            main_class="Main",
            shortenCommandLine="jarmanifest",
        )
        assert args["shortenCommandLine"] == "jarmanifest"


class TestJavaDebugAttachArguments:
    """Tests for get_attach_arguments method."""

    def test_basic_attach_arguments(self) -> None:
        """Test basic attach arguments."""
        adapter = JavaDebugAdapter()
        args = adapter.get_attach_arguments(
            host="127.0.0.1",
            port=5005,
        )

        assert args["type"] == "java"
        assert args["request"] == "attach"
        assert args["hostName"] == "127.0.0.1"
        assert args["port"] == 5005

    def test_attach_with_project_name(self) -> None:
        """Test attach with project name."""
        adapter = JavaDebugAdapter()
        args = adapter.get_attach_arguments(
            host="192.168.1.10",
            port=5006,
            project_name="my-project",
        )
        assert args["hostName"] == "192.168.1.10"
        assert args["projectName"] == "my-project"


class TestJavaDebugTransport:
    """Tests for transport creation."""

    def test_create_transport_returns_stdio(self) -> None:
        """Test that create_transport returns StdioTransport."""
        adapter = JavaDebugAdapter()

        with (
            mock.patch.object(adapter, "find_java", return_value="/usr/bin/java"),
            mock.patch.object(adapter, "_build_classpath", return_value="/tmp/cp"),
        ):
            transport = adapter.create_transport()

        assert isinstance(transport, StdioTransport)


class TestJavaDebugGetInfo:
    """Tests for get_info method."""

    def test_info_structure(self) -> None:
        """Test that get_info returns expected structure."""
        adapter = JavaDebugAdapter()
        with mock.patch.object(
            adapter, "find_java_debug_jars", side_effect=AdapterNotFoundError("nope")
        ):
            info = adapter.get_info()

        assert info["name"] == "javadebug"
        assert info["adapter_id"] == "java"
        assert "description" in info
        assert "launch_config" in info
        assert "attach_config" in info

    def test_info_with_missing_jars(self) -> None:
        """Test get_info when JARs are not installed."""
        adapter = JavaDebugAdapter()
        with mock.patch.object(
            adapter, "find_java_debug_jars", side_effect=AdapterNotFoundError("nope")
        ):
            info = adapter.get_info()
        assert info["jar_dir"] is None
        assert "install_instructions" in info


class TestJavaDebugInConfigSystem:
    """Tests for Java debug integration with the config system."""

    def test_javadebug_in_default_registry(self) -> None:
        """Test that javadebug appears in default adapter registry."""
        from mcp_dap.config import ServerConfig
        from mcp_dap.config import reset_config

        reset_config()
        config = ServerConfig()
        registry = config.build_adapter_registry()

        assert "javadebug" in registry
        assert "java" in registry
        assert "jvm" in registry
        reset_config()

    def test_javadebug_can_be_disabled(self) -> None:
        """Test that javadebug can be disabled via env var."""
        from mcp_dap.config import ServerConfig
        from mcp_dap.config import reset_config

        reset_config()
        with mock.patch.dict(
            os.environ, {"MCP_DAP_ADAPTERS__JAVADEBUG__ENABLED": "false"}
        ):
            config = ServerConfig()
            registry = config.build_adapter_registry()

            assert "javadebug" not in registry
            assert "java" not in registry
            assert "jvm" not in registry
        reset_config()
