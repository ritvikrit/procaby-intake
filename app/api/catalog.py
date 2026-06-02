from collections import defaultdict
from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.catalog import CatalogueVendor, ItemsWithCategory, VendorReference

router = APIRouter()

# Reusable expression: meta_data->>'name' as a SQLAlchemy column expression
_vendor_name = VendorReference.meta_data["name"].astext


@router.get("/items")
async def get_catalog_items(db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(ItemsWithCategory).order_by(ItemsWithCategory.cat_name, ItemsWithCategory.id)
    )
    items = result.scalars().all()
    categories: dict[str, list[str]] = defaultdict(list)
    for item in items:
        key = item.cat_name or "Uncategorized"
        categories[key].append(item.item_name)
    return {"categories": dict(categories)}


@router.get("/vendors")
async def get_vendors(db: AsyncSession = Depends(get_db)):
    vendors_result = await db.execute(
        select(_vendor_name).order_by(_vendor_name)
    )
    vendors = [row[0] for row in vendors_result.all() if row[0]]

    vc_result = await db.execute(
        select(_vendor_name, ItemsWithCategory.cat_name)
        .join(CatalogueVendor, CatalogueVendor.vendor_id == VendorReference.global_vendor_id)
        .join(ItemsWithCategory, ItemsWithCategory.id == CatalogueVendor.item_id)
        .distinct()
    )
    category_map: dict[str, list[str]] = defaultdict(list)
    for vendor_name, cat_name in vc_result.all():
        if vendor_name and cat_name:
            category_map[cat_name].append(vendor_name)

    return {"vendors": vendors, "category_map": dict(category_map)}
