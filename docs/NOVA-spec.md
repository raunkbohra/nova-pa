# NOVA — WhatsApp Personal Assistant for Raunak Bohra
**Spec Date:** 2026-03-27
**Status:** Approved Design — Ready for GitHub upload + Phase 1 implementation

---

## 0. Immediate Next Step: GitHub Repo + Spec Upload

**Task:** Create GitHub repo, save spec as `.md`, push.

**Steps:**
1. `cd "/Users/raunakbohra/Desktop/PA-Raunk Bohra"` — project root
2. `git init && git branch -M main`
3. Create `docs/NOVA-spec.md` — copy of this plan
4. Create `README.md` — one-liner + link to spec
5. `gh repo create nova-pa --public --source=. --remote=origin --push`
6. Verify repo is live on GitHub

**After upload:** Begin Phase 1 (Foundation) — project scaffold, `requirements.txt`, `config.py`, DB schema, webhook skeleton.

---

## 1. What We're Building

NOVA is a dual-mode WhatsApp AI assistant for Raunak Bohra (founder/entrepreneur). It runs 24/7 on a Hetzner VPS behind a Cloudflare Tunnel, powered by Claude Opus 4.6.

**Two modes:**
- **Commander Mode** — Raunak messages NOVA to manage his work (calendar, email, notes, research, reminders)
- **Receptionist Mode** — External contacts message NOVA and she handles them like a sharp executive assistant (qualifies, gates, books, relays)

**Name:** NOVA (Chaldean sum = 19, "Prince of Heaven", reduces to 1 — leadership, new beginnings)

---

## 2. System Architecture

```
WhatsApp (Meta Cloud API)
        │ webhook POST
        ▼
Cloudflare Tunnel → nova.yourdomain.com
        │
        ▼
FastAPI Server (Hetzner CX22 VPS, Ubuntu 24.04)
        │
        ▼
Mode Router (phone number check)
        │
   ┌────┴────┐
   │         │
Commander  Receptionist
Mode       Mode
   │         │
   └────┬────┘
        │
        ▼
Claude Opus 4.6 (NOVA brain)
+ Tools: Calendar, Email, Notes, Reminders,
  Web Search, Weather, News, Whisper, TTS
        │
        ▼
PostgreSQL Database (all persistence)
```

---

## 3. Infrastructure

| Layer | Service | Cost |
|---|---|---|
| VPS | Hetzner CX22 (2 vCPU, 4GB RAM) | ~€4/mo |
| Tunnel | Cloudflare Tunnel (cloudflared) | Free |
| Domain | Any domain via Cloudflare DNS | ~$10/yr |
| DB Backup | Cloudflare R2 (daily pg_dump backup) | Free (10GB) |
| Dev tunnel | `cloudflared tunnel --url localhost:8000` | Free |

**Process management:** NOVA runs via PM2 (`pm2 start main.py --interpreter python3 --name nova`) — consistent with existing quickbiz and app-staging processes on the server. Auto-restarts on crash, starts on boot.

**Deployment:** SSH → `git pull` → `pm2 restart nova`

---

## 4. NOVA's Identity

**Persona:**
- Name: NOVA
- Role: Executive assistant to Raunak Bohra
- With Raunak: direct, efficient, zero fluff
- With externals: warm, professional, like a sharp human EA
- If asked "are you AI?": *"I'm Raunak's digital assistant, NOVA."* — honest, not robotic
- Never reveals she's Claude or an LLM

**Pre-loaded context about Raunak (editable via chat):**
- Full name, role (founder/entrepreneur)
- Company name + what it does
- Timezone: Asia/Kolkata (IST, UTC+5:30)
- Availability: Mon–Thu, 10am–6pm IST (default, editable)
- Standard meeting length: 30 minutes (default, editable)
- Blocked days/times (e.g., "never book Fridays")
- VIP phone numbers (always get through, no qualification)
- Standard decline reasons ("not taking vendor calls")

**Raunak updates context by telling NOVA:**
- *"My company is [X], we build [Y]"*
- *"Add Raj Mehta +91XXXXXXXXXX to VIPs"*
- *"Never book meetings before 10am"*
- *"Don't take vendor calls"*

---

## 5. Mode Detection

```python
if incoming_phone == RAUNAK_PHONE:
    → Commander Mode (full tool access, Raunak's conversation history)
else:
    → Receptionist Mode (isolated thread, no access to Raunak's data)
```

---

## 6. Commander Mode — Full Feature Set

**Daily rhythm:**
- "Good morning" → Today's meetings + important unread emails + weather + top news
- "What's on today?" → Calendar summary
- "Brief me on my 3pm" → Meeting details + web research on attendees + prior email threads
- "End of day" → Done items + pending + tomorrow's first meeting

