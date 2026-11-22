"""The demo shop's tables: customers, categories, products and orders."""

from __future__ import annotations

import enum
from datetime import datetime
from decimal import Decimal

from sqlalchemy import Enum, ForeignKey, Index, Numeric, String
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class OrderStatus(enum.Enum):
    NEW = "new"
    PAID = "paid"
    SHIPPED = "shipped"
    CANCELLED = "cancelled"


class Customer(Base):
    __tablename__ = "demo_customer"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120), index=True)
    email: Mapped[str] = mapped_column(String(200), unique=True)
    country: Mapped[str] = mapped_column(String(2), index=True)
    is_vip: Mapped[bool] = mapped_column(index=True)
    created_at: Mapped[datetime] = mapped_column(index=True)


class Category(Base):
    __tablename__ = "demo_category"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(80), unique=True)


class Product(Base):
    __tablename__ = "demo_product"
    id: Mapped[int] = mapped_column(primary_key=True)
    sku: Mapped[str] = mapped_column(String(20), unique=True)
    name: Mapped[str] = mapped_column(String(160), index=True)
    price: Mapped[Decimal] = mapped_column(Numeric(10, 2), index=True)
    active: Mapped[bool] = mapped_column(index=True)
    category_id: Mapped[int] = mapped_column(ForeignKey("demo_category.id"), index=True)
    category: Mapped[Category] = relationship()


class Order(Base):
    __tablename__ = "demo_order"
    __table_args__ = (
        Index("ix_demo_order_created_id", "created_at", "id"),
        Index("ix_demo_order_total_id", "total", "id"),
        Index("ix_demo_order_status_created", "status", "created_at", "id"),
        Index("ix_demo_order_status_total", "status", "total", "id"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    customer_id: Mapped[int] = mapped_column(ForeignKey("demo_customer.id"), index=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("demo_product.id"), index=True)
    quantity: Mapped[int]
    status: Mapped[OrderStatus] = mapped_column(
        Enum(OrderStatus, name="demo_order_status", values_callable=lambda e: [m.value for m in e])
    )
    total: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    created_at: Mapped[datetime]
    note: Mapped[str | None] = mapped_column(String(200))

    customer: Mapped[Customer] = relationship()
    product: Mapped[Product] = relationship()
