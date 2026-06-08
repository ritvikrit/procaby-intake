import re
import json
import anthropic
from collections import defaultdict
from datetime import date, timedelta

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_db
from app.models.catalog import CatalogueVendor, ItemsWithCategory, VendorReference
from app.orchestrator.engine import OrchestratorEngine
from app.orchestrator.exceptions import HITLRequiredException, ClarificationRequiredException

router = APIRouter()

ENTITY        = "Katalyst Technologies"
REQUESTOR_ID  = "AD00076"

DEFAULT_PRELOADED = {
    "department":     "Engineering",
    "email":          "rahul.devakar@katalyst.com",
    "phone":          "+91 98765 43210",
    "purchase_type":  "Hardware",
    "priority":       "Medium",
    "reason":         "Operational procurement requirement",
    "completion_date": (date.today() + timedelta(days=30)).strftime("%d-%m-%Y"),
}

# ── In-memory sessions ────────────────────────────────────────────────────────
# { session_id: { history, data, submitted, preloaded } }
_sessions: dict = {}

# ── Catalog cache (loaded once from DB) ───────────────────────────────────────
_catalog: dict = {
    "categories": {},
    "flat": [],
    "vendors": [],
    "vendor_category_map": {},
    "item_ids": {},
    "vendor_ids": {},
    "loaded": False,
}

_vendor_name_col = VendorReference.meta_data["name"].astext


async def _load_catalog(db: AsyncSession) -> None:
    if _catalog["loaded"]:
        return

    items_result = await db.execute(
        select(ItemsWithCategory).order_by(ItemsWithCategory.cat_name, ItemsWithCategory.id)
    )
    items = items_result.scalars().all()
    categories: dict = defaultdict(list)
    item_ids: dict = {}
    for item in items:
        key = item.cat_name or "Uncategorized"
        categories[key].append(item.item_name)
        item_ids[item.item_name] = item.id

    vendors_result = await db.execute(
        select(VendorReference.global_vendor_id, _vendor_name_col).order_by(_vendor_name_col)
    )
    vendor_rows = vendors_result.all()
    vendors    = [r[1] for r in vendor_rows if r[1]]
    vendor_ids = {r[1]: r[0] for r in vendor_rows if r[1] and r[0]}

    vc_result = await db.execute(
        select(_vendor_name_col, ItemsWithCategory.cat_name)
        .join(CatalogueVendor, CatalogueVendor.vendor_id == VendorReference.global_vendor_id)
        .join(ItemsWithCategory, ItemsWithCategory.id == CatalogueVendor.item_id)
        .distinct()
    )
    category_map: dict = defaultdict(list)
    for vendor_name, cat_name in vc_result.all():
        if vendor_name and cat_name:
            category_map[cat_name].append(vendor_name)

    _catalog["categories"]          = dict(categories)
    _catalog["flat"]                = [i for lst in categories.values() for i in lst]
    _catalog["item_ids"]            = item_ids
    _catalog["vendors"]             = vendors
    _catalog["vendor_ids"]          = vendor_ids
    _catalog["vendor_category_map"] = dict(category_map)
    _catalog["loaded"]              = True


