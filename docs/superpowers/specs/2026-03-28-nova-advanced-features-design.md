# NOVA Advanced Features Design
**Date:** 2026-03-28
**Status:** Approved
**Scope:** Sales Digest, Persistent Memory, Proactive Follow-ups

---

## Context

NOVA is a WhatsApp-based personal assistant running on a Hetzner VPS. It uses Claude Haiku 4.5, FastAPI, PostgreSQL, APScheduler, and Google APIs (Calendar, Gmail). The goal is to make NOVA proactive and context-aware — moving from purely reactive request-response to an assistant that tracks business metrics, remembers important facts, and initiates relevant actions.

---

## System 1: Sales Digest

### Purpose
Raunk manually pastes daily iwishbag sales data into WhatsApp. NOVA parses it, stores it in a structured DB table, and uses it for trend analysis and target tracking (goal: 30L/month revenue).

### Data Model

New table: `SalesData`

| Column | Type | Notes |
|--------|------|-------|
| id | INTEGER PK | |
| date | DATE UNIQUE | The sales date |
| revenue | FLOAT | In Rs. |
| orders | INTEGER | Order count |
| quotes | INTEGER | Quote count |
| cogs | FLOAT | Cost of goods sold |
| notes | TEXT | Optional free-text |
| created_at | TIMESTAMP | UTC |

### Tool: `sales`

Three actions:

**`log`** — Save a sales entry
- Input: `date` (YYYY-MM-DD or "yesterday"), `revenue`, `orders`, `quotes` (optional), `cogs` (optional), `notes` (optional)
- NOVA calls this automatically when user pastes sales data
- Upserts (updates existing entry for same date)

**`summary`** — Query stats
- Input: `period` ("today", "this_week", "this_month", "last_7_days", "last_30_days")
- Returns: total revenue, orders, daily average, % of monthly 30L target reached
- Compares vs. same period last month if data available

**`trend`** — Compare two periods
- Input: `period_a`, `period_b` (e.g., "this_week" vs "last_week")
- Returns: side-by-side comparison with % change

### Evening Sales Digest (8pm NPT)
The end-of-day wrap (see Proactivity section) includes today's sales entry if logged. If not logged by 8pm, NOVA sends: *"No sales data for today yet — want to log it?"*

### Agent Integration
- Add `sales` to action keywords in `_ACTION_PATTERNS` (regex in `agent.py`)
- Add to Commander system prompt: *"When user pastes sales figures, call the sales tool to log them"*

---

## System 2: Persistent Memory & Context

### Purpose
NOVA remembers facts about Raunk across all conversations: preferences, goals, people, and active projects. Every Commander session loads relevant memory and injects it into the system prompt. NOVA auto-saves new facts she learns.

### Storage
Uses the existing `NovaContext` table (key-value store). No schema changes needed.

**Key naming convention:**

| Prefix | Example key | Example value |
|--------|-------------|---------------|
| `pref:` | `pref:meeting_times` | Prefers mornings, avoids Fridays |
| `goal:` | `goal:revenue_target` | 30L/month from iwishbag by Q3 2026 |
| `person:` | `person:raj_sharma` | Investor contact, Kathmandu, met March 2026, discussing Series A |
| `project:` | `project:iwishbag` | E-commerce bags brand, target 30L/month, currently at ~50K/day |
| `context:` | `context:general` | General facts about Raunk not fitting other categories |

### Tool: `memory`

Three actions:

**`remember`** — Save or update a fact
- Input: `key` (namespaced, e.g. `person:raj_sharma`), `value` (text, max ~200 chars)
- Upserts the NovaContext row

**`recall`** — Retrieve facts
- Input: `pattern` (prefix to filter, e.g. `person:` returns all person entries, or full key for exact lookup)
- Returns: matching key-value pairs

**`forget`** — Delete a fact
- Input: `key`
- Removes the NovaContext row

### Auto-extraction
System prompt instructs NOVA to call `memory.remember` when she learns:
- A new preference ("I prefer morning meetings" → `pref:meeting_times`)
- A goal or target ("I want 30L/month" → `goal:revenue_target`)
- A person fact ("Raj is an investor from Sequoia" → `person:raj`)
- A project update ("iwishbag launch delayed to April" → `project:iwishbag`)

### Dynamic Context Injection
Replace single `raunak_info` key injection with full multi-key load:

