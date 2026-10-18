"""Provider-independent MCP registry facade over the FINORA service layer."""
from modules.finora_ai.services import TOOLS, ToolSpec, list_tools, execute_tool

__all__ = ["TOOLS", "ToolSpec", "list_tools", "execute_tool"]
