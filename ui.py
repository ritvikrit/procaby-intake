import re
import os
import json
import sqlite3
import httpx
import anthropic
import chainlit as cl
from chainlit.data.sql_alchemy import SQLAlchemyDataLayer
from datetime import date, timedelta

# ── SQLite history DB ─────────────────────────────────────────────────────────

_SQLITE_DB = "./chainlit_history.db"


def _init_db() -> None:
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

    for migration in [
        'ALTER TABLE steps ADD COLUMN "defaultOpen" INTEGER DEFAULT 0',
        'ALTER TABLE steps ADD COLUMN "autoCollapse" INTEGER DEFAULT 0',
        'ALTER TABLE elements ADD COLUMN props TEXT',
    ]:
        try:
            cur.execute(migration)
        except sqlite3.OperationalError:
            pass
    con.commit()
    con.close()


_init_db()


@cl.data_layer
def _get_data_layer() -> SQLAlchemyDataLayer:
    return SQLAlchemyDataLayer(conninfo=f"sqlite+aiosqlite:///{_SQLITE_DB}")


BASE_URL      = "http://localhost:8000/api/v1"
ENTITY        = "Katalyst Technologies"
REQUESTOR_ID  = "AD00076"
TODAY         = date(2026, 5, 28)
REQUEST_DATE  = "28-05-2026"
CLAUDE_API_KEY = os.getenv("CLAUDE_API_KEY")

PRELOADED = {
    "department":     "Engineering",
    "email":          "rahul.devakar@katalyst.com",
    "phone":          "+91 98765 43210",
    "purchase_type":  "Hardware",
    "priority":       "Medium",
    "reason":         "Operational procurement requirement",
    "completion_date": (TODAY + timedelta(days=30)).strftime("%d-%m-%Y"),
}

# ── Catalog cache ─────────────────────────────────────────────────────────────

_catalog: dict = {
    "categories": {},
    "flat": [],
    "vendors": [],
    "vendor_category_map": {},
    "item_ids": {},      # {item_name: procbay_item_id}
    "vendor_ids": {},    # {vendor_name: procbay_global_vendor_id}
}


async def _load_catalog() -> None:
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
        _catalog["categories"]          = items_data.get("categories", {})
        _catalog["flat"]                = [i for lst in _catalog["categories"].values() for i in lst]
        _catalog["item_ids"]            = items_data.get("item_ids", {})
        _catalog["vendors"]             = vendors_data.get("vendors", [])
        _catalog["vendor_category_map"] = vendors_data.get("category_map", {})
        _catalog["vendor_ids"]          = vendors_data.get("vendor_ids", {})
    except Exception as exc:
        print(f"[catalog] WARNING: could not load catalog from API — {exc}")


# ── Claude system prompt ──────────────────────────────────────────────────────

