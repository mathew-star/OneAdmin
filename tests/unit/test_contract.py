"""The ``/schema`` description of a model, as the UI receives it (order, names)."""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker

from examples.shop.models import Customer
from oneadmin import AdminSite, ModelAdmin
from oneadmin.api.contract import model_schema
from oneadmin.core.model_admin import humanize_class_name, pluralize


def describe(admin_cls: type[ModelAdmin]) -> list[str]:
    site = AdminSite(session_factory=async_sessionmaker(), secret_key="k" * 32)
    site.register(Customer, admin_cls)
    site.build_app()
    (admin,) = site.admins()
    return model_schema(admin, {Customer: "customer"}).list_display


def test_list_display_keeps_the_written_order_with_relations_in_place() -> None:
    class CustomerAdmin(ModelAdmin):
        list_display = ("id", "tenant", "email")

    assert describe(CustomerAdmin) == ["id", "tenant", "email"]


def test_primary_key_is_prepended_when_not_listed() -> None:
    class CustomerAdmin(ModelAdmin):
        list_display = ("email", "tenant")

    assert describe(CustomerAdmin) == ["id", "email", "tenant"]


@pytest.mark.parametrize(
    ("name", "plural"),
    [
        ("Category", "Categories"),
        ("Box", "Boxes"),
        ("Address", "Addresses"),
        ("Batch", "Batches"),
        ("Day", "Days"),
        ("Order line", "Order lines"),
        ("Post", "Posts"),
    ],
)
def test_pluralize(name: str, plural: str) -> None:
    assert pluralize(name) == plural


@pytest.mark.parametrize(
    ("cls", "words"),
    [("OrderLine", "Order line"), ("HTTPLog", "HTTP log"), ("Item", "Item"), ("APIKey", "API key")],
)
def test_humanize_class_name(cls: str, words: str) -> None:
    assert humanize_class_name(cls) == words
