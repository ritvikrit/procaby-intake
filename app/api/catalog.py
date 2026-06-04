from collections import defaultdict
from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.catalog import CatalogueVendor, ItemsWithCategory, VendorReference

router = APIRouter()

_vendor_name = VendorReference.meta_data["name"].astext


@router.get("/items")
async def get_catalog_items(db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(ItemsWithCategory).order_by(ItemsWithCategory.cat_name, ItemsWithCategory.id)
    )
    items = result.scalars().all()
    categories: dict[str, list[str]] = defaultdict(list)
    item_ids: dict[str, int] = {}
    for item in items:
        key = item.cat_name or "Uncategorized"
        categories[key].append(item.item_name)
        item_ids[item.item_name] = item.id
    return {"categories": dict(categories), "item_ids": item_ids}


@router.get("/vendors")
async def get_vendors(db: AsyncSession = Depends(get_db)):
    vendors_result = await db.execute(
        select(VendorReference.global_vendor_id, _vendor_name).order_by(_vendor_name)
    )
    rows = vendors_result.all()
    vendors = [row[1] for row in rows if row[1]]
    vendor_ids = {row[1]: row[0] for row in rows if row[1] and row[0]}

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

    return {"vendors": vendors, "category_map": dict(category_map), "vendor_ids": vendor_ids}