def _build_system_prompt() -> str:
    categories_text = ""
    for cat, items in _catalog["categories"].items():
        sample = items[:20]
        categories_text += f"\n  {cat}: {', '.join(sample)}"
        if len(items) > 20:
            categories_text += f" (+{len(items) - 20} more)"

    vendors_text = ", ".join(_catalog["vendors"]) if _catalog["vendors"] else "None available"

    return f"""You are a friendly procurement intake assistant for {ENTITY}. Collect purchase request information by following a specific step-by-step flow — but respond intelligently and naturally, not robotically.

PRE-FILLED (do NOT ask about these):
- Department: {PRELOADED['department']}
- Email: {PRELOADED['email']}
- Phone: {PRELOADED['phone']}
- Purchase Type: {PRELOADED['purchase_type']}
- Priority: {PRELOADED['priority']}
- Completion Date: {PRELOADED['completion_date']}

FOLLOW THIS EXACT SEQUENCE — one step at a time:

STEP 1 — Ask for the requestor's full name.

STEP 2 — Ask for their location. Show these options and let them pick:
  1. Pune Office
  2. Pune Office 2
  3. Magarpatta
  4. kharadi
  5. Hinjawdi
  6. Narhe

STEP 3 — Ask what product or component they are looking for.
  - Search the catalog and suggest matching items.
  - Show matched items as a numbered list.
  - Let them pick by number or name.
  - IMPORTANT: If the requested item does not exist in the catalog, politely inform the user that the item is unavailable and ask them to search for a different product. Do NOT add unavailable items to the order or proceed further.
  - After each item is added, ask "Would you like to add another product? (Yes / No)"
  - Repeat until they say No.

STEP 4 — For each item collected, ask for quantity and price per unit (INR).
  - Ask one item at a time: "For [item name], what is the quantity and price per unit?"

STEP 5 — Show the available vendors and ask which they prefer (or None).
  Available vendors: {vendors_text}

STEP 6 — Ask if they have received a quotation document (Yes / No).

STEP 7 — Show a complete summary and ask them to confirm before submitting.

RULES:
- Follow the steps in order — do not skip ahead
- If the user provides info early (e.g. mentions location in step 1), accept it and skip that step
- Be warm and conversational, not robotic
- STRICT CATALOG RULE: Only accept items that exist in the catalog. Never proceed with items not in the catalog.
- Always confirm the full summary before outputting the completion block

AVAILABLE CATALOG ITEMS:{categories_text}

WHEN ALL INFO IS CONFIRMED — output EXACTLY this (tags included):
<PROCUREMENT_READY>
{{"requestor_name":"full name","location":"location","line_items":[{{"name":"item","qty":1,"price":0.0,"location":"location"}}],"preferred_vendors":"vendor or None","quotation":"Yes or No"}}
</PROCUREMENT_READY>

Output the completion block only after the user confirms the summary."""


# ── Helpers ───────────────────────────────────────────────────────────────────

def fmt_inr(amount: float) -> str:
    return f"₹{amount:,.2f}"


def running_total(items: list) -> float:
    return sum(i["qty"] * i["price"] for i in items)


async def say(text: str):
    await cl.Message(content=text).send()


async def _update_thread_title(title: str) -> None:
    try:
        from chainlit.data import get_data_layer
        data_layer = get_data_layer()
        thread_id  = cl.context.session.thread_id
        if data_layer and thread_id:
            await data_layer.update_thread(thread_id=thread_id, name=title)
    except Exception as e:
        print(f"[thread_title] Could not update: {e}")


# ── Final summary ─────────────────────────────────────────────────────────────

