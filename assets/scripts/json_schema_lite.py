#!/usr/bin/env python3
"""A small, dependency-free JSON Schema validator for this repo's schemas.

Why this exists: `scripts/validate_schema.py` is the schema gate for exported
strategy trees and idea states. Requiring `jsonschema` would mean the SupraMAS
DeepSeek Harness bundle needs a Python dependency step, and would make the gate
disappear whenever that package is absent. This module covers the keyword subset
the two schemas under `schemas/` actually use, so the gate always runs.

Supported keywords:
    $ref (local "#/$defs/<name>" and "#/definitions/<name>"), $defs, definitions,
    type (string or list of strings), enum, const, required, properties,
    additionalProperties (bool or schema), items, minItems, maxItems,
    minimum, maximum, exclusiveMinimum, exclusiveMaximum, minLength, maxLength,
    pattern, propertyNames, allOf, anyOf, oneOf, not

Anything outside that set is ignored rather than silently mis-evaluated: callers
that need full Draft 2020-12 behaviour should use `jsonschema` when available.
`scripts/validate_schema.py` prefers it automatically.
"""

from __future__ import annotations

import re
from typing import Any

# JSON Schema type name -> predicate.
_TYPE_CHECKS = {
    "object": lambda value: isinstance(value, dict),
    "array": lambda value: isinstance(value, list),
    "string": lambda value: isinstance(value, str),
    # bool is a subclass of int in Python; JSON Schema treats them as distinct.
    "integer": lambda value: isinstance(value, int) and not isinstance(value, bool),
    "number": lambda value: isinstance(value, (int, float)) and not isinstance(value, bool),
    "boolean": lambda value: isinstance(value, bool),
    "null": lambda value: value is None,
}


def _location(path: tuple[Any, ...]) -> str:
    return "/".join(str(part) for part in path) or "<root>"


def _resolve_ref(ref: str, root: dict) -> dict | None:
    """Resolve a local JSON Pointer reference against the root schema."""
    if not ref.startswith("#/"):
        return None
    node: Any = root
    for token in ref[2:].split("/"):
        token = token.replace("~1", "/").replace("~0", "~")
        if not isinstance(node, dict) or token not in node:
            return None
        node = node[token]
    return node if isinstance(node, dict) else None


def _check_type(value: Any, expected: Any, path: tuple, errors: list[str]) -> bool:
    """Return True when the value satisfies the declared type."""
    if isinstance(expected, list):
        if any(_TYPE_CHECKS.get(name, lambda _v: True)(value) for name in expected):
            return True
        errors.append(f"{_location(path)}: {value!r} is not of type {expected}")
        return False
    if expected not in _TYPE_CHECKS:
        return True  # Unknown type name: do not fabricate a failure.
    if _TYPE_CHECKS[expected](value):
        return True
    errors.append(f"{_location(path)}: {value!r} is not of type '{expected}'")
    return False


def _validate(instance: Any, schema: Any, root: dict, path: tuple, errors: list[str]) -> None:
    if not isinstance(schema, dict):
        return

    if "$ref" in schema:
        target = _resolve_ref(schema["$ref"], root)
        if target is None:
            errors.append(f"{_location(path)}: cannot resolve $ref {schema['$ref']!r}")
            return
        _validate(instance, target, root, path, errors)
        # A sibling of $ref is allowed in 2020-12; keep evaluating it below.

    if "type" in schema and not _check_type(instance, schema["type"], path, errors):
        # Further keyword checks assume the type held.
        return

    if "const" in schema and instance != schema["const"]:
        errors.append(f"{_location(path)}: {instance!r} is not the const {schema['const']!r}")

    if "enum" in schema and instance not in schema["enum"]:
        errors.append(f"{_location(path)}: {instance!r} is not one of {schema['enum']}")

    if isinstance(instance, dict):
        _validate_object(instance, schema, root, path, errors)
    elif isinstance(instance, list):
        _validate_array(instance, schema, root, path, errors)
    elif isinstance(instance, str):
        _validate_string(instance, schema, path, errors)
    elif isinstance(instance, (int, float)) and not isinstance(instance, bool):
        _validate_number(instance, schema, path, errors)

    for combinator in ("allOf",):
        for subschema in schema.get(combinator, []) or []:
            _validate(instance, subschema, root, path, errors)

    if "anyOf" in schema:
        if not any(not _collect(instance, sub, root, path) for sub in schema["anyOf"]):
            errors.append(f"{_location(path)}: {instance!r} does not match any of the anyOf schemas")

    if "oneOf" in schema:
        matches = sum(1 for sub in schema["oneOf"] if not _collect(instance, sub, root, path))
        if matches != 1:
            errors.append(
                f"{_location(path)}: {instance!r} matches {matches} of the oneOf schemas, expected exactly 1"
            )

    if "not" in schema and not _collect(instance, schema["not"], root, path):
        errors.append(f"{_location(path)}: {instance!r} matches a 'not' schema")


