# ProcBay Startup Guide

## Prerequisites

- Python 3.10+
- PostgreSQL running locally on port 5432
- `.env` file configured with database credentials

## Installation

```bash
cd C:\Users\lenovo\Downloads\procaby_new

# Install dependencies
pip install -r requirements.txt
```

## Running the System

### Option 1: Two Terminal Windows (Recommended for Development)

**Terminal 1 — FastAPI Backend:**
```bash
cd C:\Users\lenovo\Downloads\procaby_new
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```
✅ Backend ready at `http://localhost:8000`  
📖 API docs at `http://localhost:8000/docs`

**Terminal 2 — Chainlit UI:**
```bash
cd C:\Users\lenovo\Downloads\procaby_new
chainlit run ui.py --port 8001
```
✅ Chat UI ready at `http://localhost:8001`

---

### Option 2: Single Terminal with Background Processes

```bash
# Start backend in background
start uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

# Start UI (foreground)
chainlit run ui.py --port 8001
```

---

## Workflow

1. **Open Chat UI** → `http://localhost:8001`
2. **Type your procurement request** → "I need 500 gloves by end of month"
3. **Chat interface manages the entire pipeline:**
   - ✅ Creates procurement
   - ✅ Extracts line items
   - ✅ Routes for approvals
   - ✅ Collects bids
   - ✅ Negotiates with vendors
   - ✅ Generates PO

---

## Backend API Endpoints (for testing)

```bash
# Create procurement
curl -X POST http://localhost:8000/api/v1/procurement/ \
  -H "Content-Type: application/json" \
  -d '{"buyer_id": "buyer_001", "natural_language_input": "I need 500 gloves"}'

# Get history
curl http://localhost:8000/api/v1/procurement/{procurement_id}/history

# Submit approval (webhook)
curl -X POST http://localhost:8000/api/v1/webhooks/approval \
  -H "Content-Type: application/json" \
  -d '{"procurement_id": "{id}", "approver_id": "mgr_001", "decision": "APPROVED"}'
```

---

## Troubleshooting

**"Connection refused" at localhost:8000?**
- Backend not running. Start it in Terminal 1.

**"Can't connect to database"?**
- Check `.env` DATABASE_URL is correct
- Ensure PostgreSQL is running: `pg_isready -h localhost -p 5432`

**Chainlit shows 404?**
- Backend must be running for the chat to work.

---

## Architecture

```
Chainlit UI (Port 8001)
    ↓
  [ui.py] (httpx async requests)
    ↓
FastAPI Backend (Port 8000)
    ↓
PostgreSQL (Procurement State)
    ↓
9 Stateless Agents
```

Each user message flows through the orchestrator's state machine, managing all 9 procurement stages.
