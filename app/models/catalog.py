from sqlalchemy import String, Integer, Float
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from app.database import Base


class CatalogItem(Base):
    __tablename__ = "item"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    uuid: Mapped[str | None] = mapped_column(String(255), nullable=True)
    category_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    sub_category_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    item_code: Mapped[str | None] = mapped_column(String(255), nullable=True)
    item_name: Mapped[str] = mapped_column(String(500), nullable=False)
    description: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    sku: Mapped[str | None] = mapped_column(String(255), nullable=True)
    cost_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    selling_price: Mapped[float | None] = mapped_column(Float, nullable=True)


class Catalogue(Base):
    __tablename__ = "catalogue"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    uuid: Mapped[str | None] = mapped_column(String(255), nullable=True)
    req_catalogue_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    item_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    variant_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[str | None] = mapped_column(String(100), nullable=True)


class CatalogueVendor(Base):
    __tablename__ = "catalogue_vendor"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    uuid: Mapped[str | None] = mapped_column(String(255), nullable=True)
    vendor_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    catalogue_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    item_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    variant_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    stock: Mapped[float | None] = mapped_column(Float, nullable=True)
    price: Mapped[float | None] = mapped_column(Float, nullable=True)


class ItemsWithCategory(Base):
    __tablename__ = "items_with_category"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    item_name: Mapped[str] = mapped_column(String(500), nullable=False)
    cat_name: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)


class VendorReference(Base):
    __tablename__ = "vendor_references"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tenant_vendor_code: Mapped[str | None] = mapped_column(String(255), nullable=True)
    meta_data: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
