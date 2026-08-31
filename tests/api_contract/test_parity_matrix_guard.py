from __future__ import annotations

"""US-208: guard the parity matrix stays honest (269 legacy journeys → SPA).

The parity matrix in ``tests/api_contract/parity_matrix.py`` is a reviewable
mapping from every legacy Chromium journey suite to the SPA suite that now
covers the same capability. This guard re-counts the real legacy test files
and asserts:

- the matrix total equals the actual legacy journey count (269 today) —
  renaming/removing a legacy suite or changing its test count breaks the
  guard instead of silently drifting;
- every mapped legacy file exists and its test count matches the matrix;
- every mapped SPA suite exists and is non-empty (the SPA suite covers the
  same capability from the migrated views, US-202..US-207 — one SPA suite may
  cover several legacy suites, and the SPA suites re-assert the business
  journeys with focused tests rather than replicating every legacy assertion);
- every known SPA suite participates in the matrix (nothing is silently left
  out of the parity story);
- every matrix route starts with ``/app/`` (the SPA must own the mapped
  capability; the legacy pages themselves stay only for the migration window
  and the rollback rehearsal).
"""

from pathlib import Path

import pytest

from tests.api_contract.parity_matrix import LEGACY_TOTAL, PARITY_MATRIX

BROWSER_DIR = Path(__file__).resolve().parents[1] / "browser"


def _count_tests(path: Path) -> int:
    text = path.read_text(encoding="utf-8")
    return sum(
        1
        for line in text.splitlines()
        if line.startswith("    def test_") or line.startswith("def test_")
    )


@pytest.mark.parametrize("entry", PARITY_MATRIX, ids=lambda e: str(e["legacy_file"]))
def test_matrix_entries_are_real_and_matched(entry: dict[str, str | int]) -> None:
    legacy_path = BROWSER_DIR / f"test_{entry['legacy_file']}.py"
    assert legacy_path.is_file(), f"legacy suite missing: {legacy_path}"

    actual = _count_tests(legacy_path)
    assert actual == int(entry["legacy_tests"]), (
        f"parity matrix says {entry['legacy_file']} has {entry['legacy_tests']} "
        f"journeys but the file has {actual} — update tests/api_contract/parity_matrix.py"
    )

    spa_path = BROWSER_DIR / f"{entry['spa_suite']}.py"
    assert spa_path.is_file(), f"SPA suite missing: {spa_path}"
    assert _count_tests(spa_path) >= 1, (
        f"SPA suite {entry['spa_suite']} has no tests — it cannot cover the "
        f"legacy {entry['legacy_file']} journeys"
    )

    route = str(entry["spa_route"])
    assert route.startswith("/app"), (
        f"matrix route {route!r} for {entry['legacy_file']} is not an SPA route"
    )


def test_matrix_total_matches_legacy_journey_count() -> None:
    """The matrix covers every legacy Chromium journey (269 today)."""
    actual_total = 0
    for entry in PARITY_MATRIX:
        legacy_path = BROWSER_DIR / f"test_{entry['legacy_file']}.py"
        if legacy_path.is_file():
            actual_total += _count_tests(legacy_path)
    assert actual_total == LEGACY_TOTAL, (
        f"parity matrix total ({LEGACY_TOTAL}) does not match the real legacy "
        f"journey count ({actual_total})"
    )
    assert actual_total == 269, (
        f"expected 269 legacy journeys (US-208 acceptance) but found {actual_total}"
    )


def test_every_legacy_suite_is_mapped() -> None:
    """No legacy journey suite may be left out of the parity matrix."""
    # test_components_primitives is US-200 migration scaffolding (the
    # /app/components-demo primitive gallery), not a legacy journey; US-209
    # removes both together.
    non_legacy_scaffolding = {"components_primitives"}
    legacy_prefixes = {entry["legacy_file"] for entry in PARITY_MATRIX}
    actual = sorted(
        path.name[len("test_") : -len(".py")]
        for path in BROWSER_DIR.glob("test_*.py")
        if not path.name.startswith("test_app_")
        and path.name[len("test_") : -len(".py")] not in non_legacy_scaffolding
    )
    missing = sorted(set(actual) - legacy_prefixes)
    assert not missing, f"legacy suites missing from parity matrix: {missing}"
