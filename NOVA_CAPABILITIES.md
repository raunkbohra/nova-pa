# NOVA — Full Capabilities Reference

> NOVA is Raunak Bohra's WhatsApp-based executive assistant, powered by Claude Haiku 4.5.
> All interaction happens via WhatsApp. Timezone: **NPT (Asia/Kathmandu, UTC+5:45)**.

---

## How to Talk to NOVA

Just message naturally. NOVA understands plain English. You don't need commands or keywords — but they help trigger the right tool faster.

---

## 1. Calendar (Google Calendar)

**What you say → what NOVA does**

| Example Message | Action |
|---|---|
| "What's on today?" | Lists today's events |
| "What's free this week for 2 hours?" | Finds open slots |
| "Schedule Raj for 30 min this Friday at 3pm" | Creates event |
| "Cancel my 2pm meeting" | Deletes event by name |
| "Brief me on my 3pm" | Gets event details |

**Supports:** list, create, cancel, find free slots, get event details.
Natural language time parsing: "tomorrow at 10am", "this Friday 3pm", ISO format.

---

## 2. Email (Gmail)

| Example Message | Action |
|---|---|
| "Show me my unread emails" | Lists inbox (up to 10) |
| "Search for emails from Sequoia" | Full Gmail query search |
| "What did Raj say in his last email?" | Reads full email body |
| "Draft a reply to Amit saying I'll confirm by Friday" | Creates Gmail draft |
| "Send email to raj@example.com: [text]" | Sends email |
| "Delete email from XYZ newsletter" | Moves to trash |
| "Triage my inbox" | Scores unread by priority |

**Triage scoring:**
- 🔴 Urgent — investors, VCs, partners, term sheets, contracts, deals
- 🟡 Normal — everything else
- ⚪ Low — newsletters, noreply, promos, digests

**Delete:** moves to trash by default. Permanent deletion available but NOVA confirms first.

---

## 3. WhatsApp Messaging

| Example Message | Action |
|---|---|
| "Send Raj a WhatsApp: meeting is postponed" | Sends immediately |
| "Message +9779823377223 saying I'll call at 5" | Sends immediately |
| "Schedule a WA to Raj at 3pm saying call me" | Queues delivery |
| "Send [number] tomorrow 9am: check the orders" | Scheduled send |

**Scheduled delivery:** Uses APScheduler + PostgreSQL. Survives server restarts.
Time formats: "3pm", "tomorrow 9am", "2026-04-01 10:00".
Phone format: E.164 (e.g. +9779823377223).

---

## 4. Reminders

| Example Message | Action |
|---|---|
| "Remind me at 4pm to check orders" | One-time reminder |
| "Remind me every morning at 9am to review tasks" | Recurring (daily) |
| "Remind me every Monday at 8am for weekly review" | Recurring (weekly) |

**Persistence:** Reminders survive server restarts (stored in PostgreSQL via APScheduler).
**Delivery:** Sends WhatsApp message to Raunak's phone at the scheduled time.

---

## 5. Notes (Second Brain)

| Example Message | Action |
|---|---|
| "Note: Series A target ₹5Cr, timeline Q3" | Saves note |
| "Save to notes: meeting with Raj — discussed expansion" | Saves note with title |
| "What did I note about Project Alpha?" | Full-text search |
| "Find my notes on fundraising" | Tag/content search |

**Tagging:** include tags in message, e.g. "Note [investment, q3]: ..."
**Search:** full-text across title, content, and tags.

---

## 6. Memory (Persistent Facts)

NOVA remembers things across conversations. Organized by key prefix:

| Key pattern | Used for |
|---|---|
| `pref:...` | Your preferences |
| `goal:...` | Goals and targets |
| `person:...` | People you know |
| `project:...` | Project updates |

| Example Message | Action |
|---|---|
| "Remember I prefer short replies" | Saves preference |
| "My fundraising target is ₹5Cr" | Saves goal |
| "Remember Raj is from Matrix Partners" | Saves person info |
| "What do you know about Raj?" | Recalls person memory |
| "What do you remember?" / `/memory` | Shows all saved keys |
| "Forget my pref:replies setting" | Deletes a memory key |

---

## 7. Tasks (Google Tasks)

| Example Message | Action |
|---|---|
| "Show my tasks" / `/tasks` | Lists all pending tasks |
| "Add task: follow up with Sequoia by Friday" | Creates task with due date |
| "Done with the Sequoia follow-up" | Marks task complete |

**Due dates:** today, tomorrow, or any natural date.

---

## 8. Sales Tracking (iwishbag)

Monthly target: **Rs. 30L (3,000,000)**. NOVA always shows % of target.

| Example Message | Action |
|---|---|
| "Sales today: Rs. 52,000, 18 orders" | Logs today's sales |
| "How are sales this month?" | Month summary + % of target |
| "Compare this week vs last week" | Side-by-side trend |
| `/sales` | Instant today + month snapshot |

**Fields you can log:** revenue, orders, quotes, COGS (cost of goods sold), notes.
**When COGS provided:** NOVA shows gross profit and margin %.

