"""Tracking domain engine (Stage 29 B-B).

Owns the unified tracking-record lifecycle: deterministic ``tracking_id``
generation, the ``TrackingRecord`` contract, and (in later stories) the
revalidate/submit/retry/recover orchestration shared by every submission
entry point. Durable JSON persistence lives in
``storage_engine.controllers.tracking_repository`` so the domain model never
depends on storage details.
"""
