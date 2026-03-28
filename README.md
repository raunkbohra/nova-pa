# NOVA — WhatsApp AI Executive Assistant

**NOVA** is a dual-mode WhatsApp personal assistant for Raunk Bohra, running 24/7 on Hetzner with Cloudflare Tunnel. Powered by Claude Opus 4.6, NOVA handles calendar, email, notes, reminders, and intelligently routes external contacts like a sharp executive assistant.

## Quick Links

- **Full Specification:** [`docs/NOVA-spec.md`](docs/NOVA-spec.md)
- **Two Modes:**
  - **Commander Mode** — Raunak messages NOVA for work management (calendar, email, notes, research)
  - **Receptionist Mode** — External contacts reach NOVA, who qualifies, gates, and books meetings

## Key Features

✅ Real-time calendar management (Google Calendar)
✅ Email integration (Gmail — read, search, draft, send)
✅ Notes with full-text search (PostgreSQL)
✅ Smart reminders (APScheduler, survives restarts)
✅ Voice notes + transcription (Whisper)
✅ Weather & news (OpenWeatherMap, NewsAPI)
✅ Intelligent receptionist (qualification flow, VIP routing)
✅ Missed call auto-response
✅ Abuse prevention (rate limits, prompt injection guards)

## Infrastructure

- **VPS:** Hetzner CX22 (€4/mo)
- **Tunnel:** Cloudflare Tunnel (free)
- **Database:** PostgreSQL (existing VPS)
- **Process Manager:** PM2
- **API:** Meta Cloud API (WhatsApp)
- **AI Brain:** Claude Opus 4.6 with adaptive thinking

## Implementation

Begin with **Phase 1** in the spec: project scaffold, requirements, config, database schema, webhook skeleton.

```bash
# Phase 1 starts here
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

## Deployment

```bash
ssh user@hetzner-vps
cd /path/to/nova
git pull
pm2 restart nova
```

---

**Spec approved 2026-03-27.** Ready for Phase 1 implementation.
