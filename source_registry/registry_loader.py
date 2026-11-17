from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker
from jsonschema.exceptions import SchemaError
from referencing import Registry, Resource

PACKAGE_ROOT = Path(__file__).resolve().parent
DEFAULT_REGISTRY_PATH = PACKAGE_ROOT / "registry.json"
DEFAULT_SCHEMA_DIR = PACKAGE_ROOT / "schemas"
SCHEMA_FILES = (
    "registry.schema.json",
    "source.schema.json",
    "data.schema.json",
)


class RegistryLoaderError(ValueError):
    """Raised when a registry or its schemas cannot be loaded."""


class RegistryValidationError(RegistryLoaderError):
    """Raised when the registry fails schema or semantic validation."""


def _read_json(path: Path, description: str) -> Any:
    try:
        contents = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise RegistryLoaderError(
            f"Cannot read {description} at {path}: {exc}"
        ) from exc

    try:
        return json.loads(contents)
    except json.JSONDecodeError as exc:
        raise RegistryLoaderError(
            f"Invalid JSON in {description} at {path}: {exc}"
        ) from exc


def _load_schemas(schema_dir: Path) -> tuple[dict[str, dict[str, Any]], Registry]:
    schemas: dict[str, dict[str, Any]] = {}
    resources = Registry()

    for filename in SCHEMA_FILES:
        path = schema_dir / filename
        schema = _read_json(path, "schema")
        if not isinstance(schema, dict) or not isinstance(schema.get("$id"), str):
            raise RegistryLoaderError(
                f"Schema {path} must be an object with a string $id"
            )
        try:
            Draft202012Validator.check_schema(schema)
        except SchemaError as exc:
            raise RegistryLoaderError(
                f"Invalid JSON Schema at {path}: {exc.message}"
            ) from exc

        schemas[filename] = schema
        resources = resources.with_resource(
            schema["$id"],
            Resource.from_contents(schema),
        )

    return schemas, resources


def _semantic_errors(document: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    seen_sources: set[str] = set()

    for source_index, source in enumerate(document["sources"]):
        source_id = source["source_id"]
        source_path = f"sources[{source_index}]"
        if source_id in seen_sources:
            errors.append(f"{source_path}.source_id duplicates {source_id!r}")
        seen_sources.add(source_id)

        if source["auto_fetch"] and not source["enabled"]:
            errors.append(
                f"{source_path}.auto_fetch cannot be true when enabled is false"
            )

        fetch = source["fetch"]
        expected_backoffs = fetch["max_attempts"] - 1
        if len(fetch["retry_backoff_seconds"]) != expected_backoffs:
            errors.append(
                f"{source_path}.fetch.retry_backoff_seconds must contain "
                f"{expected_backoffs} entries because max_attempts includes "
                "the initial attempt"
            )

        seen_products: set[str] = set()
        for product_index, product in enumerate(source["products"]):
            product_id = product["product_id"]
            if product_id in seen_products:
                errors.append(
                    f"{source_path}.products[{product_index}].product_id "
                    f"duplicates {product_id!r}"
                )
            seen_products.add(product_id)

    return errors


def load_registry(
    registry_path: str | Path = DEFAULT_REGISTRY_PATH,
    schema_dir: str | Path = DEFAULT_SCHEMA_DIR,
) -> dict[str, Any]:
    path = Path(registry_path).resolve()
    schemas_path = Path(schema_dir).resolve()
    document = _read_json(path, "registry")
    schemas, resources = _load_schemas(schemas_path)

    validator = Draft202012Validator(
        schemas["registry.schema.json"],
        registry=resources,
        format_checker=FormatChecker(),
    )
    errors = sorted(
        validator.iter_errors(document),
        key=lambda error: tuple(str(part) for part in error.absolute_path),
    )
    if errors:
        details = "; ".join(
            f"{path}: {error.message}"
            for error in errors
            for path in [
                "$" + "".join(f"[{part}]" for part in error.absolute_path)
            ]
        )
        raise RegistryValidationError(
            f"Registry validation failed for {path}: {details}"
        )

    semantic_errors = _semantic_errors(document)
    if semantic_errors:
        raise RegistryValidationError(
            f"Registry validation failed for {path}: "
            + "; ".join(semantic_errors)
        )

    return document