def _collect(instance: Any, schema: Any, root: dict, path: tuple) -> list[str]:
    """Return the errors for one subschema, without touching the shared list."""
    nested: list[str] = []
    _validate(instance, schema, root, path, nested)
    return nested


def _validate_object(instance: dict, schema: dict, root: dict, path: tuple, errors: list[str]) -> None:
    for name in schema.get("required", []) or []:
        if name not in instance:
            errors.append(f"{_location(path)}: {name!r} is a required property")

    properties = schema.get("properties") or {}
    for name, subschema in properties.items():
        if name in instance:
            _validate(instance[name], subschema, root, path + (name,), errors)

    additional = schema.get("additionalProperties", True)
    extras = [name for name in instance if name not in properties]
    if additional is False:
        for name in extras:
            errors.append(f"{_location(path)}: additional property {name!r} is not allowed")
    elif isinstance(additional, dict) and additional:
        for name in extras:
            _validate(instance[name], additional, root, path + (name,), errors)

    property_names = schema.get("propertyNames")
    if isinstance(property_names, dict):
        for name in instance:
            _validate(name, property_names, root, path + (name,), errors)


def _validate_array(instance: list, schema: dict, root: dict, path: tuple, errors: list[str]) -> None:
    if "minItems" in schema and len(instance) < schema["minItems"]:
        errors.append(f"{_location(path)}: {instance!r} is too short (minimum {schema['minItems']})")
    if "maxItems" in schema and len(instance) > schema["maxItems"]:
        errors.append(f"{_location(path)}: {instance!r} is too long (maximum {schema['maxItems']})")
    items = schema.get("items")
    if isinstance(items, dict):
        for index, item in enumerate(instance):
            _validate(item, items, root, path + (index,), errors)


def _validate_string(instance: str, schema: dict, path: tuple, errors: list[str]) -> None:
    if "minLength" in schema and len(instance) < schema["minLength"]:
        errors.append(f"{_location(path)}: {instance!r} is too short (minimum {schema['minLength']})")
    if "maxLength" in schema and len(instance) > schema["maxLength"]:
        errors.append(f"{_location(path)}: {instance!r} is too long (maximum {schema['maxLength']})")
    if "pattern" in schema:
        try:
            if not re.search(schema["pattern"], instance):
                errors.append(f"{_location(path)}: {instance!r} does not match {schema['pattern']!r}")
        except re.error:
            pass


def _validate_number(instance: float, schema: dict, path: tuple, errors: list[str]) -> None:
    if "minimum" in schema and instance < schema["minimum"]:
        errors.append(f"{_location(path)}: {instance!r} is less than the minimum {schema['minimum']}")
    if "maximum" in schema and instance > schema["maximum"]:
        errors.append(f"{_location(path)}: {instance!r} is greater than the maximum {schema['maximum']}")
    if "exclusiveMinimum" in schema and instance <= schema["exclusiveMinimum"]:
        errors.append(f"{_location(path)}: {instance!r} is not greater than {schema['exclusiveMinimum']}")
    if "exclusiveMaximum" in schema and instance >= schema["exclusiveMaximum"]:
        errors.append(f"{_location(path)}: {instance!r} is not less than {schema['exclusiveMaximum']}")


def iter_errors(instance: Any, schema: dict) -> list[str]:
    """Return `location: message` strings for every violation, sorted by location."""
    errors: list[str] = []
    _validate(instance, schema, schema, (), errors)
    return sorted(set(errors), key=lambda message: message.split(":", 1)[0])
