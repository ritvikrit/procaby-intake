import re
import sqlite3
import httpx
import chainlit as cl
from chainlit.data.sql_alchemy import SQLAlchemyDataLayer
from datetime import date, timedelta

# ── SQLite history DB ─────────────────────────────────────────────────────────

_SQLITE_DB = "./chainlit_history.db"


def _init_db() -> None:
    """Create Chainlit history tables if they don't exist."""
    con = sqlite3.connect(_SQLITE_DB)
    cur = con.cursor()
    cur.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            id         TEXT PRIMARY KEY,
            identifier TEXT UNIQUE NOT NULL,
            "createdAt" TEXT,
            metadata   TEXT
        );
        CREATE TABLE IF NOT EXISTS threads (
            id               TEXT PRIMARY KEY,
            name             TEXT,
            "userId"         TEXT,
            "userIdentifier" TEXT,
            tags             TEXT,
            metadata         TEXT,
            "createdAt"      TEXT
        );
        CREATE TABLE IF NOT EXISTS steps (
            id              TEXT PRIMARY KEY,
            name            TEXT,
            type            TEXT,
            "threadId"      TEXT NOT NULL,
            "parentId"      TEXT,
            streaming       INTEGER DEFAULT 0,
            "waitForAnswer" INTEGER,
            "isError"       INTEGER,
            metadata        TEXT,
            tags            TEXT,
            input           TEXT,
            output          TEXT,
            "createdAt"     TEXT,
            start           TEXT,
            "end"           TEXT,
            generation      TEXT,
            language        TEXT,
            indent          INTEGER,
            "showInput"     TEXT,
            "defaultOpen"   INTEGER DEFAULT 0,
            "autoCollapse"  INTEGER DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS elements (
            id               TEXT PRIMARY KEY,
            "threadId"       TEXT,
            type             TEXT,
            url              TEXT,
            "chainlitKey"    TEXT,
            name             TEXT,
            display          TEXT,
            "objectKey"      TEXT,
            size             TEXT,
            language         TEXT,
            page             INTEGER,
            "autoPlay"       INTEGER,
            "playerConfig"   TEXT,
            "forId"          TEXT,
            mime             TEXT,
            props            TEXT
        );
        CREATE TABLE IF NOT EXISTS feedbacks (
            id         TEXT PRIMARY KEY,
            "forId"    TEXT,
            "threadId" TEXT,
            value      INTEGER,
            comment    TEXT
        );
    """)
    con.commit()

    # Migrate existing DB files that predate newer Chainlit column additions
    for migration in [
        'ALTER TABLE steps ADD COLUMN "defaultOpen" INTEGER DEFAULT 0',
        'ALTER TABLE steps ADD COLUMN "autoCollapse" INTEGER DEFAULT 0',
        'ALTER TABLE elements ADD COLUMN props TEXT',
    ]:
        try:
            cur.execute(migration)
        except sqlite3.OperationalError:
            pass  # column already exists
    con.commit()
    con.close()


_init_db()


@cl.data_layer
def _get_data_layer() -> SQLAlchemyDataLayer:
    return SQLAlchemyDataLayer(conninfo=f"sqlite+aiosqlite:///{_SQLITE_DB}")

BASE_URL = "http://localhost:8000/api/v1"

ENTITY        = "Katalyst Technologies"
REQUESTOR_ID  = "AD00076"
TODAY         = date(2026, 5, 28)
REQUEST_DATE  = "28-05-2026"

# ── Pre-loaded form values (not asked) ────────────────────────────────────────
# "location" is now asked from the user — removed from PRELOADED

PRELOADED = {
    "department":     "Engineering",
    "email":          "rahul.devakar@katalyst.com",
    "phone":          "+91 98765 43210",
    "purchase_type":  "Hardware",
    "priority":       "Medium",
    "reason":         "Operational procurement requirement",
    "completion_date": (TODAY + timedelta(days=30)).strftime("%d-%m-%Y"),
}

# ── Catalog cache (populated from DB on first chat start) ─────────────────────

_catalog: dict = {
    "categories": {},      # {category: [item, ...]}
    "flat": [],            # [item, ...]
    "vendors": [],         # [vendor_name, ...]
    "vendor_category_map": {},  # {category: [vendor_name, ...]}
}


async def _load_catalog() -> None:
    """Fetch catalog and vendor data from the backend API (once per process)."""
    if _catalog["flat"]:
        return
    try:
        async with httpx.AsyncClient() as client:
            items_resp   = await client.get(f"{BASE_URL}/catalog/items",   timeout=10.0)
            vendors_resp = await client.get(f"{BASE_URL}/catalog/vendors", timeout=10.0)
            items_resp.raise_for_status()
            vendors_resp.raise_for_status()
        items_data   = items_resp.json()
        vendors_data = vendors_resp.json()
        _catalog["categories"]         = items_data.get("categories", {})
        _catalog["flat"]               = [i for lst in _catalog["categories"].values() for i in lst]
        _catalog["vendors"]            = vendors_data.get("vendors", [])
        _catalog["vendor_category_map"] = vendors_data.get("category_map", {})
    except Exception as exc:
        # Non-fatal: fall back to empty catalog so the UI still starts
        print(f"[catalog] WARNING: could not load catalog from API — {exc}")


# ── Helpers ───────────────────────────────────────────────────────────────────

def get_item_category(item_name: str) -> str | None:
    for cat, items in _catalog["categories"].items():
        if item_name in items:
            return cat
    return None


def get_filtered_vendors(line_items: list[dict]) -> list[str]:
    categories = {get_item_category(i["name"]) for i in line_items} - {None}
    all_vendors = _catalog["vendors"]
    if not categories:
        return all_vendors
    vendor_set: set[str] = set()
    for cat in categories:
        vendor_set.update(_catalog["vendor_category_map"].get(cat, []))
    result = [v for v in all_vendors if v in vendor_set]
    return result if result else all_vendors


def search_catalog(keyword: str) -> list[str]:
    kl = keyword.lower()
    words = kl.split()
    return [item for item in _catalog["flat"] if all(w in item.lower() for w in words)]


def fmt_inr(amount: float) -> str:
    return f"₹{amount:,.2f}"


def running_total(items: list) -> float:
    return sum(i["qty"] * i["price"] for i in items)


def parse_qty_price(text: str) -> tuple[int, float] | None:
    t = text.strip()
    qm = re.search(r"(?:qty|quantity|q)[:\s]+(\d+)", t, re.I)
    pm = re.search(r"(?:price|cost|rate|p)[:\s]+[$₹]?\s*([\d,\.]+)", t, re.I)
    if qm and pm:
        return int(qm.group(1)), float(pm.group(1).replace(",", ""))
    m = re.match(r"(\d+)\s*(?:units?|pcs?|pieces?|nos?)?\s*(?:at|@|x|for)\s*[$₹]?\s*([\d,\.]+)", t, re.I)
    if m:
        return int(m.group(1)), float(m.group(2).replace(",", ""))
    m = re.match(r"(\d+)[,\s]+[$₹]?\s*([\d,\.]+)", t)
    if m:
        return int(m.group(1)), float(m.group(2).replace(",", ""))
    return None


def resolve_vendors(text: str, vendor_list: list[str]) -> list[str]:
    t = text.strip()
    if t.lower() in ("none", "no", "n/a", "-", "nope", "nil"):
        return []
    parts = [p.strip() for p in re.split(r"[,;&]", t) if p.strip()]
    result: list[str] = []
    for part in parts:
        if re.match(r"^\d+$", part):
            idx = int(part) - 1
            if 0 <= idx < len(vendor_list):
                result.append(vendor_list[idx])
        else:
            pl = part.lower()
            match = next((v for v in vendor_list if v.lower() == pl or pl in v.lower()), part)
            result.append(match)
    return result


# ── Display builders ──────────────────────────────────────────────────────────

def _build_filtered_catalog(matches: list[str], keyword: str) -> str:
    lines = [
        f"Here are the items matching **\"{keyword}\"** — "
        "type the **number** to select:\n"
    ]
    for i, item in enumerate(matches, 1):
        lines.append(f"`{i:>2}` {item}")
    return "\n".join(lines)


def _build_vendor_prompt(vendor_list: list[str]) -> str:
    lines = [
        "Here are the vendors dealing in your selected products. "
        "Type one or more **numbers or names** (comma-separated), or say **None**.\n"
    ]
    for i, v in enumerate(vendor_list, 1):
        lines.append(f"`{i:>2}` {v}")
    return "\n".join(lines)


def _selected_items_summary(data: dict) -> str:
    items = data.get("pending_items", [])
    if not items:
        return ""
    return "\n".join(f"  • {item}" for item in items)


# ── Session helper ─────────────────────────────────────────────────────────────

def _save(data: dict, next_step: str):
    cl.user_session.set("data", data)
    cl.user_session.set("step", next_step)


async def say(text: str):
    await cl.Message(content=text).send()


# ── Step handlers ──────────────────────────────────────────────────────────────

async def handle_name(text: str, data: dict):
    if len(text.strip()) < 2:
        await say("Could you share your full name?")
        return
    data["requestor_name"] = text.strip().title()

    if data.get("edit_mode"):
        data["edit_mode"] = False
        _save(data, "complete")
        await say(f"✓ Name updated to **{data['requestor_name']}**.")
        await _show_final_summary(data)
        return

    _save(data, "location")
    await say(
        f"Welcome, **{data['requestor_name']}**!\n\n"
        "What is your **location / site**? *(e.g., Mumbai, Delhi, Pune)*"
    )


async def handle_location(text: str, data: dict):
    if len(text.strip()) < 2:
        await say("Please enter your location (e.g., Mumbai, Delhi, Pune).")
        return
    data["location"] = text.strip().title()

    if data.get("edit_mode"):
        data["edit_mode"] = False
        _save(data, "complete")
        await say(f"✓ Location updated to **{data['location']}**.")
        await _show_final_summary(data)
        return

    _save(data, "product_search")
    await say(
        f"Got it — **{data['location']}**.\n\n"
        "What product or component are you looking for? "
        "*(Type a keyword — e.g., \"jaw coupling\", \"roller chain\", \"seal\")*"
    )


async def handle_product_search(text: str, data: dict):
    keyword = text.strip()
    if len(keyword) < 2:
        await say("Please enter a keyword to search for a product.")
        return

    matches = search_catalog(keyword)

    if not matches:
        await say(
            f"No items found for **\"{keyword}\"**. Try a different keyword.\n\n"
            "*Hint: try terms like `coupling`, `chain`, `gearbox`, `seal`, `valve`, `cylinder`, `tube`, `plate`*"
        )
        return

    data["filtered_items"] = matches
    data["last_keyword"]   = keyword
    _save(data, "item_select")
    await say(_build_filtered_catalog(matches, keyword))


async def handle_item_select(text: str, data: dict):
    filtered = data.get("filtered_items", [])
    t = text.strip()

    if re.match(r"^\d+$", t):
        idx = int(t) - 1
        if 0 <= idx < len(filtered):
            item = filtered[idx]
        else:
            await say(f"Please enter a number between 1 and {len(filtered)}.")
            return
    else:
        tl = t.lower()
        item = next((i for i in filtered if tl in i.lower()), None)
        if not item:
            await say(
                "I couldn't match that to the list. "
                "Please type a number from the list above."
            )
            return

    pending: list[str] = data.get("pending_items", [])

    if len(pending) >= 10:
        await say("You've reached the maximum of 10 items. Let's proceed to pricing.")
        _save(data, "item_pricing")
        await _start_pricing(data)
        return

    if item in pending:
        await say(f"**{item}** is already in your list. Choose a different item or say **No** to proceed.")
        _save(data, "add_more")
        return

    pending.append(item)
    data["pending_items"] = pending
    count = len(pending)

    summary = _selected_items_summary(data)
    _save(data, "add_more")
    await say(
        f"Added **{item}** ✓\n\n"
        f"**Items selected so far ({count}/10):**\n{summary}\n\n"
        "Would you like to add another product? **(Yes / No)**"
    )


async def handle_add_more(text: str, data: dict):
    t = text.lower()
    if any(w in t for w in ["yes", "yeah", "yep", "sure", "add", "another", "more", "y"]):
        _save(data, "product_search")
        await say("What else are you looking for? *(Enter another keyword)*")
    elif any(w in t for w in ["no", "nope", "done", "finish", "proceed", "n"]):
        await _start_pricing(data)
    else:
        await say("Please reply **Yes** to add another product or **No** to proceed to pricing.")


async def _start_pricing(data: dict):
    pending = data.get("pending_items", [])
    if not pending:
        await say("No items to price. Please search for a product first.")
        _save(data, "product_search")
        return

    data["items_to_price"] = list(pending)
    data["pending_items"]  = []
    _save(data, "item_pricing")

    first       = data["items_to_price"][0]
    total_items = len(data["items_to_price"])
    await say(
        f"Let's finalise the quantities and pricing. You have **{total_items} item(s)** to price.\n\n"
        f"**Item 1/{total_items} — {first}**\n"
        "What is the **Quantity** and **Price per unit**?\n\n"
        "*e.g., `5 units at ₹85,000` · `10 @ 200` · `3, 15000`*"
    )


async def handle_item_pricing(text: str, data: dict):
    items_to_price: list[str] = data.get("items_to_price", [])
    if not items_to_price:
        _save(data, "preferred_vendors")
        await _show_vendor_prompt(data)
        return

    current = items_to_price[0]
    parsed  = parse_qty_price(text)

    if not parsed:
        await say(
            f"Couldn't parse that for **{current}**. Please try again.\n\n"
            "*Format: `5 units at ₹85,000` or `10, 200`*"
        )
        return

    qty, price = parsed
    line_items: list[dict] = data.get("line_items", [])
    line_items.append({
        "name":     current,
        "qty":      qty,
        "price":    price,
        "location": data.get("location", ""),
    })
    data["line_items"] = line_items
    items_to_price.pop(0)
    data["items_to_price"] = items_to_price

    line_total = qty * price

    if items_to_price:
        done        = len(line_items)
        total_count = done + len(items_to_price)
        next_item   = items_to_price[0]
        _save(data, "item_pricing")
        await say(
            f"✓ **{current}** — {qty} × {fmt_inr(price)} = **{fmt_inr(line_total)}**\n\n"
            f"**Item {done + 1}/{total_count} — {next_item}**\n"
            "What is the **Quantity** and **Price per unit**?"
        )
    else:
        total = running_total(line_items)
        _save(data, "preferred_vendors")
        await say(
            f"✓ **{current}** — {qty} × {fmt_inr(price)} = **{fmt_inr(line_total)}**\n\n"
            f"All items priced! Running total: **{fmt_inr(total)}**"
        )
        await _show_vendor_prompt(data)


async def _show_vendor_prompt(data: dict):
    vendor_list = get_filtered_vendors(data.get("line_items", []))
    data["available_vendors"] = vendor_list
    cl.user_session.set("data", data)
    await say(_build_vendor_prompt(vendor_list))


async def handle_preferred_vendors(text: str, data: dict):
    vendor_list = data.get("available_vendors", _catalog["vendors"])
    vendors     = resolve_vendors(text, vendor_list)
    data["preferred_vendors"] = ", ".join(vendors) if vendors else "None"

    if data.get("edit_mode"):
        data["edit_mode"] = False
        _save(data, "complete")
        await say(f"✓ Preferred vendors updated to **{data['preferred_vendors']}**.")
        await _show_final_summary(data)
        return

    _save(data, "quotation_status")
    await say(
        f"Noted — **{data['preferred_vendors']}**.\n\n"
        "Have you already received a **quotation document** from a vendor? **(Yes / No)**"
    )


async def handle_quotation_status(text: str, data: dict):
    t = text.lower()
    if any(w in t for w in ["yes", "yeah", "yep", "y", "have", "received"]):
        data["quotation"] = "Yes"
    elif any(w in t for w in ["no", "nope", "haven't", "not yet", "n"]):
        data["quotation"] = "No"
    else:
        await say("Please confirm — have you received a quotation? Reply **Yes** or **No**.")
        return

    if data.get("edit_mode"):
        data["edit_mode"] = False
        _save(data, "complete")
        await say(f"✓ Quotation status updated to **{data['quotation']}**.")
        await _show_final_summary(data)
        return

    _save(data, "complete")
    await _show_final_summary(data)


# ── Edit menu ──────────────────────────────────────────────────────────────────

async def handle_edit_menu(text: str, data: dict):
    t = text.strip()
    if not re.match(r"^\d+$", t):
        await say("Please type the **number** of the field you want to edit.")
        return

    choice = int(t)
    if choice == 1:
        data["edit_mode"] = True
        _save(data, "name")
        await say("What is your **name**?")

    elif choice == 2:
        data["edit_mode"] = True
        _save(data, "location")
        await say("What is your **location / site**? *(e.g., Mumbai, Delhi, Pune)*")

    elif choice == 3:
        items = data.get("line_items", [])
        if not items:
            await say("No line items to edit.")
            _save(data, "complete")
            await _show_final_summary(data)
            return
        lines = ["Which item would you like to update? Type the **number**:\n"]
        for i, item in enumerate(items, 1):
            lines.append(
                f"`{i}` {item['name']} — "
                f"{item['qty']} × {fmt_inr(item['price'])} = **{fmt_inr(item['qty'] * item['price'])}**"
            )
        data["edit_mode"] = True
        _save(data, "edit_item_select")
        await say("\n".join(lines))

    elif choice == 4:
        data["edit_mode"] = True
        await _show_vendor_prompt(data)
        _save(data, "preferred_vendors")

    elif choice == 5:
        data["edit_mode"] = True
        _save(data, "quotation_status")
        await say("Have you received a **quotation document**? **(Yes / No)**")

    else:
        await say("Please enter a number between **1 and 5**.")


async def handle_edit_item_select(text: str, data: dict):
    items = data.get("line_items", [])
    t     = text.strip()
    if not re.match(r"^\d+$", t):
        await say("Please type the item number.")
        return
    idx = int(t) - 1
    if not (0 <= idx < len(items)):
        await say(f"Please enter a number between 1 and {len(items)}.")
        return
    data["edit_item_index"] = idx
    item = items[idx]
    _save(data, "edit_item_price")
    await say(
        f"Updating **{item['name']}**\n"
        f"*(current: {item['qty']} × {fmt_inr(item['price'])})*\n\n"
        "Enter new **Quantity** and **Price per unit**:\n"
        "*e.g., `5 units at ₹85,000` · `10 @ 200` · `3, 15000`*"
    )


async def handle_edit_item_price(text: str, data: dict):
    items  = data.get("line_items", [])
    idx    = data.get("edit_item_index", 0)
    parsed = parse_qty_price(text)
    if not parsed:
        await say("Couldn't parse. Try: `5 units at ₹85,000` or `10, 200`")
        return
    qty, price = parsed
    items[idx]["qty"]   = qty
    items[idx]["price"] = price
    data["line_items"]  = items
    data["edit_mode"]   = False
    _save(data, "complete")
    total = running_total(items)
    await say(
        f"✓ Updated **{items[idx]['name']}** → {qty} × {fmt_inr(price)} = **{fmt_inr(qty * price)}**\n"
        f"New running total: **{fmt_inr(total)}**"
    )
    await _show_final_summary(data)


# ── Final summary ──────────────────────────────────────────────────────────────

async def _show_final_summary(data: dict):
    items = data.get("line_items", [])
    total = running_total(items)
    name  = data.get("requestor_name", "—")

    rows = "\n".join(
        f"| {i['name']} | {i['qty']} | {fmt_inr(i['price'])} "
        f"| {fmt_inr(i['qty'] * i['price'])} | {i['location']} |"
        for i in items
    ) or "| *No items* | — | — | — | — |"

    summary = f"""---
### 📋 Purchase Request — Final Review
Please review your requisition before submission.

* **Requestor:** {name} ({REQUESTOR_ID}) | {ENTITY}
* **Department:** {data.get('department')} &nbsp;|&nbsp; **Location:** {data.get('location')}
* **Contact:** {data.get('email')} &nbsp;·&nbsp; {data.get('phone')}
* **Purchase Type:** {data.get('purchase_type')} &nbsp;|&nbsp; **Priority:** {data.get('priority')}
* **Completion Date:** {data.get('completion_date')}
* **Estimated Budget:** {fmt_inr(total)}
* **Preferred Vendors:** {data.get('preferred_vendors')}
* **Quotation Received:** {data.get('quotation')}
* **Request Date:** {REQUEST_DATE}

#### Line Items ({len(items)}/10)
| Item Name | Qty | Unit Price | Line Total | Location |
| :--- | :---: | ---: | ---: | :--- |
{rows}
| **TOTAL** | | | **{fmt_inr(total)}** | |

---"""

    msg = cl.Message(content=summary)
    msg.actions = [
        cl.Action(name="submit_pr",  label="🚀 Submit Purchase Request", payload={"value": "submit"}),
        cl.Action(name="edit_pr",    label="✏️ Edit",                    payload={"value": "edit"}),
        cl.Action(name="restart_pr", label="🔄 Start Over",              payload={"value": "restart"}),
    ]
    await msg.send()


# ── Action callbacks ───────────────────────────────────────────────────────────

@cl.action_callback("submit_pr")
async def on_submit_pr(_: cl.Action):
    data = cl.user_session.get("data") or {}
    msg  = cl.Message(content="⏳ Submitting your Purchase Request...")
    await msg.send()
    try:
        items     = data.get("line_items", [])
        items_txt = ", ".join(
            f"{i['qty']} {i['name']} at {fmt_inr(i['price'])} each" for i in items
        )
        nl_input = (
            f"Department: {data.get('department')}. "
            f"Purchase Type: {data.get('purchase_type')}. "
            f"Priority: {data.get('priority')}. "
            f"Reason: {data.get('reason')}. "
            f"Items: {items_txt}. "
            f"Required by: {data.get('completion_date')}. "
            f"Location: {data.get('location')}."
        )
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{BASE_URL}/procurement/",
                json={"buyer_id": f"buyer_{REQUESTOR_ID}", "natural_language_input": nl_input},
                timeout=15.0,
            )
            resp.raise_for_status()
            result = resp.json()

        proc_id = result.get("procurement_id", "N/A")
        msg.content = (
            f"✅ **Purchase Request Submitted Successfully!**\n\n"
            f"* **Reference ID:** `{proc_id}`\n"
            f"* **Requestor:** {data.get('requestor_name')} ({REQUESTOR_ID}) — {ENTITY}\n"
            f"* **Total Value:** {fmt_inr(running_total(items))}\n"
            f"* **Status:** Queued for processing"
        )
        await msg.update()
    except Exception as e:
        msg.content = f"❌ Submission failed: {str(e)}"
        await msg.update()


@cl.action_callback("edit_pr")
async def on_edit_pr(_: cl.Action):
    data = cl.user_session.get("data") or {}
    _save(data, "edit_menu")
    await say(
        "What would you like to edit? Type the **number**:\n\n"
        "`1` Requestor Name\n"
        "`2` Location\n"
        "`3` Line Item (quantity / price)\n"
        "`4` Preferred Vendors\n"
        "`5` Quotation Status"
    )


@cl.action_callback("restart_pr")
async def on_restart_pr(_: cl.Action):
    cl.user_session.set("step", "name")
    cl.user_session.set("data", {**PRELOADED, "location": "", "line_items": [], "pending_items": [], "items_to_price": []})
    await say("No problem — let's start fresh.\n\nCould I get your **name** to begin?")


# ── Auth (required for thread history sidebar) ────────────────────────────────
# Auto-authenticates silently — no login screen shown.
# Chainlit needs a known user identity to store and display thread history.

@cl.header_auth_callback
def header_auth_callback(headers: dict) -> cl.User | None:
    return cl.User(
        identifier=REQUESTOR_ID,
        metadata={"name": "Rahul Devakar", "entity": ENTITY},
    )


# ── Chainlit entry points ──────────────────────────────────────────────────────

@cl.on_chat_start
async def on_chat_start():
    await _load_catalog()
    cl.user_session.set("step", "name")
    cl.user_session.set("data", {**PRELOADED, "location": "", "line_items": [], "pending_items": [], "items_to_price": []})
    await say(
        f"Welcome to **{ENTITY}** Procurement Intake.\n\n"
        "Could I get your **name** to get started?"
    )


@cl.on_message
async def on_message(message: cl.Message):
    step = cl.user_session.get("step") or "name"
    data = cl.user_session.get("data") or {**PRELOADED, "location": "", "line_items": [], "pending_items": [], "items_to_price": []}
    text = message.content.strip()

    if step == "complete":
        await say("Your request is ready. Click **🚀 Submit** above, **✏️ Edit** to make changes, or **🔄 Start Over** for a new request.")
        return

    dispatch = {
        "name":              handle_name,
        "location":          handle_location,
        "product_search":    handle_product_search,
        "item_select":       handle_item_select,
        "add_more":          handle_add_more,
        "item_pricing":      handle_item_pricing,
        "preferred_vendors": handle_preferred_vendors,
        "quotation_status":  handle_quotation_status,
        "edit_menu":         handle_edit_menu,
        "edit_item_select":  handle_edit_item_select,
        "edit_item_price":   handle_edit_item_price,
    }

    handler = dispatch.get(step)
    if handler:
        await handler(text, data)
    else:
        await say("Something went wrong. Please refresh the page to start a new session.")
