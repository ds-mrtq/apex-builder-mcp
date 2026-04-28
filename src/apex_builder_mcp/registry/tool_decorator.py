# src/apex_builder_mcp/registry/tool_decorator.py
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, TypeVar

from apex_builder_mcp.registry.categories import Category

F = TypeVar("F", bound=Callable[..., Any])


@dataclass(frozen=True)
class RegisteredTool:
    name: str
    category: Category
    always_loaded: bool
    func: Callable[..., Any]


_REGISTERED_TOOLS: list[RegisteredTool] = []


def apex_tool(*, name: str, category: Category) -> Callable[[F], F]:
    def decorator(func: F) -> F:
        _REGISTERED_TOOLS.append(
            RegisteredTool(
                name=name,
                category=category,
                always_loaded=category.always_loaded,
                func=func,
            )
        )
        return func

    return decorator


def get_registered_tools() -> list[RegisteredTool]:
    return list(_REGISTERED_TOOLS)


def clear_registry_for_tests() -> None:
    _REGISTERED_TOOLS.clear()
