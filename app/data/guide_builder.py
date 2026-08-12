"""
Model introspection for the GET /guide endpoint.

/guide used to be maintained by hand, and it drifted. It documented a
`local_start_time_of_day_hours` parameter the API no longer accepts, a flat
parameter set for `/calculate/min-off-duty` that had since become a nested
`preceding_fdp` object, an `acclimatisation` enum value (`not_acclimatised`)
the API rejects, and a three-day acclimatisation rule that appears nowhere in
CAO 48.1. It never documented `adjustments[]` at all, and it never mentioned
`acclimatised_time_offset_hours` — a shipped, safety-relevant field that the
first integrator to go looking for it could not find, and consequently
reported as missing.

Everything in this module derives the parameter and response documentation
from the live Pydantic models, so it cannot drift again. Editorial content
(purpose, when to use, common mistakes) stays hand-written in guide.py,
because no amount of introspection produces that.
"""

from __future__ import annotations

import types
from enum import Enum
from typing import Any, Literal, Union, get_args, get_origin

from pydantic import BaseModel
from pydantic_core import PydanticUndefined

# Prevents runaway recursion on any accidentally self-referential model.
_MAX_NESTING_DEPTH = 4

# Both spellings of a union: typing.Union[A, B] and the PEP 604 `A | B`.
# types.UnionType only exists from Python 3.10; the tuple stays valid either way.
_UNION_ORIGINS = tuple(
    origin for origin in (Union, getattr(types, "UnionType", None))
    if origin is not None
)


def _is_union(origin: Any) -> bool:
    """
    True if a type origin is a union.

    Written as an explicit None guard rather than an `is` chain: an earlier
    version compared against a fallback that evaluated to None, which meant
    every plain type (whose origin is also None) was treated as a union and
    rendered as an empty string.
    """
    return origin is not None and origin in _UNION_ORIGINS


# ═══════════════════════════════════════════════════════════════════════
# Type rendering
# ═══════════════════════════════════════════════════════════════════════

def _unwrap_optional(annotation: Any) -> tuple[Any, bool]:
    """
    Strip Optional[...] / Union[..., None] from an annotation.

    Returns
    -------
    (inner_annotation, was_optional)
    """
    origin = get_origin(annotation)
    if _is_union(origin):
        args = [a for a in get_args(annotation) if a is not type(None)]
        if len(args) != len(get_args(annotation)):
            return (args[0] if len(args) == 1 else Union[tuple(args)]), True
    return annotation, False


def _type_name(annotation: Any) -> str:
    """Render a type annotation as a short, readable string for the guide."""
    annotation, optional = _unwrap_optional(annotation)
    suffix = " (nullable)" if optional else ""

    origin = get_origin(annotation)

    if origin is Literal:
        return "string (enum)" + suffix

    if origin in (list, set, tuple):
        args = get_args(annotation)
        inner = _type_name(args[0]) if args else "any"
        return f"array of {inner}{suffix}"

    if origin is dict:
        return "object" + suffix

    if _is_union(origin):
        return " | ".join(_type_name(a) for a in get_args(annotation)) + suffix

    if isinstance(annotation, type):
        if issubclass(annotation, BaseModel):
            return f"object ({annotation.__name__})" + suffix
        if issubclass(annotation, Enum):
            return "string (enum)" + suffix
        simple = {
            str: "string", int: "integer", float: "number", bool: "boolean",
        }
        for python_type, label in simple.items():
            if annotation is python_type:
                return label + suffix
        if annotation.__name__ == "datetime":
            return "string (ISO 8601 datetime)" + suffix

    return str(annotation).replace("typing.", "") + suffix


def _literal_values(annotation: Any) -> list[Any] | None:
    """Extract the permitted values from a Literal annotation, if it is one."""
    annotation, _ = _unwrap_optional(annotation)
    if get_origin(annotation) is Literal:
        return list(get_args(annotation))
    if isinstance(annotation, type) and issubclass(annotation, Enum):
        return [member.value for member in annotation]
    return None


def _nested_model(annotation: Any) -> type[BaseModel] | None:
    """Return the nested Pydantic model in an annotation, if there is one."""
    annotation, _ = _unwrap_optional(annotation)

    if isinstance(annotation, type) and issubclass(annotation, BaseModel):
        return annotation

    origin = get_origin(annotation)
    if origin in (list, set, tuple):
        args = get_args(annotation)
        if args:
            return _nested_model(args[0])

    if _is_union(origin):
        for arg in get_args(annotation):
            found = _nested_model(arg)
            if found is not None:
                return found

    # Annotated[...] — e.g. discriminated unions
    if hasattr(annotation, "__metadata__"):
        return _nested_model(get_args(annotation)[0])

    return None


