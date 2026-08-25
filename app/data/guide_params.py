"""
Parameter documentation generated from the running request models.

The remediation spec's S14 motivating failure was that "/guide documented a
parameter set the API no longer accepted" — a caller following the guide got a
422, or worse, silently empty windows. Hand-maintained prose alongside evolving
Pydantic models drifts, and it had: the guide still described
`local_start_time_of_day_hours`, a boolean `augmented_crew`, a string
`extension`, and `acclimatisation: "not_acclimatised"`, none of which the API
had accepted for some time.

Prose that genuinely cannot be generated — `when_to_use`, `common_mistakes` —
stays hand-written in guide.py, with a contract test asserting that every
parameter it names exists on the corresponding model.
"""

from __future__ import annotations

import typing
from typing import Any, Literal, Optional, Union

from pydantic import BaseModel
from pydantic_core import PydanticUndefined


def _is_model(annotation: Any) -> bool:
    return isinstance(annotation, type) and issubclass(annotation, BaseModel)


def _unwrap_optional(annotation: Any) -> tuple[Any, bool]:
    """Strip Optional[...] / Union[..., None], reporting whether it was there."""
    origin = typing.get_origin(annotation)
    if origin is Union:
        args = [a for a in typing.get_args(annotation) if a is not type(None)]
        if len(args) < len(typing.get_args(annotation)):
            return (args[0] if len(args) == 1 else Union[tuple(args)]), True
    return annotation, False


def _describe_type(annotation: Any) -> tuple[str, Optional[list[str]], Any]:
    """
    Return (type_name, enum_values, nested_model) for one annotation.

    Discriminated unions (the roster/sequence event types) resolve to a list of
    their member models so each variant can be documented.
    """
    annotation, _ = _unwrap_optional(annotation)

    if typing.get_origin(annotation) is typing.Annotated:
        annotation = typing.get_args(annotation)[0]
        annotation, _ = _unwrap_optional(annotation)

    origin = typing.get_origin(annotation)

    if origin is Literal:
        values = [str(v) for v in typing.get_args(annotation)]
        return "string", values, None

    if origin in (list, typing.List):
        (inner,) = typing.get_args(annotation) or (Any,)
        inner, _ = _unwrap_optional(inner)
        if typing.get_origin(inner) is typing.Annotated:
            inner = typing.get_args(inner)[0]
        if typing.get_origin(inner) is Union:
            members = [m for m in typing.get_args(inner) if _is_model(m)]
            return "array[object]", None, members or None
        if _is_model(inner):
            return "array[object]", None, inner
        name, values, _ = _describe_type(inner)
        return f"array[{name}]", values, None

    if origin is Union:
        members = [m for m in typing.get_args(annotation) if _is_model(m)]
        if members:
            return "object", None, members

    if _is_model(annotation):
        return "object", None, annotation

    return {
        int: "integer", float: "number", str: "string", bool: "boolean",
    }.get(annotation, getattr(annotation, "__name__", str(annotation)))  , None, None


def describe_model(model: type[BaseModel], _seen: frozenset = frozenset()) -> list[dict]:
    """
    Describe a request model's fields as guide `parameters` entries.

    Nested models are expanded inline so an integrator sees the whole shape —
    `preceding_fdp` is an object, and its own fields matter.
    """
    if model in _seen:
        return []
    _seen = _seen | {model}

    parameters: list[dict] = []
    for name, field in model.model_fields.items():
        type_name, enum_values, nested = _describe_type(field.annotation)
        required = field.is_required()

        entry: dict[str, Any] = {
            "name": name,
            "in": "body",
            "type": type_name,
            "required": required,
            "description": field.description or "",
        }
        if enum_values:
            entry["enum"] = enum_values
        if not required and field.default is not PydanticUndefined and field.default is not None:
            entry["default"] = field.default
        if nested is not None:
            members = nested if isinstance(nested, list) else [nested]
            fields: list[dict] = []
            for member in members:
                for sub in describe_model(member, _seen):
                    if sub["name"] not in {f["name"] for f in fields}:
                        if len(members) > 1:
                            sub = {**sub, "variant": member.__name__}
                        fields.append(sub)
            entry["fields"] = fields
        parameters.append(entry)
    return parameters


def parameter_names(model: type[BaseModel], _seen: frozenset = frozenset()) -> set[str]:
    """Every field name reachable from a request model, nested ones included."""
    names: set[str] = set()
    for entry in describe_model(model, _seen):
        names.add(entry["name"])
        for sub in entry.get("fields", []):
            names.add(sub["name"])
    return names


def response_shape(model: type[BaseModel]) -> dict:
    """
    Describe a response model as `{field: type}`, or return its own worked
    example where the model carries one.

    The hand-written `example_response_shape` blocks had drifted as far as the
    request documentation: `/calculate/max-fdp` advertised `max_fdp_hours`,
    `time_band`, `crosses_wocl` and `is_early_start`, none of which the
    response has ever contained under those names, while omitting every field
    it does return.
    """
    examples = (model.model_config.get("json_schema_extra") or {}).get("examples")
    if examples:
        return examples[0]

    shape: dict[str, Any] = {}
    for name, field in model.model_fields.items():
        type_name, enum_values, nested = _describe_type(field.annotation)
        if nested is not None and not isinstance(nested, list):
            shape[name] = (
                [{f["name"]: f["type"] for f in describe_model(nested)}]
                if type_name.startswith("array")
                else {f["name"]: f["type"] for f in describe_model(nested)}
            )
        elif enum_values:
            shape[name] = " | ".join(enum_values)
        else:
            shape[name] = type_name
    return shape
