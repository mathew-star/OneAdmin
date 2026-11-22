"""OneAdmin: fast, secure, async admin panel for FastAPI + SQLAlchemy 2.

Only names listed in ``__all__`` are public API; everything else may change without notice.
"""

from oneadmin.__about__ import __version__
from oneadmin.auth.backend import AdminIdentity, AuthBackend
from oneadmin.core.actions import action
from oneadmin.core.context import AdminContext
from oneadmin.core.errors import ConfigurationError, OneAdminError, ValidationError
from oneadmin.core.model_admin import ModelAdmin
from oneadmin.site import AdminSite

__all__ = [
    "AdminContext",
    "AdminIdentity",
    "AdminSite",
    "AuthBackend",
    "ConfigurationError",
    "ModelAdmin",
    "OneAdminError",
    "ValidationError",
    "__version__",
    "action",
]
