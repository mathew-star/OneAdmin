"""The demo's admin: a compact tour of conventions, typed options, field types and actions."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from oneadmin import AdminContext, AdminSite, ModelAdmin, action
from oneadmin import conventions as cv
from oneadmin.demo.models import Category, Customer, Order, OrderStatus, Product
from oneadmin.fields import EmailField, MoneyField


def build_site(session_factory: async_sessionmaker[AsyncSession]) -> AdminSite:
    admin = AdminSite(
        title="OneAdmin demo shop",
        session_factory=session_factory,
        dev=True,  # local only, no secret key needed
        conventions=[
            cv.field_type(EmailField(), "email"),
            cv.readonly("created_at", id="timestamps"),
            cv.filterable(kind=("boolean", "enum"), id="choice-filters"),
        ],
    )

    @admin.register(Order)
    class OrderAdmin(ModelAdmin[Order]):
        list_display = (Order.id, Order.customer, Order.product, Order.quantity,
                        Order.status, Order.total, Order.created_at)  # fmt: skip
        list_filter = (Order.created_at, Order.total)
        search_fields = ("=id",)
        ordering = (Order.created_at.desc(),)
        sortable_fields = (Order.id, Order.created_at, Order.total)
        field_types = {Order.total: MoneyField("EUR")}

        @action(label="Mark shipped", confirm="Mark the selected orders as shipped?")
        async def mark_shipped(self, ctx: AdminContext, rows: list[Order]) -> str:
            for order in rows:
                order.status = OrderStatus.SHIPPED
            return f"{len(rows)} order(s) marked shipped."

    @admin.register(Customer)
    class CustomerAdmin(ModelAdmin[Customer]):
        list_display = (Customer.id, Customer.name, Customer.email, Customer.country,
                        Customer.is_vip, Customer.created_at)  # fmt: skip
        list_filter = (Customer.country,)
        search_fields = (Customer.name, "^email")
        ordering = (Customer.name,)

    @admin.register(Product)
    class ProductAdmin(ModelAdmin[Product]):
        list_display = (Product.id, Product.sku, Product.name, Product.category,
                        Product.price, Product.active)  # fmt: skip
        list_filter = (Product.category_id, Product.price)
        search_fields = ("^sku", Product.name)
        ordering = (Product.name,)
        field_types = {Product.price: MoneyField("EUR")}

    admin.register(Category)
    return admin
