"""Tracking domain pure controllers (Stage 29 B-B).

Controllers orchestrate tracking domain models without depending on storage
details; durable persistence is injected by the caller.  ``migration`` owns the
pure historical-backfill classification used by the migration runner.
"""