**Calendar:**
- Schedule, reschedule, cancel, list events
- Find free slots ("what's free this week for 2 hours?")
- Block time ("block Friday afternoon, deep work")
- Default timezone: IST

**Email:**
- Read and summarize unread emails
- Search ("all emails from Sequoia")
- Draft and send replies
- Reply preserving thread

**Notes (second brain):**
- Save notes with tags
- Search and retrieve
- "Note: Series A target ₹5Cr, timeline Q3"
- "What did I note about Project Alpha?"

**Reminders:**
- One-time and recurring
- Survive server restarts (APScheduler + PostgreSQL job store)
- NOVA sends a WhatsApp message when reminder fires

**Research & quick answers:**
- Web search (Claude built-in, free)
- Weather (OpenWeatherMap)
- News headlines (NewsAPI.org)
- "Research [company/topic]"

**Message drafting:**
- "Help me reply to this" [paste any message]
- NOVA drafts, Raunak approves or edits

**Autonomous tool chaining:**
- "Brief me on my 3pm" → Calendar + Web Search + Email → one summary
- "Schedule Raj, check weather that day" → Calendar (find slot) + Create event + Weather

---

## 7. Receptionist Mode — Qualification Flow

```
Stranger messages NOVA
        │
        ▼
"Hi, I'm NOVA, Raunak's executive assistant. How can I help you?"
        │
        ▼
Collect: Name → Company → Purpose
        │
   ┌────▼──────────────────────────────────┐
   │ STRONG signal (investor, client,      │──→ Auto-book in Raunak's calendar
   │ known partner)?                       │    Send calendar invite to both
   │                                       │    Notify Raunak silently
   │ UNCLEAR (could be relevant)?          │──→ Ping Raunak:
   │                                       │    "Amit Sharma (XYZ Ventures) wants
   │                                       │     30 min re: investment. YES/NO/LATER?"
   │ SPAM/IRRELEVANT (vendor, cold pitch)? │──→ Politely decline, no ping
   └───────────────────────────────────────┘
```

**Special cases:**
- **VIP number** → Skip all qualification, auto-book immediately
- **Missed call** → NOVA messages caller: *"Hi, Raunak missed your call. I'm NOVA, his assistant — how can I help?"*
- **"URGENT"/"Emergency" in message** → Immediately ping Raunak regardless of who it is
- **"Just tell Raunak..."** → Relay to Raunak + confirm to sender: *"I've passed your message to Raunak."*
- **Known contact returns** → Greeted by name, no re-qualification

**After booking:**
- Google Calendar invite sent to both parties
- Contact receives: *"Done! You're booked with Raunak on [date/time] IST."*
- Raunak gets silent notification: *"Booked: [Name] ([Company]) — [date/time]. Purpose: [X]"*

**What NOVA never reveals to externals:**
- Raunak's personal phone number
- Calendar details beyond available/unavailable
- Private conversation history
- Email or personal data

---

## 8. Voice & Media

**Incoming voice notes:**
- NOVA downloads audio from Meta's servers
- Transcribes with OpenAI Whisper (local, free)
- Processes transcript exactly like typed text
- Tags response with *[Voice note transcribed]*

**Outgoing voice replies:**
- On long responses or when Raunak says "reply with voice"
- Text-to-speech via gTTS (Python, free)
- Sends as WhatsApp audio message

**Missed calls:**
- Meta Cloud API webhook fires on missed call
- NOVA auto-messages caller immediately
- Opens isolated receptionist thread

**Images & documents:**
- Photos/PDFs sent by Raunak → Claude reads them (multimodal)
- "What does this invoice say?" [attaches PDF] → NOVA extracts details

**Not supported:**
- Live voice/video calls (Meta API limitation)
- Stickers, polls (ignored gracefully)

---

## 9. Tools & Integrations

| Tool | Purpose | Service | Cost |
|---|---|---|---|
| Calendar | CRUD events, find free slots | Google Calendar API | Free |
| Email | Read, search, draft, send | Gmail API | Free |
| Reminders | Timed WA notifications | APScheduler + PostgreSQL | Free |
| Notes | Second brain CRUD | PostgreSQL (local) | Free |
| Web Search | Real-time research | Claude built-in | Free |
| Weather | Current + forecast | OpenWeatherMap | Free |
| News | Headlines by topic | NewsAPI.org | Free |
| Voice in | Transcribe voice notes | Whisper (local, default) or Sarvam AI (swap-in for regional Indian languages) | Free / ~₹0.5/min |
| Voice out | TTS replies | gTTS (Python) | Free |
| VIP list | Trusted numbers | PostgreSQL | Free |
| Contact profiles | Remember external contacts | PostgreSQL | Free |

