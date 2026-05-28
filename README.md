# ProcBay Agentic Orchestrator

**Centralized State Machine Orchestrator for Automated Procurement**

A FastAPI-based, database-backed orchestration system that coordinates 9 specialist stateless sub-agents through a 9-stage procurement pipeline. Enforces strict human-in-the-loop (HITL) safety gates, handles both standard RFQs and real-time live reverse auctions, and maintains full audit logs in PostgreSQL.

## Architecture Overview

### Core Components

- **Orchestrator Engine** (`app/orchestrator/engine.py`): State machine that reads/writes pipeline state from PostgreSQL, routes to appropriate agents, handles exceptions
- **9 Stateless Sub-Agents**: Each stage has a dedicated agent with no persistent memory
  1. **Intake**: Parses natural language procurement intent
  2. **Approvals**: Financial routing & HITL pause (₹50K–₹5M thresholds)
  3. **PR Generation**: Generates formal Purchase Requisitions
  4. **Cart**: Consolidates line items across PRs for purchasing leverage
  5. **Event**: Configures RFQ or live Auction sourcing strategy
  6. **Quote**: Normalizes diverse incoming vendor bids to uniform format
  7. **Negotiation**: Analyzes bids, calculates margins, drafts counter-offers
  8. **Awarding**: Single-vendor selection & HITL pause
  9. **PO**: Generates binding Purchase Order, closes cycle

- **Pipeline State**: Single unified Procurement model in PostgreSQL with JSON fields for flexible data schemas
- **Approval Workflow**: Sequential routing (Manager → CFO) for high-value purchases; auto-routing for standard approvals
- **Real-Time Auction**: WebSocket broadcast of live bids, asyncio-based countdown timers, database row locking for concurrent bids

## Setup

### Prerequisites

- Python 3.10+
- PostgreSQL 13+
- Redis (optional, for future PubSub integration)

### Installation

```bash
# Create virtual environment
python -m venv venv
source venv/bin/activate  # or venv\Scripts\activate on Windows

# Install dependencies
pip install -r requirements.txt

# Create .env file
cp .env.example .env
# Edit .env with your PostgreSQL credentials

# Initialize database
alembic upgrade head
# Or for dev: the app auto-creates tables on first run via SQLAlchemy
```

### Running the Application

```bash
# Development server
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

# API docs available at http://localhost:8000/docs
```

## API Endpoints

### Create Procurement

```bash
POST /api/v1/procurement/
{
  "buyer_id": "buyer_001",
  "natural_language_input": "I need 500 gloves and 200 masks by end of month"
}
```

Response:
```json
{
  "procurement_id": "550e8400-e29b-41d4-a716-446655440000",
  "status": "CREATED"
}
```

### Check History (Non-Destructive Query)

```bash
GET /api/v1/procurement/{procurement_id}/history
```

### Advance Stage

```bash
POST /api/v1/procurement/{procurement_id}/advance
```

### Submit Clarification

```bash
POST /api/v1/procurement/{procurement_id}/clarify
{
  "procurement_id": "...",
  "buyer_id": "buyer_001",
  "response_text": "Actually, we need 50 additional units"
}
```

### Submit Vendor Bid

```bash
POST /api/v1/procurement/{procurement_id}/bid
{
  "vendor_id": "vendor_xyz",
  "vendor_name": "Acme Supplies",
  "unit_price_inr": 50.0,
  "quantity": 500,
  "delivery_days": 7
}
```

### HITL Webhooks

**Approval Decision:**
```bash
POST /api/v1/webhooks/approval
{
  "procurement_id": "...",
  "approver_id": "mgr_001",
  "decision": "APPROVED",
  "notes": "Approved within budget guidelines"
}
```

**Award Confirmation:**
```bash
POST /api/v1/webhooks/award-confirmation
{
  "procurement_id": "...",
  "buyer_id": "buyer_001",
  "confirmed_vendor_id": "vendor_xyz"
}
```

### Rejection Branches (After Blocked Approval)

```bash
POST /api/v1/procurement/{procurement_id}/rejection-branch
{
  "branch": "REVISE_REQUEST"  // or ESCALATE_ROUTING, CANCEL_PROCUREMENT
}
```

### WebSocket: Live Auction Feed

