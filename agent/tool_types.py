from __future__ import annotations

from typing import Any, Literal, NotRequired, TypeAlias, TypedDict

JsonValue: TypeAlias = Any
JsonObject: TypeAlias = dict[str, Any]
ToolCallSource: TypeAlias = Literal["model"]


class ToolCallRecord(TypedDict):
    name: str
    arguments: JsonObject
    result: JsonObject
    source: NotRequired[ToolCallSource]
