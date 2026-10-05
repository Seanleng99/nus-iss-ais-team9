"""Request-local output contracts, without changing fixture gateway interfaces."""

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from copy import deepcopy

from pydantic import BaseModel

_format: ContextVar[dict | None] = ContextVar("model_output_format", default=None)


def _close_schema(schema: dict) -> dict:
    result = deepcopy(schema)

    def visit(node):
        if isinstance(node, list):
            for item in node:
                visit(item)
        elif isinstance(node, dict):
            node.pop("default", None)
            if "const" in node:
                node["enum"] = [node.pop("const")]
            if "oneOf" in node:
                node["anyOf"] = node.pop("oneOf")
                node.pop("discriminator", None)
            if node.get("type") == "object":
                # An open workspace-operation map cannot be made closed without
                # deleting real fields. Keep its original non-strict schema.
                if "properties" not in node or isinstance(node.get("additionalProperties"), dict):
                    raise ValueError("Open object contract")
                node["additionalProperties"] = False
                node["required"] = list(node["properties"])
            for value in node.values():
                visit(value)

    visit(result)
    return result


@contextmanager
def structured_contract(response_type: type[BaseModel]) -> Iterator[None]:
    schema = response_type.model_json_schema()
    try:
        closed = _close_schema(schema)
        strict = True
    except ValueError:
        closed, strict = schema, False
    token = _format.set({
        "type": "json_schema", "name": response_type.__name__,
        "schema": closed, "strict": strict,
    })
    try:
        yield
    finally:
        _format.reset(token)


def output_format() -> dict:
    return deepcopy(_format.get() or {"type": "json_object"})
