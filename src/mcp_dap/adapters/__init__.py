"""Debug adapter configurations."""

from __future__ import annotations

from mcp_dap.adapters.base import AdapterConfig
from mcp_dap.adapters.codelldb import CodeLLDBAdapter
from mcp_dap.adapters.debugpy import DebugpyAdapter
from mcp_dap.adapters.godlv import DelveAdapter
from mcp_dap.adapters.javadebug import JavaDebugAdapter
from mcp_dap.adapters.jsdebug import JsDebugAdapter

__all__ = [
    "AdapterConfig",
    "CodeLLDBAdapter",
    "DebugpyAdapter",
    "DelveAdapter",
    "JavaDebugAdapter",
    "JsDebugAdapter",
]
