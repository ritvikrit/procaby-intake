"""
Run once to seed catalog_items, vendors, and vendor_categories tables.
Usage:  python seed_catalog.py
"""
import asyncio
import os
from dotenv import load_dotenv
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.dialects.postgresql import insert as pg_insert

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL not set in .env")

# ── Catalog data (migrated from ui.py) ────────────────────────────────────────

CATALOG_CATEGORIES: dict[str, list[str]] = {
    "🔩 Structural / Raw Materials": [
        "UBE RECT 25363-000",
        "TUBE RECT 25910-000",
        "PLATE CUT SHAPE 25161-000",
        "PLATE CUT SHAPE 25340-000",
        "BAR RECT FLAT170",
    ],
    "🔗 Jaw Couplings": [
        "Lovejoy L-Series Jaw Coupling - Jaw Size L090",
        "Lovejoy L-Series Jaw Coupling - Jaw Size L095",
        "Lovejoy L-Series Jaw Coupling - Jaw Size L100",
        "Lovejoy L-Series Jaw Coupling - Jaw Size L110",
        "Lovejoy L-Series Jaw Coupling - Jaw Size L150",
        "Rexnord Omega Elastomeric Coupling - Jaw Size L090",
        "Rexnord Omega Elastomeric Coupling - Jaw Size L095",
        "Rexnord Omega Elastomeric Coupling - Jaw Size L100",
        "Rexnord Omega Elastomeric Coupling - Jaw Size L110",
        "Rexnord Omega Elastomeric Coupling - Jaw Size L150",
    ],
    "⛓️ Roller Chains": [
        'Tsubaki RS Roller Chain - RS40 1/2"',
        'Tsubaki RS Roller Chain - RS50 5/8"',
        'Tsubaki RS Roller Chain - RS60 3/4"',
        'Tsubaki RS Roller Chain - RS80 1"',
        'Tsubaki RS Roller Chain - RS100 1-1/4"',
        'Renold Synergy Roller Chain - RS40 1/2"',
        'Renold Synergy Roller Chain - RS50 5/8"',
        'Renold Synergy Roller Chain - RS60 3/4"',
        'Renold Synergy Roller Chain - RS80 1"',
        'Renold Synergy Roller Chain - RS100 1-1/4"',
    ],
    "⚙️ Helical Gearboxes": [
        "SEW-Eurodrive R-Series Helical Gearbox - Ratio 5:1",
        "SEW-Eurodrive R-Series Helical Gearbox - Ratio 10:1",
        "SEW-Eurodrive R-Series Helical Gearbox - Ratio 20:1",
        "SEW-Eurodrive R-Series Helical Gearbox - Ratio 40:1",
        "SEW-Eurodrive R-Series Helical Gearbox - Ratio 60:1",
        "Nord SK Helical Gearbox - Ratio 5:1",
        "Nord SK Helical Gearbox - Ratio 10:1",
        "Nord SK Helical Gearbox - Ratio 20:1",
        "Nord SK Helical Gearbox - Ratio 40:1",
        "Nord SK Helical Gearbox - Ratio 60:1",
    ],
    "🔒 Mechanical Seals": [
        "EagleBurgmann MFL85N Seal - Shaft 35mm",
        "EagleBurgmann MFL85N Seal - Shaft 40mm",
        "EagleBurgmann MFL85N Seal - Shaft 50mm",
        "EagleBurgmann MFL85N Seal - Shaft 60mm",
        "John Crane Type 2100 Seal - Shaft 25mm",
        "John Crane Type 2100 Seal - Shaft 35mm",
        "John Crane Type 2100 Seal - Shaft 40mm",
        "John Crane Type 2100 Seal - Shaft 50mm",
        "John Crane Type 2100 Seal - Shaft 60mm",
    ],
    "🔧 Globe Valves": [
        "Samson 3241 Globe Valve - DN15 PN40",
        "Samson 3241 Globe Valve - DN25 PN40",
        "Samson 3241 Globe Valve - DN40 PN40",
        "Samson 3241 Globe Valve - DN50 PN40",
        "Samson 3241 Globe Valve - DN80 PN40",
    ],
    "💨 Pneumatic Cylinders": [
        "Festo DSBC ISO Cylinder - Ø32 x 100mm",
        "Festo DSBC ISO Cylinder - Ø40 x 100mm",
        "Festo DSBC ISO Cylinder - Ø50 x 150mm",
        "Festo DSBC ISO Cylinder - Ø63 x 200mm",
        "Festo DSBC ISO Cylinder - Ø80 x 100mm",
    ],
}