```
ws://localhost:8000/ws/auction/{procurement_id}
```

Connect to receive real-time bid updates as vendors submit competing bids during a live auction.

## Pipeline States

### Stages (in order)
- `INTAKE` → `APPROVALS` → `PR_GENERATION` → `CART` → `EVENT` → `QUOTE` → `NEGOTIATION` → `AWARDING` → `PO_GENERATION` → `CLOSED`

### Pipeline Status
- `ACTIVE`: Running normally
- `PAUSED_HITL`: Awaiting human approval or confirmation
- `PAUSED_CLARIFICATION`: Awaiting buyer response to clarification question
- `CLOSED`: Procurement cycle complete
- `CANCELLED`: Terminated by user

## HITL Safety Gates

**Stage 2 (Approvals)** - Hard pause requiring human sign-off:
- Under ₹50,000 → Single Manager approval
- ₹50,000–₹5,00,000 → Manager approval
- Over ₹5,00,000 → Sequential Manager + CFO approvals

**Stage 8 (Awarding)** - Hard pause requiring buyer confirmation:
- Orchestrator presents recommended winning vendor
- Buyer clicks "Confirm" via webhook to proceed to PO generation

## Key Features

✅ **Stateless Sub-Agents**: No agent maintains state between calls  
✅ **Database-Backed State**: Single source of truth in PostgreSQL  
✅ **Strict Stage Ordering**: Cannot skip stages; progression is sequential  
✅ **HITL Enforcement**: Hard pauses at approval & award stages  
✅ **Clarification Routing**: Buyers can answer agent questions mid-pipeline  
✅ **Real-Time Auctions**: WebSocket streaming + asyncio timers + row locking  
✅ **Historical Queries**: Non-destructive lookups of prior pipeline state  
✅ **Audit Logging**: Every action logged with actor, timestamp, payload  
✅ **Single-Vendor Fulfillment**: One RFQ/Auction = one winning vendor (no splits)  
✅ **Currency Normalization**: All values in INR (MVP scope)  

## File Structure

```
procaby_new/
├── app/
│   ├── __init__.py
│   ├── main.py                 # FastAPI app entry
│   ├── config.py              # Settings from .env
│   ├── database.py            # SQLAlchemy setup
│   ├── models/
│   │   ├── procurement.py      # Main pipeline state model
│   │   ├── vendor.py           # Vendor bid tracking
│   │   └── audit.py            # Audit log model
│   ├── schemas/                # Pydantic request/response schemas
│   ├── orchestrator/
│   │   ├── engine.py          # Core state machine (450+ lines)
│   │   ├── router.py          # Stage routing logic
│   │   └── exceptions.py       # Custom exceptions
│   ├── agents/                 # 9 stateless sub-agents
│   │   ├── base.py
│   │   ├── intake.py
│   │   ├── approvals.py
│   │   ├── pr_agent.py
│   │   ├── cart.py
│   │   ├── event.py
│   │   ├── quote.py
│   │   ├── negotiation.py
│   │   ├── awarding.py
│   │   └── po.py
│   ├── api/                    # REST + WebSocket endpoints
│   │   ├── procurement.py
│   │   ├── webhooks.py
│   │   └── websocket.py
│   └── utils/
│       └── auction_timer.py    # Asyncio countdown for auctions
├── alembic/                    # Database migrations
│   ├── env.py
│   └── versions/
├── requirements.txt
├── .env.example
└── README.md
```

## Development Notes

- **Agent Framework**: All agents inherit from `BaseAgent` and return `AgentResult` with status/fields/message
- **Stage Progression**: Orchestrator auto-advances non-interactive stages (PR, Cart, Negotiation)
- **Concurrency**: PostgreSQL `SELECT FOR UPDATE` used in bid submissions to prevent race conditions
- **Async Throughout**: Built on FastAPI async/await for high concurrency
- **No Caching**: State always read fresh from DB on every stage run

## Future Extensions

- LLM-powered agents (Claude API integration for natural language parsing)
- Redis PubSub for distributed deployments
- Batch procurement workflows
- Split-order capability (multiple winners)
- Dynamic approval routing based on cost center / department
- Email/Slack notifications at HITL gates
- Advanced analytics dashboard (bid trends, vendor performance)
- Multi-currency support
