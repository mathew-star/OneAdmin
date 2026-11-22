"""The configuration compiler: typed options, conventions, precedence and provenance."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker

from examples.shop.models import Customer, Order, Product
from oneadmin import AdminSite, ConfigurationError, ModelAdmin
from oneadmin import conventions as cv
from oneadmin.core.compiler import CompiledAdmin
from oneadmin.fields import EmailField, MoneyField, URLField
from tests.models import Item, Staff


def compile_one(
    model: type[Any], admin_cls: type[ModelAdmin] = ModelAdmin, *conventions: cv.Convention
) -> CompiledAdmin:
    site = AdminSite(
        session_factory=async_sessionmaker(), secret_key="k" * 32, conventions=conventions
    )
    site.register(model, admin_cls)
    site.build_app()
    return site.admins()[0].compiled


# ---- typed options -------------------------------------------------------------------------
def test_attributes_work_wherever_names_do() -> None:
    class OrderAdmin(ModelAdmin[Order]):
        list_display = (Order.id, Order.status, Order.customer)
        list_filter = (Order.status,)
        search_fields = ("=id", Order.notes)
        ordering = (Order.created_at.desc(), Order.id)
        readonly_fields = (Order.created_at,)
        labels = {Order.total: "Amount"}
        field_types = {Order.total: MoneyField("EUR")}

    c = compile_one(Order, OrderAdmin)
    assert c.list_display == ("id", "status", "customer")
    assert c.filter_fields == ("status",)
    assert [sf.field.name for sf in c.search] == ["id", "notes"]
    assert c.default_sort == ("-created_at", "id")
    assert "created_at" not in c.write.fields
    assert c.labels["total"] == "Amount"
    assert c.meta.fields["total"].field_type == MoneyField("EUR")


def test_attributes_of_another_model_are_rejected() -> None:
    class Wrong(ModelAdmin):
        list_display = (Customer.email,)

    with pytest.raises(ConfigurationError, match=r"Customer\.email belongs to another model"):
        compile_one(Order, Wrong)


def test_a_missing_comma_is_explained() -> None:
    class Oops(ModelAdmin):
        list_filter = "status"  # a str is a Sequence[str], so only the runtime check catches it

    with pytest.raises(ConfigurationError, match="did you forget a comma"):
        compile_one(Order, Oops)


def test_incompatible_field_types_are_rejected() -> None:
    class Bad(ModelAdmin):
        field_types = {Order.status: EmailField()}

    with pytest.raises(ConfigurationError, match="'status' is a enum column"):
        compile_one(Order, Bad)


# ---- conventions ---------------------------------------------------------------------------
def test_conventions_apply_to_every_matching_field() -> None:
    c = compile_one(
        Customer,
        ModelAdmin,
        cv.readonly(r".*_at", id="timestamps"),
        cv.field_type(EmailField(), r"email"),
        cv.label("Signed up", "created_at"),
        cv.filterable(kind="string"),
    )
    assert "created_at" not in c.write.fields
    assert c.meta.fields["email"].field_type == EmailField()
    assert c.labels["created_at"] == "Signed up"
    assert set(c.filter_allowed) == {"email", "full_name"}


def test_admin_options_win_over_conventions() -> None:
    class CustomerAdmin(ModelAdmin):
        field_types = {"email": URLField()}  # an explicit (if odd) choice
        labels = {"created_at": "Joined"}

    c = compile_one(
        Customer,
        CustomerAdmin,
        cv.field_type(EmailField(), "email"),
        cv.label("Signed up", "created_at"),
    )
    assert c.meta.fields["email"].field_type == URLField()
    assert c.labels["created_at"] == "Joined"


def test_later_conventions_win_over_earlier_ones() -> None:
    first, second = cv.label("A", "email"), cv.label("B", "email")
    assert (first.id, second.id) == ("label('A', 'email')", "label('B', 'email')")
    c = compile_one(Customer, ModelAdmin, first, second)
    assert c.labels["email"] == "B"


def test_an_admin_can_ignore_a_convention_by_id() -> None:
    class CustomerAdmin(ModelAdmin):
        ignore_conventions = ("timestamps",)

    c = compile_one(Customer, CustomerAdmin, cv.readonly(r".*_at", id="timestamps"))
    assert "created_at" in c.write.fields


def test_ignoring_an_unknown_convention_is_an_error() -> None:
    class CustomerAdmin(ModelAdmin):
        ignore_conventions = ("timestamp",)

    with pytest.raises(ConfigurationError, match=r"no convention with id \['timestamp'\]"):
        compile_one(Customer, CustomerAdmin, cv.readonly(r".*_at", id="timestamps"))


def test_conventions_need_criteria_and_unique_ids() -> None:
    with pytest.raises(ConfigurationError, match="at least one of name="):
        cv.readonly()
    with pytest.raises(ConfigurationError, match="invalid name pattern"):
        cv.hide("(")
    with pytest.raises(ConfigurationError, match="share the id"):
        AdminSite(
            session_factory=async_sessionmaker(),
            secret_key="k" * 32,
            conventions=[cv.hide("x", id="a"), cv.readonly("y", id="a")],
        )


def test_hide_convention_and_an_explicit_fields_list() -> None:
    c = compile_one(Product, ModelAdmin, cv.hide("description"))
    assert "description" not in {f.name for f in c.detail_fields}

    class ProductAdmin(ModelAdmin):
        fields = ("id", "name", "description")

    c = compile_one(Product, ProductAdmin, cv.hide("description"))
    assert [f.name for f in c.detail_fields] == ["id", "name", "description"]


def test_filterable_convention_skips_unfilterable_types() -> None:
    c = compile_one(Product, ModelAdmin, cv.filterable(kind=("json", "string")))
    assert "attributes" not in c.filter_allowed
    assert "sku" in c.filter_allowed


# ---- provenance ----------------------------------------------------------------------------
def test_every_decision_records_its_origin() -> None:
    class ItemAdmin(ModelAdmin):
        readonly_fields = ("name",)

    rule = cv.readonly("amount", id="money-is-readonly")
    c = compile_one(Item, ItemAdmin, rule)
    p = {k: str(v) for k, v in c.provenance.items()}
    assert p["field.name.readonly"] == "ItemAdmin.readonly_fields"
    assert p["field.amount.readonly"] == f"convention money-is-readonly ({rule.declared_at})"
    assert rule.declared_at.endswith(f"test_compiler.py:{_line_of('money-is-readonly')}")
    assert p["field.doubled.readonly"] == "model: generated by the database"
    assert p["field.grp.readonly"] == "default"
    assert p["field.amount.type"] == "default (from the column's SQL type)"
    assert p["ordering"] == "default (newest primary key first)"


def test_hidden_field_errors_say_why() -> None:
    class StaffAdmin(ModelAdmin):
        list_display = ("id", "api_token")

    with pytest.raises(ConfigurationError, match=r"'api_token' is hidden \(default \(credential"):
        compile_one(Staff, StaffAdmin)


def _line_of(marker: str) -> int:
    lines = Path(__file__).read_text(encoding="utf-8").splitlines()
    return next(i for i, line in enumerate(lines, 1) if f'id="{marker}"' in line)
