from __future__ import annotations

"""Subscription-plan generation seam (issue #174).

This package owns the "build a real subscription plan" use case that used to
live inside the CLI app controller:

- `controllers/data_sources.py` — the `PlanDataSource` port plus the two
  adapters (real MiKan / static fixture);
- `controllers/plan_generation.py` — `build_plan`, the CLI-free generation
  entry;
- `controllers/plan_actions.py` — confirmation / modify / save actions shared
  by the Web API and the CLI.

`apps.migu_orca_entry` keeps a thin compatibility shell for the historical CLI
signature; the Web API and all fixtures import this package directly.
"""
