"""``register_all`` and the shared suggestion heuristics."""

from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy import ForeignKey, String
from sqlalchemy.ext.asyncio import async_sessionmaker
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from examples.shop.models import Base as ShopBase
from examples.shop.models import Customer, Order, Product
from oneadmin import AdminSite, ConfigurationError, ModelAdmin
from oneadmin.core.autoconfig import suggest


def site() -> AdminSite:
    return AdminSite(session_factory=async_sessionmaker(), secret_key="k" * 32)


def test_suggestions_for_an_order() -> None:
    s = suggest(Order)
    assert s.list_display[:2] == ("id", "customer"), "FK shown as its relationship"
    assert "customer_id" not in s.list_display
    assert len(s.list_display) <= 7
    assert s.list_filter == ("status", "created_at", "shipped_at")
    assert s.ordering == ("-created_at",)


def test_suggestions_search_identifier_like_text_only() -> None:
    assert suggest(Customer).search_fields == ("email", "full_name")
    assert suggest(Product).search_fields == ("^sku", "name")


def test_register_all_registers_every_model_and_compiles() -> None:
    s = site()
    added = s.register_all(ShopBase)
    s.build_app()
    slugs = {a.compiled.slug for a in s.admins()}
    assert {"customer", "order", "product", "tenant", "category"} <= slugs
    assert len(added) == len(s.admins())
    order = s.admin_by_slug("order")
    assert order is not None
    assert order.compiled.filter_fields == ("status", "created_at", "shipped_at")


@pytest.mark.parametrize("explicit_first", [True, False])
def test_explicit_registrations_win_in_any_order(explicit_first: bool) -> None:
    class OrderAdmin(ModelAdmin):
        list_display = ("id", "total")

    s = site()
    if explicit_first:
        s.register(Order, OrderAdmin)
        s.register_all(ShopBase)
    else:
        s.register_all(ShopBase)
        s.register(Order, OrderAdmin)
    s.build_app()
    order = s.admin_by_slug("order")
    assert isinstance(order, OrderAdmin)
    assert order.compiled.list_display == ("id", "total")


def test_exclude_and_a_custom_base_class() -> None:
    class Base(ModelAdmin):
        list_per_page = 20
        list_filter = ()  # explicit on the base: wins over suggestions

    s = site()
    s.register_all(ShopBase, exclude=[Customer], admin_class=Base)
    s.build_app()
    assert s.admin_by_slug("customer") is None
    order = s.admin_by_slug("order")
    assert order is not None
    assert order.list_per_page == 20
    assert order.compiled.filter_fields == ()


class _B(DeclarativeBase):
    pass


class _Animal(_B):
    __tablename__ = "ra_animal"
    id: Mapped[int] = mapped_column(primary_key=True)
    kind: Mapped[str] = mapped_column(String(20))
    name: Mapped[str] = mapped_column(String(50))
    __mapper_args__: Any = {"polymorphic_on": "kind", "polymorphic_identity": "animal"}


class _Dog(_Animal):  # single-table inheritance: same table
    __mapper_args__: Any = {"polymorphic_identity": "dog"}


class _Owner(_B):
    __tablename__ = "ra_owner"
    id: Mapped[int] = mapped_column(primary_key=True)
    pet_id: Mapped[int] = mapped_column(ForeignKey("ra_animal.id"))
    pet: Mapped[_Animal] = relationship()


def test_single_table_subclasses_are_skipped() -> None:
    s = site()
    assert set(s.register_all(_B)) == {_Animal, _Owner}
    s.build_app()


def test_register_all_needs_mapped_classes() -> None:
    with pytest.raises(ConfigurationError, match="not a mapped class"):
        site().register_all(["nope"])