```python
# Before each Commander call, load all memory keys
all_context = await get_all_context(session)  # new DB helper
# Format as structured block injected into system prompt
```

New DB helper: `get_all_context(session) -> dict[str, str]` — returns all NovaContext rows as a dict.

---

## System 3: Proactive Follow-ups

### Purpose
NOVA initiates on four triggers rather than waiting to be asked. All jobs live in `app/proactive.py` as module-level async functions registered in `main.py` at startup.

### Jobs

#### Job 1: Unanswered Email Check
- **ID:** `proactive_unanswered_emails`
- **Schedule:** Daily 10:00am NPT
- **Logic:**
  1. Search Gmail for `is:inbox is:unread older_than:2d` (48+ hrs old, unread)
  2. Filter to max 3 most important (by sender keywords: investor, client, partner)
  3. If any found → send WhatsApp: *"📧 3 emails need your attention (48hrs+): [sender — subject] ..."*
  4. If none → silent (no message)

#### Job 2: Post-Meeting Follow-up
- **ID:** `proactive_post_meeting`
- **Schedule:** Every 30 minutes
- **Logic:**
  1. Fetch calendar events that ended in the last 30 minutes
  2. For each event with ≥1 attendee → send WhatsApp: *"📅 [Meeting title] just ended. Want me to send a follow-up or log notes?"*
  3. Skip all-day events and events with no attendees (solo blocks)

#### Job 3: Contact Check-ins
- **ID:** `proactive_contact_checkins`
- **Schedule:** Monday 9:00am NPT
- **Logic:**
  1. Query Contact table for non-blocked contacts with `last_seen < 14 days ago`
  2. Filter to VIP contacts first, then others
  3. If any → send WhatsApp list: *"👥 Haven't heard from these contacts in 2+ weeks: [names] — want me to reach out?"*
  4. Limit to top 5 contacts

#### Job 4: End-of-Day Wrap
- **ID:** `proactive_eod_wrap`
- **Schedule:** Daily 8:00pm NPT
- **Logic:**
  1. Pull today's calendar events (completed)
  2. Pull today's sales entry from SalesData (if exists)
  3. Pull any pending reminders due tomorrow
  4. Format and send WhatsApp summary:
     ```
     🌙 End of Day — [date]

     ✅ DONE TODAY
     • 10am — Sync with team
     • 2pm — Investor call

     📊 SALES TODAY
     • Revenue: Rs. 50.6K (target pace: Rs. 1L/day for 30L month)

     ⏰ TOMORROW
     • 9am reminder: Weekly review
     ```
  5. If no data for any section → omit that section silently

### All jobs: send only if there's something worth reporting. No empty pings.

---

## Implementation Order

1. `app/memory.py` — add `get_all_context()` helper
2. `app/tools/memory_tool.py` — new tool
3. `app/tools/sales_tool.py` — new tool + `SalesData` model in `memory.py`
4. `app/tools/__init__.py` — register both tools
5. `app/agent.py` — update system prompt + dynamic context injection
6. `app/proactive.py` — 4 job functions
7. `main.py` — register 4 proactive jobs at startup

---

## Files Modified / Created

| File | Change |
|------|--------|
| `app/memory.py` | Add `SalesData` model, `save_sales`, `get_sales_summary`, `get_all_context` |
| `app/tools/memory_tool.py` | New — `memory` tool |
| `app/tools/sales_tool.py` | New — `sales` tool |
| `app/tools/__init__.py` | Register 2 new tools |
| `app/agent.py` | Updated system prompt, dynamic context injection |
| `app/proactive.py` | New — 4 proactive job functions |
| `main.py` | Register 4 proactive APScheduler jobs |

---

## Testing

1. Start server: `python main.py` — confirm all 5 scheduled jobs appear in logs (morning briefing + 4 proactive)
2. **Memory:** Tell NOVA "I prefer 9am meetings" → check NovaContext table for `pref:` key
3. **Sales:** Paste sales data → NOVA calls `sales.log` → query `SELECT * FROM sales_data`
4. **Sales summary:** Ask "how are sales this month?" → NOVA calls `sales.summary`
5. **EOD wrap:** Trigger manually via `ssh nova-vps "cd nova-pa && python -c 'import asyncio; from app.proactive import _end_of_day_wrap; asyncio.run(_end_of_day_wrap())'"` → confirm WhatsApp received
6. **Unanswered emails:** Same manual trigger pattern for `_check_unanswered_emails`