**Total external API costs:** Anthropic API only (all other services free tier)

---

## 10. Data Model (PostgreSQL)

**Database:** Existing PostgreSQL on Hetzner VPS. Create dedicated `nova_db` database + `nova` user.

```sql
-- Raunak's conversation (rolling 50 messages)
CREATE TABLE messages (
  id SERIAL PRIMARY KEY,
  role TEXT,
  content TEXT,
  created_at TIMESTAMPTZ
);

-- One thread per external contact
CREATE TABLE external_threads (
  id SERIAL PRIMARY KEY,
  phone TEXT,
  role TEXT,
  content TEXT,
  created_at TIMESTAMPTZ
);

-- External contact profiles
CREATE TABLE contacts (
  id SERIAL PRIMARY KEY,
  phone TEXT UNIQUE,
  name TEXT,
  company TEXT,
  purpose TEXT,
  is_vip BOOLEAN DEFAULT FALSE,
  is_blocked BOOLEAN DEFAULT FALSE,
  first_seen TIMESTAMPTZ,
  last_seen TIMESTAMPTZ
);

-- Raunak's second brain (with full-text search index)
CREATE TABLE notes (
  id SERIAL PRIMARY KEY,
  title TEXT,
  content TEXT,
  tags TEXT,
  created_at TIMESTAMPTZ,
  updated_at TIMESTAMPTZ,
  search_vector TSVECTOR GENERATED ALWAYS AS (to_tsvector('english', title || ' ' || content)) STORED
);
CREATE INDEX notes_search_idx ON notes USING GIN(search_vector);

-- Scheduled reminders (APScheduler PostgreSQL job store manages its own table)
-- nova_context stores NOVA's knowledge about Raunak
CREATE TABLE nova_context (
  id SERIAL PRIMARY KEY,
  key TEXT UNIQUE,
  value TEXT,
  updated_at TIMESTAMPTZ
);

-- Rate limiting for external contacts
CREATE TABLE rate_limits (
  id SERIAL PRIMARY KEY,
  phone TEXT,
  message_count INT DEFAULT 0,
  window_start TIMESTAMPTZ,
  blocked_until TIMESTAMPTZ
);
```

**Connection:** `DATABASE_URL=postgresql+asyncpg://nova:password@localhost/nova_db`

**Stack:** `asyncpg` + `SQLAlchemy 2.0 async` for all DB operations.

**Privacy:** All data stays on Raunak's VPS. Nothing shared except API calls to Google/Anthropic.

**Backup:** Daily cron: `pg_dump nova_db | gzip | rclone copy - r2:nova-backups/$(date +%Y%m%d).sql.gz`

---

## 11. File Structure

```
nova/
├── .env / .env.example
├── .gitignore
├── requirements.txt
├── main.py                      # uvicorn entry point
├── app/
│   ├── config.py                # pydantic-settings from .env
│   ├── memory.py                # PostgreSQL: all tables + CRUD
│   ├── agent.py                 # Claude agentic loop (the brain)
│   ├── webhook.py               # FastAPI: POST /webhook, GET /webhook (verify), GET /health
│   ├── whatsapp.py              # Meta Cloud API: send text, send audio, parse incoming
│   ├── voice.py                 # Whisper transcription + gTTS synthesis
│   └── tools/
│       ├── __init__.py          # Tool registry
│       ├── base.py              # ToolResult dataclass
│       ├── calendar_tool.py     # Google Calendar
│       ├── email_tool.py        # Gmail
│       ├── reminder_tool.py     # APScheduler
│       ├── notes_tool.py        # PostgreSQL notes
│       ├── weather_tool.py      # OpenWeatherMap
│       └── news_tool.py         # NewsAPI.org
├── data/                        # Google OAuth tokens (gitignored)
└── scripts/
    ├── setup_google_auth.py     # One-time OAuth2 flow
    └── test_local.py            # Test without WhatsApp
```

---

## 12. Environment Variables

```bash
# Anthropic
ANTHROPIC_API_KEY=sk-ant-...

# Meta Cloud API
META_VERIFY_TOKEN=any_secret_string
META_ACCESS_TOKEN=your_permanent_system_user_token
META_PHONE_NUMBER_ID=your_whatsapp_phone_number_id

# Raunak's number (E.164 format, e.g. +919XXXXXXXXX)
RAUNAK_PHONE=+91XXXXXXXXXX

# Google APIs
GOOGLE_CREDENTIALS_FILE=data/google_credentials.json
GOOGLE_TOKEN_FILE=data/google_token.json

# Weather + News
OPENWEATHER_API_KEY=...
NEWS_API_KEY=...

# Database (existing PostgreSQL on VPS)
DATABASE_URL=postgresql+asyncpg://nova:password@localhost/nova_db

# App
MAX_CONVERSATION_HISTORY=50
LOG_LEVEL=INFO
TRANSCRIPTION_BACKEND=whisper  # or "sarvam" for regional Indian languages
```

