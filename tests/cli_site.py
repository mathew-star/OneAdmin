"""An ``AdminSite`` for CLI tests, loaded by ``oneadmin --app tests.cli_site:site``."""

from __future__ import annotations

import os
from typing import Any

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from oneadmin import AdminContext, AdminSite, ModelAdmin, action
from tests.models import Item

engine = create_async_engine(os.environ["ONEADMIN_TEST_CLI_URL"])
site = AdminSite(
    session_factory=async_sessionmaker(engine), secret_key="cli-test-secret-" + "c" * 32
)


@site.register(Item)
class ItemAdmin(ModelAdmin):
    list_display = ("id", "name", "grp", "amount")
    ordering = ("-grp",)
    list_filter = ("name",)

    @action(permission="custom")
    async def archive(self, ctx: AdminContext, rows: list[Any]) -> None:
        """Only for the codename listing: ``qe_item.action.archive``."""
