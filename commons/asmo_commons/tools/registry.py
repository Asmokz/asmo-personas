"""Tool registry — manages LLM-callable tools for a bot."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Optional

import structlog

logger = structlog.get_logger()


@dataclass
class ToolDefinition:
    """A single tool that can be called by the LLM."""

    name: str
    description: str
    parameters: dict  # JSON Schema
    handler: Callable  # async callable

    def to_ollama_format(self) -> dict:
        """Return the Ollama/OpenAI-compatible tool descriptor."""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }


class ToolRegistry:
    """Registry of tools available to a bot instance."""

    def __init__(self) -> None:
        self._tools: dict[str, ToolDefinition] = {}

    # ------------------------------------------------------------------
    # Registration
    # ------------------------------------------------------------------

    def register(
        self,
        name: str,
        description: str,
        parameters: Optional[dict] = None,
    ) -> Callable:
        """Decorator that registers an async function as a named tool.

        Example::

            registry = ToolRegistry()

            @registry.register("get_disk_usage", "Return df -h output")
            async def get_disk_usage() -> str:
                ...
        """
        if parameters is None:
            parameters = {"type": "object", "properties": {}, "required": []}

        def decorator(func: Callable) -> Callable:
            self._tools[name] = ToolDefinition(
                name=name,
                description=description,
                parameters=parameters,
                handler=func,
            )
            logger.debug("tool_registered", name=name)
            return func

        return decorator

    def add(self, definition: ToolDefinition) -> None:
        """Directly add a ToolDefinition."""
        self._tools[definition.name] = definition
        logger.debug("tool_added", name=definition.name)

    # ------------------------------------------------------------------
    # Querying
    # ------------------------------------------------------------------

    def get(self, name: str) -> Optional[ToolDefinition]:
        return self._tools.get(name)

    def names(self) -> list[str]:
        return list(self._tools.keys())

    def to_ollama_tools(self) -> list[dict]:
        """Return all tools in Ollama-compatible format."""
        return [t.to_ollama_format() for t in self._tools.values()]

    # ------------------------------------------------------------------
    # Execution
    # ------------------------------------------------------------------

    async def execute(self, name: str, arguments: dict) -> str:
        """Call a registered tool and return its string result.

        Never raises — returns an error string on failure so the LLM can
        reason about what went wrong.
        """
        tool = self.get(name)
        if tool is None:
            logger.warning("tool_not_found", name=name)
            return f"[Error] Tool '{name}' is not registered."

        try:
            result = await tool.handler(**arguments)
            logger.info("tool_executed", name=name, success=True)
            return str(result)
        except TypeError as exc:
            logger.error("tool_bad_args", name=name, error=str(exc))
            return f"[Error] Bad arguments for tool '{name}': {exc}"
        except Exception as exc:
            logger.error("tool_execution_failed", name=name, error=str(exc))
            return f"[Error] Tool '{name}' failed: {exc}"