async def _show_final_summary(data: dict):
    items = data.get("line_items", [])
    total = running_total(items)
    name  = data.get("requestor_name", "—")

    rows = "\n".join(
        f"| {i['name']} | {i['qty']} | {fmt_inr(i['price'])} "
        f"| {fmt_inr(i['qty'] * i['price'])} | {i.get('location', '')} |"
        for i in items
    ) or "| *No items* | — | — | — | — |"

    summary = f"""---
### 📋 Purchase Request — Final Review
Please review your requisition before submission.

* **Requestor:** {name} ({REQUESTOR_ID}) | {ENTITY}
* **Department:** {PRELOADED['department']} &nbsp;|&nbsp; **Location:** {data.get('location')}
* **Contact:** {PRELOADED['email']} &nbsp;·&nbsp; {PRELOADED['phone']}
* **Purchase Type:** {PRELOADED['purchase_type']} &nbsp;|&nbsp; **Priority:** {PRELOADED['priority']}
* **Completion Date:** {PRELOADED['completion_date']}
* **Estimated Budget:** {fmt_inr(total)}
* **Preferred Vendors:** {data.get('preferred_vendors')}
* **Quotation Received:** {data.get('quotation')}

#### Line Items
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


# ── Action callbacks ──────────────────────────────────────────────────────────

@cl.action_callback("submit_pr")
async def on_submit_pr(_: cl.Action):
    # Block if already submitted or a submission is in progress (race condition guard)
    if cl.user_session.get("submitted") or cl.user_session.get("submitting"):
        await say("⚠️ **Request Already Submitted** — your purchase request has already been submitted and cannot be submitted again. Please start a new chat to raise another request.")
        return

    cl.user_session.set("submitting", True)

    data = cl.user_session.get("data") or {}
    msg  = cl.Message(content="⏳ Submitting your Purchase Request...")
    await msg.send()
    try:
        items     = data.get("line_items", [])
        items_txt = ", ".join(
            f"{i['qty']} {i['name']} at {fmt_inr(i['price'])} each" for i in items
        )
        nl_input = (
            f"Department: {PRELOADED['department']}. "
            f"Purchase Type: {PRELOADED['purchase_type']}. "
            f"Priority: {PRELOADED['priority']}. "
            f"Reason: {PRELOADED['reason']}. "
            f"Items: {items_txt}. "
            f"Required by: {PRELOADED['completion_date']}. "
            f"Location: {data.get('location', '')}."
        )
        structured_items = [
            {
                "item_name":           i["name"],
                "quantity":            i["qty"],
                "unit":                "pcs",
                "unit_price_inr":      i["price"],
                "estimated_price_inr": i["qty"] * i["price"],
                "location":            i.get("location", ""),
                "procbay_id":          i.get("procbay_id"),
            }
            for i in items
        ]
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{BASE_URL}/procurement/",
                json={
                    "buyer_id":               f"buyer_{REQUESTOR_ID}",
                    "natural_language_input": nl_input,
                    "requestor_name":         data.get("requestor_name"),
                    "location":               data.get("location"),
                    "department":             PRELOADED["department"],
                    "email":                  PRELOADED["email"],
                    "phone":                  PRELOADED["phone"],
                    "purchase_type":          PRELOADED["purchase_type"],
                    "priority":               PRELOADED["priority"],
                    "completion_date":        PRELOADED["completion_date"],
                    "reason":                 PRELOADED["reason"],
                    "preferred_vendors":      data.get("preferred_vendors"),
                    "preferred_vendor_id":    data.get("preferred_vendor_id"),
                    "quotation_received":     data.get("quotation"),
                    "line_items":             structured_items,
                },
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
            f"* **Status:** Queued for processing\n\n"
            f"*This session is now closed. Start a new chat to raise another request.*"
        )
        await msg.update()
        cl.user_session.set("submitted", True)
        cl.user_session.set("submitting", False)
        # Persist submitted state to thread metadata so it survives page refresh
        try:
            from chainlit.data import get_data_layer
            dl = get_data_layer()
            tid = cl.context.session.thread_id
            if dl and tid:
                await dl.update_thread(thread_id=tid, metadata={"submitted": True})
        except Exception:
            pass
    except Exception as e:
        cl.user_session.set("submitting", False)  # allow retry on failure
        msg.content = f"❌ Submission failed: {str(e)}"
        await msg.update()


@cl.action_callback("edit_pr")
async def on_edit_pr(_: cl.Action):
    data    = cl.user_session.get("data") or {}
    history = cl.user_session.get("history") or []

    edit_msg = (
        f"The user wants to edit their purchase request. "
        f"Current data: {json.dumps(data)}. "
        f"Ask them what they'd like to change, make the change conversationally, "
        f"then confirm the updated details and output the PROCUREMENT_READY block again."
    )
    history.append({"role": "user", "content": edit_msg})
    cl.user_session.set("history", history)
    await say("What would you like to edit? You can change the name, location, items, quantities, prices, vendors, or quotation status.")


@cl.action_callback("restart_pr")
async def on_restart_pr(_: cl.Action):
    cl.user_session.set("history", [])
    cl.user_session.set("data", {})
    await say(
        f"Let's start fresh!\n\n"
        f"I'm your procurement assistant for **{ENTITY}**. "
        "What would you like to procure today?"
    )


# ── Auth ──────────────────────────────────────────────────────────────────────

@cl.header_auth_callback
def header_auth_callback(headers: dict) -> cl.User | None:
    return cl.User(
        identifier=REQUESTOR_ID,
        metadata={"name": "Rahul Devakar", "entity": ENTITY},
    )


# ── Chainlit entry points ─────────────────────────────────────────────────────

@cl.on_chat_start
async def on_chat_start():
    await _load_catalog()
    cl.user_session.set("history", [])
    cl.user_session.set("data", {})
    cl.user_session.set("submitting", False)

    # Restore submitted state from thread metadata (survives page refresh)
    try:
        from chainlit.data import get_data_layer
        dl = get_data_layer()
        tid = cl.context.session.thread_id
        if dl and tid:
            thread = await dl.get_thread(tid)
            if thread and thread.metadata and thread.metadata.get("submitted"):
                cl.user_session.set("submitted", True)
            else:
                cl.user_session.set("submitted", False)
    except Exception:
        cl.user_session.set("submitted", False)

    await say(
        f"Welcome to **{ENTITY}** Procurement Intake!\n\n"
        "Could you please share your **full name** to get started?"
    )


@cl.on_message
async def on_message(message: cl.Message):
    if not CLAUDE_API_KEY:
        await say("❌ Claude API key not configured. Please add CLAUDE_API_KEY to .env")
        return

    if cl.user_session.get("submitted"):
        await say("Your purchase request has already been submitted. Please start a new chat to raise another request.")
        return

    history: list = cl.user_session.get("history") or []
    data: dict    = cl.user_session.get("data") or {}

    is_first_message = len(history) == 0
    history.append({"role": "user", "content": message.content})

    # Set thread title to user's first message
    if is_first_message:
        await _update_thread_title(message.content.strip()[:80])

    client   = anthropic.Anthropic(api_key=CLAUDE_API_KEY)
    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=2048,
        system=_build_system_prompt(),
        messages=history,
    )
    reply = response.content[0].text

    history.append({"role": "assistant", "content": reply})
    cl.user_session.set("history", history)

    # Check if Claude has all info and signalled completion
    if "<PROCUREMENT_READY>" in reply and "</PROCUREMENT_READY>" in reply:
        try:
            json_str = reply.split("<PROCUREMENT_READY>")[1].split("</PROCUREMENT_READY>")[0].strip()
            parsed   = json.loads(json_str)

            # Enrich line items with ProcaBay item IDs
            line_items = parsed.get("line_items", [])
            for item in line_items:
                item["procbay_id"] = _catalog["item_ids"].get(item.get("name", ""), None)

            # Resolve preferred vendor names to ProcaBay vendor IDs
            vendor_str  = parsed.get("preferred_vendors", "None")
            vendor_id   = None
            if vendor_str and vendor_str.lower() != "none":
                first_vendor = vendor_str.split(",")[0].strip()
                vendor_id = _catalog["vendor_ids"].get(first_vendor)

            data = {
                **PRELOADED,
                "requestor_name":    parsed.get("requestor_name", ""),
                "location":          parsed.get("location", ""),
                "line_items":        line_items,
                "preferred_vendors": vendor_str,
                "preferred_vendor_id": vendor_id,
                "quotation":         parsed.get("quotation", "No"),
            }
            cl.user_session.set("data", data)

            # Update thread title to product name
            items_for_title = [i.get("name", "") for i in line_items if i.get("name")]
            if items_for_title:
                product_title = items_for_title[0] if len(items_for_title) == 1 else f"{items_for_title[0]} +{len(items_for_title)-1} more"
                await _update_thread_title(product_title)

            text_before = reply.split("<PROCUREMENT_READY>")[0].strip()
            if text_before:
                await say(text_before)

            await _show_final_summary(data)
            return
        except Exception as e:
            print(f"[Claude] Failed to parse completion JSON: {e}")

    # Normal reply — strip any broken completion block
    clean_reply = re.sub(r"<PROCUREMENT_READY>.*?</PROCUREMENT_READY>", "", reply, flags=re.DOTALL).strip()
    await say(clean_reply)