VENDORS = [
    "Manav Singh", "Vishal Arak", "Chetana", "Karan", "Sham",
    "Kailas Bhel", "Rohan", "Rishab Borade", "Rahul", "Adinath",
    "Paras Enterprises", "Rana Enterprises", "Vihan Enterprises",
    "Shantanu", "Kyc", "Ketan Automation", "Ihan", "Karishma",
    "Sakshi", "Prabhas",
]

VENDOR_CATEGORY_MAP: dict[str, list[str]] = {
    "🔩 Structural / Raw Materials": [
        "Manav Singh", "Paras Enterprises", "Rana Enterprises", "Vihan Enterprises", "Shantanu",
    ],
    "🔗 Jaw Couplings": [
        "Kailas Bhel", "Ketan Automation", "Vishal Arak", "Rohan", "Prabhas",
    ],
    "⛓️ Roller Chains": [
        "Adinath", "Sham", "Rishab Borade", "Manav Singh", "Rahul",
    ],
    "⚙️ Helical Gearboxes": [
        "Ketan Automation", "Kailas Bhel", "Rishab Borade", "Vihan Enterprises", "Chetana",
    ],
    "🔒 Mechanical Seals": [
        "Kyc", "Ihan", "Karishma", "Sakshi", "Paras Enterprises",
    ],
    "🔧 Globe Valves": [
        "Chetana", "Karan", "Rana Enterprises", "Vishal Arak", "Ihan",
    ],
    "💨 Pneumatic Cylinders": [
        "Karan", "Karishma", "Sakshi", "Rohan", "Prabhas",
    ],
}


async def seed():
    engine = create_async_engine(DATABASE_URL, echo=False)
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with session_factory() as session:
        # ── catalog_items ──────────────────────────────────────────────────────
        item_rows = [
            {"name": name, "category": category}
            for category, names in CATALOG_CATEGORIES.items()
            for name in names
        ]
        stmt = pg_insert(CatalogItemTable).values(item_rows)
        stmt = stmt.on_conflict_do_nothing(index_elements=["name"])
        await session.execute(stmt)

        # ── vendors ────────────────────────────────────────────────────────────
        vendor_rows = [{"name": v} for v in VENDORS]
        stmt = pg_insert(VendorTable).values(vendor_rows)
        stmt = stmt.on_conflict_do_nothing(index_elements=["name"])
        await session.execute(stmt)

        # ── vendor_categories ──────────────────────────────────────────────────
        vc_rows = [
            {"vendor_name": vendor, "category": category}
            for category, vendors in VENDOR_CATEGORY_MAP.items()
            for vendor in vendors
        ]
        stmt = pg_insert(VendorCategoryTable).values(vc_rows)
        stmt = stmt.on_conflict_do_nothing(constraint="uq_vendor_category")
        await session.execute(stmt)

        await session.commit()

    await engine.dispose()
    print(f"Seeded {len(item_rows)} catalog items, {len(vendor_rows)} vendors, {len(vc_rows)} vendor-category mappings.")


# ── Table references (avoid importing app models to keep script self-contained) ─

from sqlalchemy import Table, Column, Integer, String, MetaData, UniqueConstraint

_meta = MetaData()

CatalogItemTable = Table(
    "catalog_items", _meta,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("name", String(500), nullable=False, unique=True),
    Column("category", String(255), nullable=False),
)

VendorTable = Table(
    "vendors", _meta,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("name", String(500), nullable=False, unique=True),
)

VendorCategoryTable = Table(
    "vendor_categories", _meta,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("vendor_name", String(500), nullable=False),
    Column("category", String(255), nullable=False),
    UniqueConstraint("vendor_name", "category", name="uq_vendor_category"),
)


if __name__ == "__main__":
    asyncio.run(seed())