---

## 9. Expenses & Profit

| Example Message | Action |
|---|---|
| "Spent Rs. 8,000 on Facebook ads today" | Logs expense (category: ads) |
| "Rs. 3,500 on packaging" | Logs expense (category: packaging) |
| "What's my actual profit this month?" | Revenue − COGS − expenses = net |
| "Show expense summary" | Breakdown by category |

**Categories auto-detected** from message context (ads, packaging, logistics, salaries, misc).

---

## 10. Google Drive

| Example Message | Action |
|---|---|
| "Find the investor deck in Drive" | Searches Drive by name |
| "Read the Q1 report doc" | Reads Google Doc content |
| "Open the orders spreadsheet" | Reads Google Sheet (first 50 rows) |

**Supported:** Google Docs, Google Sheets, Drive file search.
Accepts full Drive URLs or just file names.

---

## 11. Reading List

Save URLs to read later, organized and summarized on demand.

| Example Message | Action |
|---|---|
| "Save this for later: https://..." | Saves URL |
| "What's on my reading list?" | Lists unread items with IDs |
| "Summarize reading list item 3" | Fetches + summarizes via Perplexity (cached) |
| "Mark item 3 as read" | Removes from unread list |

**Tags:** "Save this for later [vc, india]: https://..." adds tags for filtering.

---

## 12. Research & Web

| Example Message | Action |
|---|---|
| "Research Sequoia India's latest portfolio" | Perplexity web search |
| "What's the current RBI repo rate?" | Web search |
| "Summarize this: https://..." | Fetches and summarizes URL |
| Just paste a URL | Auto-detected, summarized |
| "Latest news on D2C brands India" | News headlines |
| "What's the weather in Kathmandu?" | Current weather + forecast |

---

## 13. External Contacts (Receptionist Mode)

When anyone messages NOVA's WhatsApp number (not Raunak's), NOVA handles them:

- Greets and qualifies (name, company, purpose)
- **Strong signal** (investor, client, partner) → auto-books a meeting
- **Unclear** → pings Raunak for approval
- **Spam/cold pitch** → politely declines, doesn't ping
- VIP numbers → skip qualification, auto-book
- "URGENT" messages → always pings Raunak immediately

NOVA also auto-extracts name/company/purpose from each conversation and saves to memory.

**Raunak can review contacts anytime:**

| Example Message | Action |
|---|---|
| "Who messaged me recently?" | Lists recent external contacts |
| "Show me what John said" | Full conversation thread by name |
| "Read thread with +91XXXXXXXXXX" | Full thread by phone |

---

## 14. Image / Vision

Send any image to NOVA and it will:
- Describe what's in the image
- Flag any action items
- Extract text (invoices, screenshots, business cards, etc.)

---

## 15. Slash Commands (Instant, No AI Loop)

Fast shortcuts — no processing delay.

| Command | What it does |
|---|---|
| `/help` | Lists all slash commands |
| `/brief` | Triggers morning briefing now |
| `/tasks` | Lists pending Google Tasks |
| `/sales` | Today + this month sales snapshot |
| `/memory` | Shows all saved memory keys |
| `/cost` | API token usage + estimated cost (last 30 days) |
| `/remind 3pm check orders` | Quick reminder (passes to agent) |

---

## 16. Proactive Jobs (NOVA Initiates Without Being Asked)

These run automatically on a schedule:

| Job | Schedule | What it does |
|---|---|---|
| Morning Brief | Daily 7am NPT | Today's calendar, unread emails, weather, news, tasks |
| Unanswered Emails | Daily 10am NPT | Flags emails 48hrs+ unread (investor/client priority) |
| Pre-Meeting Prep | 30 min before each event | Researches attendees via Perplexity, sends briefing |
| Post-Meeting Follow-up | Every 30 min | Detects recently ended meetings, prompts for notes/actions |
| Sales Pace Check | Daily 6pm NPT | Alerts if behind daily target to hit 30L/month |
| Contact Check-ins | Mondays 9am NPT | Flags contacts not heard from in 14+ days |
| End-of-Day Wrap | Daily 8pm NPT | Day summary: meetings done, emails, tasks, sales |
| Weekly Review | Mondays 8am NPT | Week recap, goals progress, sales vs target |
| Monthly Sales Report | 1st of each month | Full month summary, margin, target hit/miss |

---

## Infrastructure

| Component | Detail |
|---|---|
| AI Model | Claude Haiku 4.5 (`claude-haiku-4-5-20251001`) |
| Server | Hetzner VPS, managed by PM2 |
| Database | PostgreSQL (async SQLAlchemy 2.0) |
| Scheduler | APScheduler + PostgreSQL job store (survives restarts) |
| WhatsApp | Meta Cloud API webhooks |
| Google APIs | Calendar, Gmail, Drive, Docs, Sheets, Tasks (OAuth2) |
| Timezone | NPT — Asia/Kathmandu (UTC+5:45) |

---

*Last updated: March 2026*
