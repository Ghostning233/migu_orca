#!/usr/bin/env python
"""Request-body equivalence report for the OpenAPI document (issue #171).

Issue #171 moved every ``requestBody`` in ``docs/api/openapi.json`` from a
handwritten registry copy onto a pipeline derived from the pydantic models in
``src/apps/migu_orca_web/schemas.py``.  This tool diffs a *reference* document
(the pre-migration artifact) against the *current* one, per endpoint and per
property, and classifies every difference so the migration can be reviewed
instead of trusted.

Each leaf difference is classified as:

- ``structure``: a change to properties / required / type / enum / const /
  default / additionalProperties / nullable / numeric bounds / array bounds /
  union composition.  These change the contract and need an explanation.
- ``documentation``: a change to a ``description``/``example``/``x-*`` marker
  (they reach the generated client's JSDoc but not the types).
- ``metadata``: pydantic JSON-Schema metadata (``title``) or a key-order-only
  difference; not part of the published contract.

Usage::

    git show <ref>:docs/api/openapi.json > /tmp/openapi-reference.json
    uv run python tools/openapi_request_body_equivalence.py \
        /tmp/openapi-reference.json docs/api/openapi.json

Exit status is 0 even when differences exist (the report is the output); pass
``--fail-on-structure`` to exit 1 when any structural difference is found.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

DOCUMENTATION_KEYS = frozenset(
    {
        "description",
        "example",
        "deprecated",
        "readOnly",
        "writeOnly",
        "x-request-scoped",
        "x-legacy",
    }
)
METADATA_KEYS = frozenset({"title", "$ref", "$defs"})
#: Container keys whose element order is not semantically meaningful.
UNORDERED_KEYS = frozenset({"required", "anyOf", "oneOf", "allOf", "enum"})


def request_bodies(document: dict[str, Any]) -> dict[tuple[str, str], tuple[Any, Any]]:
    """Map ``(method, path)`` to the ``(schema, example)`` of its JSON body."""
    bodies: dict[tuple[str, str], tuple[Any, Any]] = {}
    for path, methods in document.get("paths", {}).items():
        for method, operation in methods.items():
            if not isinstance(operation, dict):
                continue
            body = operation.get("requestBody")
            if not body:
                continue
            media = body.get("content", {}).get("application/json", {})
            bodies[(method.upper(), path)] = (media.get("schema"), media.get("example"))
    return bodies


def classify(key: str) -> str:
    if key in DOCUMENTATION_KEYS:
        return "documentation"
    if key in METADATA_KEYS:
        return "metadata"
    return "structure"


def child_bucket(parent: str, key: str) -> str:
    """Bucket for ``key`` nested in a node already classified as ``parent``.

    ``field`` marks a ``properties`` map: its keys are user-visible field names
    named like pydantic metadata (``title``/``description``), so they must not
    be classified by name. Both ``structure`` and ``field`` report as structure.
    """
    if parent == "documentation":
        return "documentation"
    if parent == "field":
        return "field"
    if key == "properties":
        return "field"
    return classify(key)


def _unordered_equal(left: Any, right: Any) -> bool:
    return json.dumps(left, sort_keys=True) == json.dumps(right, sort_keys=True)


def diff_nodes(
    reference: Any,
    current: Any,
    path: str,
    kind: str,
    out: list[tuple[str, str, str, str]],
) -> None:
    """Append ``(bucket, path, reference, current)`` leaf differences."""
    if isinstance(reference, dict) and isinstance(current, dict):
        for key in sorted(set(reference) | set(current)):
            child = f"{path}.{key}" if path else key
            bucket = child_bucket(kind, key)
            if key not in reference:
                out.append((bucket, child, "<absent>", _short(current[key])))
            elif key not in current:
                out.append((bucket, child, _short(reference[key]), "<absent>"))
            else:
                diff_nodes(reference[key], current[key], child, bucket, out)
        return
    if isinstance(reference, list) and isinstance(current, list):
        if reference == current:
            return
        if len(reference) == len(current):
            if _unordered_equal(reference, current):
                out.append(("metadata", f"{path} (element order)", "<reordered>", "<reordered>"))
                return
            for index, (before, after) in enumerate(zip(reference, current, strict=True)):
                diff_nodes(before, after, f"{path}[{index}]", kind, out)
            return
        out.append((kind, path, _short(reference), _short(current)))
        return
    if reference != current:
        out.append((kind, path, _short(reference), _short(current)))


def bucket_name(kind: str) -> str:
    return "structure" if kind == "field" else kind


def _short(value: Any, limit: int = 120) -> str:
    text = json.dumps(value, ensure_ascii=False)
    return text if len(text) <= limit else text[: limit - 1] + "…"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("reference", type=Path, help="pre-migration OpenAPI document")
    parser.add_argument("current", type=Path, help="current OpenAPI document")
    parser.add_argument(
        "--fail-on-structure",
        action="store_true",
        help="exit 1 when any structural difference is reported",
    )
    args = parser.parse_args(argv)

    reference = json.loads(args.reference.read_text(encoding="utf-8"))
    current = json.loads(args.current.read_text(encoding="utf-8"))
    left, right = request_bodies(reference), request_bodies(current)

    print("# OpenAPI request-body equivalence report\n")
    print(f"reference: `{args.reference}`")
    print(f"current:   `{args.current}`\n")
    print(f"- endpoints with a request body: {len(left)} (reference) / {len(right)} (current)")
    only_reference = sorted(set(left) - set(right))
    only_current = sorted(set(right) - set(left))
    print(f"- only in reference: {only_reference or 'none'}")
    print(f"- only in current:   {only_current or 'none'}\n")

    structural = 0
    documented = 0
    for key in sorted(left):
        if key not in right:
            continue
        differences: list[tuple[str, str, str, str]] = []
        reference_schema, reference_example = left[key]
        current_schema, current_example = right[key]
        diff_nodes(reference_schema, current_schema, "", "structure", differences)
        diff_nodes(reference_example, current_example, "example", "documentation", differences)
        by_kind: dict[str, list[tuple[str, str, str, str]]] = {"structure": [], "documentation": [], "metadata": []}
        for item in differences:
            by_kind[bucket_name(item[0])].append(item)
        structural += len(by_kind["structure"])
        documented += len(by_kind["documentation"])
        print(f"## {key[0]} {key[1]}\n")
        if not differences:
            print("No differences.\n")
            continue
        print(
            f"{len(by_kind['structure'])} structural / "
            f"{len(by_kind['documentation'])} documentation / "
            f"{len(by_kind['metadata'])} metadata difference(s).\n"
        )
        for kind in ("structure", "documentation", "metadata"):
            if not by_kind[kind]:
                continue
            print(f"### {kind} ({len(by_kind[kind])})\n")
            for _, path, before, after in by_kind[kind]:
                print(f"- `{path}`: `{before}` -> `{after}`")
            print()

    print("## Summary\n")
    print(f"- structural differences: {structural}")
    print(f"- documentation differences: {documented}")
    if args.fail_on_structure and structural:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
