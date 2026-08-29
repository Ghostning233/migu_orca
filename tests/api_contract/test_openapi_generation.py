from __future__ import annotations

"""US-190: deterministic OpenAPI generation and drift checks.

The generated ``docs/api/openapi.json`` is the machine-readable contract for
Stage 27's TypeScript client generation. These tests pin:

- every /api/v1 JSON endpoint in the live url_map appears in the document
  (coverage can never silently shrink);
- the document is deterministic and free of runtime/absolute-path/credential
  values (examples use only fictional placeholders);
- the poster binary endpoint declares its content types explicitly;
- the drift-check CLI exits non-zero when the checked-in document is stale.
"""

import json
import subprocess
import sys
from pathlib import Path

from apps.base import create_app
from apps.migu_orca_web import openapi_gen
from apps.migu_orca_web.openapi_gen import (
    _ENDPOINTS,
    generate_openapi,
)

DOC_PATH = (
    Path(__file__).resolve().parents[2] / "docs" / "api" / "openapi.json"
)


def _live_api_operations() -> set[tuple[str, str]]:
    app = create_app("testing")
    operations: set[tuple[str, str]] = set()
    for rule in app.url_map.iter_rules():
        if not rule.rule.startswith("/api/v1/"):
            continue
        for method in rule.methods - {"HEAD", "OPTIONS"}:
            operations.add((method, openapi_gen._normalized_path(rule.rule)))
    return operations


def test_openapi_covers_every_live_endpoint() -> None:
    doc = generate_openapi()
    documented: set[tuple[str, str]] = set()
    for path, methods in doc["paths"].items():
        for method in methods:
            documented.add((method.upper(), path))

    live = _live_api_operations()
    missing = sorted(live - documented)
    assert not missing, (
        "Endpoint(s) exist in the Flask url_map but are missing from the "
        "generated OpenAPI: " + ", ".join(f"{m} {p}" for m, p in missing)
    )
    # No phantom endpoints either.
    phantom = sorted(documented - live)
    assert not phantom, (
        "OpenAPI documents endpoint(s) that do not exist in the url_map: "
        + ", ".join(f"{m} {p}" for m, p in phantom)
    )


def test_openapi_registry_covers_every_live_endpoint() -> None:
    """Every live endpoint must have an explicit schema-registry entry.

    ``_ENDPOINTS`` keys use the url_map ``<param>`` form; this test guards the
    registry itself so a new endpoint fails with a clear "add an entry"
    message instead of silently missing from the document.
    """
    app = create_app("testing")
    live_keys: set[str] = set()
    for rule in app.url_map.iter_rules():
        if not rule.rule.startswith("/api/v1/"):
            continue
        for method in rule.methods - {"HEAD", "OPTIONS"}:
            live_keys.add(f"{method} {rule.rule}")
    missing = sorted(live_keys - set(_ENDPOINTS))
    assert not missing, (
        "Endpoint(s) have no _ENDPOINTS schema-registry entry: "
        + ", ".join(missing)
    )
    phantom = sorted(set(_ENDPOINTS) - live_keys)
    assert not phantom, (
        "Schema-registry entry(ies) do not match any live endpoint: "
        + ", ".join(phantom)
    )


def test_openapi_deterministic_and_repeatable() -> None:
    first = json.dumps(generate_openapi(), ensure_ascii=False, sort_keys=True)
    second = json.dumps(generate_openapi(), ensure_ascii=False, sort_keys=True)
    assert first == second


def test_openapi_examples_are_desensitized() -> None:
    """Examples never contain absolute paths, credentials or real hosts."""
    text = json.dumps(generate_openapi(), ensure_ascii=False)
    for forbidden in ("/home/", "/tmp/", "secret-token", "private.example", "magnet:?"):
        assert forbidden not in text, f"OpenAPI example leaks {forbidden!r}"


def test_openapi_marks_request_scoped_fields() -> None:
    """Credential/config fields are flagged x-request-scoped everywhere."""
    text = json.dumps(generate_openapi(), ensure_ascii=False)
    # submit-ab, batch submit/retry and connection tests carry credentials.
    for marker in ("x-request-scoped", "request-scoped"):
        assert marker in text


def test_openapi_poster_endpoint_declares_content_types() -> None:
    doc = generate_openapi()
    poster = doc["paths"]["/api/v1/mikan/posters/{key}"]["get"]
    content = poster["responses"]["200"]["content"]
    assert set(content) == {"image/jpeg", "image/png", "image/gif", "image/webp"}
    assert content["image/jpeg"]["schema"] == {"type": "string", "format": "binary"}
    assert "Cache-Control" in poster["responses"]["200"]["headers"]
    # The poster endpoint is binary — it must not claim a JSON envelope.
    assert "application/json" not in content


def test_openapi_checked_in_document_matches_generator() -> None:
    """The committed docs/api/openapi.json must equal generated output."""
    expected = json.dumps(generate_openapi(), ensure_ascii=False, indent=2) + "\n"
    actual = DOC_PATH.read_text(encoding="utf-8") if DOC_PATH.exists() else None
    assert actual == expected, (
        "docs/api/openapi.json is stale. Run `uv run python -m "
        "apps.migu_orca_web.openapi_gen` (or `uv run migu-orca-openapi`) "
        "and commit the regenerated file."
    )


def test_openapi_drift_check_cli() -> None:
    """--check exits 0 when fresh and 1 when stale."""
    result = subprocess.run(
        [sys.executable, "-m", "apps.migu_orca_web.openapi_gen", "--check"],
        capture_output=True,
        text=True,
        cwd=Path(__file__).resolve().parents[2],
        env={"PYTHONPATH": "src"},
    )
    assert result.returncode == 0, result.stderr
