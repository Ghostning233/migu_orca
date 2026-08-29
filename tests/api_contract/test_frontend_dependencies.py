from __future__ import annotations

"""US-189: freeze the old frontend's dependencies on the API.

The legacy single-file frontend (`static/app.js`) is the only client we must
keep compatible through Stage 26/27. These tests freeze its localStorage keys,
URL state parameters, and API URL usage so a migration cannot silently break
old pages. No browser is required — the assertions read the served script.
"""

import re
from pathlib import Path

from flask.testing import FlaskClient

APP_JS_PATH = (
    Path(__file__).resolve().parents[2]
    / "src" / "apps" / "migu_orca_web" / "static" / "app.js"
)


def _script(client: FlaskClient) -> str:
    response = client.get("/migu-orca-static/app.js")
    assert response.status_code == 200
    return response.get_data(as_text=True)


def test_localstorage_keys_are_frozen(client: FlaskClient) -> None:
    script = _script(client)

    # These two keys are the ONLY browser-storage keys the frontend may use;
    # anything sensitive (endpoint/token/cookie/password) must stay out.
    assert "storageDir: \"miguOrca.web.storageDir\"" in script
    assert "saveRequest: \"miguOrca.web.saveRequest\"" in script

    # No other localStorage key is read or written.
    for match in re.finditer(r'(?:getItem|setItem|removeItem)\(\s*"([^"]+)"', script):
        key = match.group(1)
        assert key in {
            "miguOrca.web.storageDir",
            "miguOrca.web.saveRequest",
        }, f"unexpected localStorage key: {key}"

    # sessionStorage is never used (sensitive data must not be recoverable).
    assert "sessionStorage" not in script


def test_url_state_parameters_are_frozen(client: FlaskClient) -> None:
    script = _script(client)

    # request_id and batch_id are the only URL state the frontend syncs.
    assert 'url.searchParams.set("request_id", requestId)' in script
    assert 'url.searchParams.delete("request_id")' in script
    assert 'url.searchParams.set("batch_id", batchId)' in script
    assert 'url.searchParams.delete("batch_id")' in script

    # storage_dir is appended as a query string to GET API calls (current
    # contract; US-193 will migrate it to a server-allowed profile).
    assert 'return "?storage_dir=" + encodeURIComponent(storageDir)' in script

    # The frontend must never push sensitive config into the URL.
    for sensitive in ("token", "password", "cookie", "ab_config", "qbittorrent_config"):
        assert f"searchParams.set(\"{sensitive}\"" not in script


def test_all_api_fetch_urls_are_covered(client: FlaskClient) -> None:
    """Every API URL the frontend calls is a documented endpoint."""
    script = _script(client)

    # Static literal URLs used directly with fetchJson.
    for url in (
        "/api/v1/requests",
        "/api/v1/requests/preview-modify",
        "/api/v1/requests/preview-save",
        "/api/v1/mikan/candidates",
        "/api/v1/preferences",
        "/api/v1/corrections",
        "/api/v1/batches/parse",
        "/api/v1/qbittorrent/test-connection",
        "/api/v1/autobangumi/test-connection",
    ):
        assert f'"{url}"' in script, f"app.js must call {url}"

    # Dynamic URL prefixes built with string concatenation.
    for fragment in (
        '"/api/v1/requests/" + encodeURIComponent(requestId)',
        'apiPath("/api/v1/requests/" + encodeURIComponent(requestId))',
        '"/api/v1/batches/" + encodeURIComponent(currentBatchId) + "/accept"',
        'apiPath("/api/v1/batches/" + encodeURIComponent(currentBatchId) + "/queue")',
        'apiPath("/api/v1/batches/" + encodeURIComponent(currentBatchId) + "/submit")',
        'apiPath("/api/v1/batches/" + encodeURIComponent(currentBatchId) + "/retry")',
        'apiPath("/api/v1/batches/" + encodeURIComponent(currentBatchId) + "/recover")',
        'apiPath("/api/v1/requests/" + encodeURIComponent(requestId) + "/" + actionType)',
        'apiPath("/api/v1/requests/" + encodeURIComponent(requestId) + "/delete")',
        'apiPath("/api/v1/requests/" + encodeURIComponent(requestId) + "/submit-ab")',
    ):
        assert fragment in script, f"app.js must build {fragment}"

    # The frontend never embeds raw credentials into a URL or body path.
    assert "endpoint=" not in script.replace("?endpoint=", "")
    assert "http://" not in script
    assert "https://" not in script


def test_fetch_json_handles_the_shared_envelope(client: FlaskClient) -> None:
    """fetchJson consumes the frozen {ok, result}/{ok, error_*} envelope."""
    script = _script(client)
    fetch_start = script.index("async function fetchJson")
    fetch_end = script.index("function setQbittorrentFormError")
    fetch_json = script[fetch_start:fetch_end]

    assert "await response.json()" in fetch_json
    assert "if (!payload.ok)" in fetch_json
    assert "error.errorType = payload.error_type || \"request_error\"" in fetch_json
    assert "error.errorData = payload.error_data || null" in fetch_json
    assert "return payload.result" in fetch_json
    assert "response.status" not in fetch_json.split("await response.json()")[0]


def test_old_frontend_does_not_expose_secret_values(client: FlaskClient) -> None:
    script = _script(client)
    assert "secret-token" not in script
    assert "Authorization" not in script
    assert "SID=" not in script
    assert "magnet:?" not in script
    assert "<rss" not in script.lower()