def _build_system_prompt(preloaded: dict) -> str:
    categories_text = ""
    for cat, items in _catalog["categories"].items():
        sample = items[:20]
        categories_text += f"\n  {cat}: {', '.join(sample)}"
        if len(items) > 20:
            categories_text += f" (+{len(items) - 20} more)"

    vendors_text = ", ".join(_catalog["vendors"]) if _catalog["vendors"] else "None available"

    return f"""You are a friendly procurement intake assistant for {ENTITY}. Collect purchase request information by following a specific step-by-step flow — but respond intelligently and naturally, not robotically.

PRE-FILLED (do NOT ask about these):
- Department: {preloaded['department']}
- Email: {preloaded['email']}
- Phone: {preloaded['phone']}
- Purchase Type: {preloaded['purchase_type']}
- Priority: {preloaded['priority']}
- Completion Date: {preloaded['completion_date']}

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


# ── Request / Response schemas ────────────────────────────────────────────────

class ChatRequest(BaseModel):
    session_id: str
    message: str
    # Optional overrides for pre-filled fields (pass on first message if needed)
    department:      str | None = None
    email:           str | None = None
    phone:           str | None = None
    purchase_type:   str | None = None
    priority:        str | None = None
    completion_date: str | None = None
    reason:          str | None = None


class ChatResponse(BaseModel):
    reply:   str
    state:   str        # "collecting" | "ready" | "submitted"
    summary: dict | None = None


class SubmitRequest(BaseModel):
    session_id: str


# ── Routes ────────────────────────────────────────────────────────────────────

@router.post("/", response_model=ChatResponse)
async def chat(body: ChatRequest, db: AsyncSession = Depends(get_db)):
    """
    Send a message and get Claude's reply.

    - state="collecting" : conversation still in progress
    - state="ready"      : all info collected, summary included — call /submit to finalise
    - state="submitted"  : already submitted, start a new session
    """
    await _load_catalog(db)

    session = _sessions.setdefault(body.session_id, {
        "history":   [],
        "data":      {},
        "submitted": False,
        "preloaded": DEFAULT_PRELOADED.copy(),
    })

    if session["submitted"]:
        return ChatResponse(
            reply="This request has already been submitted. Use a new session_id to start another request.",
            state="submitted",
        )

    # Let caller override any pre-filled fields (useful if they pass user profile on first call)
    for field in ("department", "email", "phone", "purchase_type", "priority", "completion_date", "reason"):
        val = getattr(body, field, None)
        if val is not None:
            session["preloaded"][field] = val

    history  = session["history"]
    preloaded = session["preloaded"]
    history.append({"role": "user", "content": body.message})

    client = anthropic.Anthropic(api_key=settings.CLAUDE_API_KEY)
    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=2048,
        system=_build_system_prompt(preloaded),
        messages=history,
    )
    reply = response.content[0].text
    history.append({"role": "assistant", "content": reply})

    # Check if Claude has finished collecting and signalled completion
    if "<PROCUREMENT_READY>" in reply and "</PROCUREMENT_READY>" in reply:
        try:
            json_str = reply.split("<PROCUREMENT_READY>")[1].split("</PROCUREMENT_READY>")[0].strip()
            parsed   = json.loads(json_str)

            line_items = parsed.get("line_items", [])
            for item in line_items:
                item["procbay_id"] = _catalog["item_ids"].get(item.get("name", ""), None)

            vendor_str = parsed.get("preferred_vendors", "None")
            vendor_id  = None
            if vendor_str and vendor_str.lower() != "none":
                first_vendor = vendor_str.split(",")[0].strip()
                vendor_id = _catalog["vendor_ids"].get(first_vendor)

            data = {
                **preloaded,
                "requestor_name":     parsed.get("requestor_name", ""),
                "location":           parsed.get("location", ""),
                "line_items":         line_items,
                "preferred_vendors":  vendor_str,
                "preferred_vendor_id": vendor_id,
                "quotation":          parsed.get("quotation", "No"),
            }
            session["data"] = data

            clean_reply = re.sub(
                r"<PROCUREMENT_READY>.*?</PROCUREMENT_READY>", "", reply, flags=re.DOTALL
            ).strip()
            return ChatResponse(
                reply=clean_reply or "Here's your summary. Ready to submit?",
                state="ready",
                summary=data,
            )
        except Exception as e:
            print(f"[chat] Failed to parse PROCUREMENT_READY: {e}")

    clean_reply = re.sub(
        r"<PROCUREMENT_READY>.*?</PROCUREMENT_READY>", "", reply, flags=re.DOTALL
    ).strip()
    return ChatResponse(reply=clean_reply, state="collecting")


@router.post("/submit")
async def submit(body: SubmitRequest, db: AsyncSession = Depends(get_db)):
    """
    Submit the completed procurement to ProcaBay.
    Call this only when /chat returns state="ready" and the user has confirmed.
    """
    session = _sessions.get(body.session_id)
    if not session:
        return {"error": "Session not found. Start a chat first."}
    if session["submitted"]:
        return {"error": "Already submitted."}

    data = session.get("data", {})
    if not data:
        return {"error": "No completed procurement data. Continue the chat until you reach the summary."}

    preloaded = session["preloaded"]
    items     = data.get("line_items", [])

    items_txt = ", ".join(f"{i['qty']} {i['name']} at ₹{i['price']} each" for i in items)
    nl_input  = (
        f"Department: {preloaded['department']}. "
        f"Purchase Type: {preloaded['purchase_type']}. "
        f"Priority: {preloaded['priority']}. "
        f"Reason: {preloaded['reason']}. "
        f"Items: {items_txt}. "
        f"Required by: {preloaded['completion_date']}. "
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

    extra = {
        "requestor_name":     data.get("requestor_name"),
        "location":           data.get("location"),
        "department":         preloaded["department"],
        "email":              preloaded["email"],
        "phone":              preloaded["phone"],
        "purchase_type":      preloaded["purchase_type"],
        "priority":           preloaded["priority"],
        "completion_date":    preloaded["completion_date"],
        "reason":             preloaded["reason"],
        "preferred_vendors":  data.get("preferred_vendors"),
        "preferred_vendor_id": data.get("preferred_vendor_id"),
        "quotation_received": data.get("quotation"),
        "line_items":         structured_items,
    }

    try:
        engine = OrchestratorEngine(db)
        proc   = await engine.create_procurement(f"buyer_{REQUESTOR_ID}", nl_input, extra)
        session["submitted"] = True
        return {
            "procurement_id": str(proc.procurement_id),
            "status":         "CREATED",
            "requestor_name": data.get("requestor_name"),
            "total_value":    sum(i["qty"] * i["price"] for i in items),
        }
    except HITLRequiredException as e:
        return {"status": "PAUSED_HITL", "message": str(e)}
    except ClarificationRequiredException as e:
        return {"status": "PAUSED_CLARIFICATION", "question": e.question}
    except Exception as e:
        return {"error": str(e)}


@router.get("/catalog")
async def get_catalog(db: AsyncSession = Depends(get_db)):
    """Return catalog items and vendors so the frontend can show options."""
    await _load_catalog(db)
    return {
        "categories": _catalog["categories"],
        "vendors":    _catalog["vendors"],
    }


@router.delete("/{session_id}")
async def clear_session(session_id: str):
    """Clear a session — call this when the user starts over or closes the chat."""
    _sessions.pop(session_id, None)
    return {"cleared": session_id}
