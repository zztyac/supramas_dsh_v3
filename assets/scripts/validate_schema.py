from __future__ import annotations

import argparse
import json
import sys
import warnings
from pathlib import Path

try:  # Prefer the real Draft 2020-12 implementation when it is installed.
    with warnings.catch_warnings():
        warnings.filterwarnings("ignore", category=DeprecationWarning)
        from jsonschema import Draft202012Validator, RefResolver

    HAVE_JSONSCHEMA = True
except ImportError:  # pragma: no cover - depends on the environment
    HAVE_JSONSCHEMA = False

try:  # `python scripts/x.py` puts scripts/ on sys.path; `python -m scripts.x` does not.
    from json_schema_lite import iter_errors as lite_iter_errors
except ModuleNotFoundError:  # pragma: no cover - depends on how the script is launched
    from scripts.json_schema_lite import iter_errors as lite_iter_errors  # type: ignore[no-redef]


def load_schema_store(schema_dir: Path) -> dict[str, dict]:
    store: dict[str, dict] = {}
    for path in schema_dir.glob("*.schema.json"):
        schema = json.loads(path.read_text(encoding="utf-8"))
        store[path.name] = schema
        store[path.resolve().as_uri()] = schema
        if "$id" in schema:
            store[schema["$id"]] = schema
    return store


def collect_errors(data: object, schema: dict, schema_dir: Path) -> list[str]:
    """Return `location: message` strings for every violation."""
    if HAVE_JSONSCHEMA:
        store = load_schema_store(schema_dir)
        resolver = RefResolver(
            base_uri=schema_dir.resolve().as_uri() + "/", referrer=schema, store=store
        )
        validator = Draft202012Validator(schema, resolver=resolver)
        found = sorted(validator.iter_errors(data), key=lambda error: list(error.path))
        return [
            f"{'/'.join(str(part) for part in error.path) or '<root>'}: {error.message}"
            for error in found
        ]
    return lite_iter_errors(data, schema)


def validate_file(data_path: Path, schema_path: Path) -> None:
    data = json.loads(data_path.read_text(encoding="utf-8"))
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    errors = collect_errors(data, schema, schema_path.parent)
    if errors:
        for message in errors:
            print(message)
        raise SystemExit(1)
    print(f"valid: {data_path}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate a JSON file against a JSON schema.")
    parser.add_argument("json_file", type=Path)
    parser.add_argument("--schema", type=Path, required=True)
    parser.add_argument(
        "--engine",
        action="store_true",
        help="Print which validation engine is in use (jsonschema or the bundled subset validator).",
    )
    args = parser.parse_args()

    if args.engine:
        print(
            "engine: jsonschema" if HAVE_JSONSCHEMA else "engine: json_schema_lite (bundled)",
            file=sys.stderr,
        )

    validate_file(args.json_file, args.schema)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