def _constraints(field: Any) -> dict[str, Any]:
    """
    Extract numeric and length constraints from a field's metadata.

    Surfaces ge / gt / le / lt / min_length so integrators can see, for
    example, that `sectors` must be at least 1 without having to discover it
    from a 422.
    """
    found: dict[str, Any] = {}
    for item in getattr(field, "metadata", []) or []:
        for attribute in ("ge", "gt", "le", "lt", "min_length", "max_length"):
            value = getattr(item, attribute, None)
            if value is not None:
                found[attribute] = value
    return found


# ═══════════════════════════════════════════════════════════════════════
# Field extraction
# ═══════════════════════════════════════════════════════════════════════

def describe_model(
    model: type[BaseModel],
    depth: int = 0,
    _seen: frozenset[str] | None = None,
) -> list[dict]:
    """
    Describe every field on a Pydantic model, recursing into nested models.

    Parameters
    ----------
    model : type[BaseModel]
        The model to describe.
    depth : int
        Current recursion depth, used to cap nesting.
    _seen : frozenset of str
        Model names already expanded on this branch, to break any cycle.

    Returns
    -------
    list of dict
        One entry per field: name, type, required, description, and where
        applicable default, valid_values, constraints and nested fields.
    """
    _seen = _seen or frozenset()
    if model.__name__ in _seen or depth > _MAX_NESTING_DEPTH:
        return []

    fields: list[dict] = []

    for name, field in model.model_fields.items():
        entry: dict[str, Any] = {
            "name": name,
            "type": _type_name(field.annotation),
            "required": field.is_required(),
            "description": field.description or "",
        }

        if not field.is_required() and field.default is not PydanticUndefined:
            # default_factory results are not serialisable here; report the
            # concrete default only.
            entry["default"] = field.default

        values = _literal_values(field.annotation)
        if values:
            entry["valid_values"] = values

        constraints = _constraints(field)
        if constraints:
            entry["constraints"] = constraints

        nested = _nested_model(field.annotation)
        if nested is not None:
            child_fields = describe_model(
                nested, depth + 1, _seen | {model.__name__},
            )
            if child_fields:
                entry["object_name"] = nested.__name__
                entry["fields"] = child_fields

        fields.append(entry)

    return fields


def model_example(model: type[BaseModel]) -> dict | None:
    """
    Pull the worked example out of a model's json_schema_extra, if it has one.

    Using the model's own example rather than a separately maintained copy
    means the guide's example is the same object the OpenAPI schema shows and
    the same one the tests exercise.
    """
    extra = (model.model_config or {}).get("json_schema_extra") or {}
    examples = extra.get("examples") if isinstance(extra, dict) else None
    if examples:
        return examples[0]
    return None


def describe_endpoint(
    request_model: type[BaseModel] | None = None,
    response_model: type[BaseModel] | None = None,
    path_parameters: list[dict] | None = None,
) -> dict:
    """
    Build the generated portion of a /guide endpoint entry.

    Returns a dict with `parameters`, and where the models allow it
    `example_request`, `response_fields` and `example_response_shape`.
    """
    generated: dict[str, Any] = {"parameters": list(path_parameters or [])}

    if request_model is not None:
        generated["parameters"].extend(describe_model(request_model))
        generated["request_body_model"] = request_model.__name__
        example = model_example(request_model)
        if example is not None:
            generated["example_request"] = example

    if response_model is not None:
        generated["response_model"] = response_model.__name__
        generated["response_fields"] = describe_model(response_model)
        example = model_example(response_model)
        generated["example_response_shape"] = (
            example if example is not None else response_skeleton(response_model)
        )

    return generated


def response_skeleton(
    model: type[BaseModel],
    depth: int = 0,
    _seen: frozenset[str] | None = None,
) -> dict:
    """
    Build a type-annotated skeleton of a response model.

    Used where a response model carries no worked example. Every value is the
    rendered type name rather than a plausible-looking number, so nobody can
    mistake the skeleton for real regulatory output — which matters on an API
    whose numbers are fatigue limits.
    """
    _seen = _seen or frozenset()
    if model.__name__ in _seen or depth > _MAX_NESTING_DEPTH:
        return {}

    skeleton: dict[str, Any] = {}
    for name, field in model.model_fields.items():
        nested = _nested_model(field.annotation)
        annotation, _ = _unwrap_optional(field.annotation)
        is_list = get_origin(annotation) in (list, set, tuple)

        if nested is not None:
            child = response_skeleton(nested, depth + 1, _seen | {model.__name__})
            skeleton[name] = [child] if is_list else child
        else:
            skeleton[name] = _type_name(field.annotation)

    return skeleton
