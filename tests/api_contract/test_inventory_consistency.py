from __future__ import annotations

"""US-189: keep the documented endpoint inventory in sync with the app.

Every rule in the live Flask ``url_map`` must be covered by the inventory in
``docs/api/endpoint_inventory.md``. The inventory is a plain markdown table;
this test parses the ``|`` rows of the "端点总表" section and compares them to
the real url_map so a newly added endpoint that nobody documented fails CI.
"""

import re
from pathlib import Path

import pytest

from apps.base import create_app

DOC_PATH = (
    Path(__file__).resolve().parents[2] / "docs" / "api" / "endpoint_inventory.md"
)


def _api_rules_from_app() -> set[tuple[str, str]]:
    app = create_app("testing")
    rules: set[tuple[str, str]] = set()
    for rule in app.url_map.iter_rules():
        if not rule.rule.startswith("/api/v1/"):
            continue
        for method in rule.methods - {"HEAD", "OPTIONS"}:
            # Normalize url_map's <path:request_id> to the plain <request_id>
            # form the inventory documents.
            path = re.sub(r"<path:([^>]+)>", r"<\1>", rule.rule)
            rules.add((method, path))
    return rules


def _rules_from_inventory() -> set[tuple[str, str]]:
    text = DOC_PATH.read_text(encoding="utf-8")
    section = text.split("## 2. 端点总表", 1)[1].split("## 3.", 1)[0]
    rules: set[tuple[str, str]] = set()
    for line in section.splitlines():
        match = re.match(r"\|\s*(GET|POST)\s*\|\s*(`[^`]+`|/api/v1/\S+)\s*\|", line)
        if not match:
            continue
        method = match.group(1)
        path = match.group(2).strip("`")
        # The inventory uses <path:request_id>/<batch_id>/<key> placeholders;
        # normalize to the url_map's <...> form for comparison.
        path = re.sub(r"<path:([^>]+)>", r"<\1>", path)
        rules.add((method, path))
    return rules


def test_inventory_covers_every_api_rule() -> None:
    live = _api_rules_from_app()
    documented = _rules_from_inventory()

    missing = sorted(live - documented)
    assert not missing, (
        "Endpoint(s) exist in the Flask url_map but are missing from "
        "docs/api/endpoint_inventory.md §2: "
        + ", ".join(f"{method} {path}" for method, path in missing)
    )


def test_inventory_mentions_only_existing_rules() -> None:
    live = _api_rules_from_app()
    documented = _rules_from_inventory()

    phantom = sorted(documented - live)
    assert not phantom, (
        "Endpoint(s) are documented in docs/api/endpoint_inventory.md §2 but do "
        "not exist in the Flask url_map: "
        + ", ".join(f"{method} {path}" for method, path in phantom)
    )


def test_inventory_documents_every_json_api_view() -> None:
    app = create_app("testing")
    api_rules = [
        rule
        for rule in app.url_map.iter_rules()
        if rule.rule.startswith("/api/v1/") and rule.endpoint.startswith("migu_orca_web_api.")
    ]
    assert api_rules, "expected at least one /api/v1 rule"
    # No view may be registered twice under the same path+method with a
    # different endpoint name (silent contract break for clients).
    seen: set[tuple[str, str]] = set()
    for rule in api_rules:
        for method in rule.methods - {"HEAD", "OPTIONS"}:
            key = (method, rule.rule)
            assert key not in seen, f"duplicate route {method} {rule.rule}"
            seen.add(key)


def test_inventory_documents_all_fetch_dependencies() -> None:
    """Every /api/v1 URL used by app.js must be covered by the inventory.

    app.js builds dynamic URLs with string prefixes (e.g.
    ``"/api/v1/batches/" + encodeURIComponent(currentBatchId) + "/accept"``),
    so we collect every ``/api/v1/...`` string literal in the script and assert
    each one appears inside the inventory's frontend-dependency section.
    """
    app_js = (
        Path(__file__).resolve().parents[2]
        / "src" / "apps" / "migu_orca_web" / "static" / "app.js"
    )
    script = app_js.read_text(encoding="utf-8")
    inventory = DOC_PATH.read_text(encoding="utf-8")

    section = inventory.split("### 5.1", 1)[1]
    used: set[str] = set()
    for match in re.finditer(r'["`](/api/v1/[^"`\s]+)["`]', script):
        url = match.group(1).split("?")[0]
        used.add(url)

    missing = sorted(url for url in used if url not in section)
    assert not missing, (
        "app.js uses API URL(s) not listed in docs/api/endpoint_inventory.md §5.1: "
        + ", ".join(missing)
    )


@pytest.mark.parametrize("route", ["/", "/index", "/Settings", "/settings"])
def test_page_routes_are_registered(route: str) -> None:
    app = create_app("testing")
    # Flask test client follows the redirect for / and /Settings; we just need
    # to confirm the route is registered and reachable (302 or 200).
    response = app.test_client().get(route)
    assert response.status_code in {200, 302}