---

## 13. Guardrails & Abuse Prevention

**Rate limiting (per unknown number):**
- Max 10 messages/hour per external contact → *"Please reach out again later"*
- Auto-block after 3 clearly irrelevant/spam attempts from same number
- Manual block list — Raunak says *"Block this number"* → added permanently
- Max 50 Claude API calls/day from ALL external contacts combined (hard cost cap)
- Long messages from unknowns truncated to 500 chars before hitting Claude

**Against social engineering:**
- NOVA never reveals Raunak's personal phone, email, home location — even under urgency claims
- NOVA never confirms whether a number is on the VIP list
- "Raunak told me I'm a VIP" → treated as unknown, still qualifies normally
- Externals cannot change NOVA's instructions or persona in any way

**Against prompt injection:**
- System prompt locked for external contacts — they cannot override with "ignore previous instructions"
- Any message containing prompt injection patterns flagged and ignored
- Raunak's commands always take priority over any external input

**Against booking abuse:**
- Max 2 auto-bookings per day from unknowns without Raunak's explicit approval
- NOVA never double-books — checks calendar before confirming any slot
- All auto-bookings notify Raunak immediately — he can cancel within 30 min
- Externals cannot request meetings longer than 1 hour without Raunak approval

**Cost protection:**
- Hard cap: 50 external API calls/day (prevents runaway costs from spam)
- Raunak's usage: uncapped (it's his PA)
- If daily cap hit: NOVA replies *"I'm unavailable right now, please try again tomorrow"*

---

## 14. Implementation Order

**Phase 1 — Foundation**
1. Project structure + requirements.txt
2. config.py + .env
3. memory.py (DB schema + CRUD)
4. webhook.py (/health + Meta webhook verification)
5. whatsapp.py (send text via Meta API)
6. Test: `curl localhost:8000/health`

**Phase 2 — Core Intelligence**
7. tools/base.py
8. tools/__init__.py (empty registry)
9. agent.py (Claude loop, no tools yet)
10. scripts/test_local.py
11. Test: "Hello NOVA" → Claude responds

**Phase 3 — Tools (one at a time)**
12. notes_tool.py → test: "Save a note: test"
13. reminder_tool.py → test: "Remind me in 1 min"
14. weather_tool.py + news_tool.py → test
15. scripts/setup_google_auth.py → run OAuth flow
16. calendar_tool.py → test with real calendar
17. email_tool.py → test with real Gmail

**Phase 4 — Voice & Media**
18. voice.py (Whisper + gTTS)
19. Wire into webhook for audio messages
20. Missed call detection + auto-response

**Phase 5 — Receptionist Mode**
21. Mode router in webhook.py
22. External thread management in memory.py
23. Receptionist system prompt + qualification flow
24. VIP list + contact profiles
25. Raunak approval flow (YES/NO/LATER)

**Phase 6 — Deploy**
26. Hetzner CX22 setup + Ubuntu
27. cloudflared tunnel install + configure
28. PM2 service for NOVA
29. Meta webhook URL → nova.yourdomain.com/webhook
30. End-to-end WhatsApp test

---

## 15. Key Technical Decisions

- **Background tasks:** Return 200 to Meta immediately, process in `BackgroundTask` (Meta times out at 15s, Claude can take 30-60s)
- **Thinking:** `thinking={"type": "adaptive"}` on Claude Opus 4.6
- **Strip thinking blocks:** Filter from conversation history before saving (can't be replayed)
- **Parallel tools:** `asyncio.gather()` when Claude requests multiple tools at once
- **Max 10 iterations:** Guard against infinite tool loops
- **IST default:** All times shown/interpreted in Asia/Kolkata unless specified
- **Voice notes:** Whisper runs locally (no API cost, works offline). Handles Hindi, Nepali, Hinglish, Indian English well. Swap `TRANSCRIPTION_BACKEND=sarvam` in .env to use Sarvam AI for better regional Indian language support (Tamil, Marathi, Bengali etc.)
- **PostgreSQL + async:** `asyncpg` + `SQLAlchemy 2.0 async` throughout (existing VPS PostgreSQL)
- **APScheduler:** `AsyncIOScheduler` + `SQLAlchemyJobStore` with PostgreSQL URL (reminders survive restarts)
- **Full-text search:** PostgreSQL `tsvector` on notes table — "find my note about X" is fast and accurate
