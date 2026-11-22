"""Framework-agnostic core: metadata, query engine, validation, services.

Layering rule (enforced by tests/unit/test_layering.py): nothing under ``oneadmin.core``
may import fastapi, starlette, or ``oneadmin.api`` / ``oneadmin.ui`` / ``oneadmin.cli``.
"""
