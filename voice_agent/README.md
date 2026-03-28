# NOVA Voice Agent

Answers phone calls via Vobiz (Indian DID) + LiveKit + Claude.

## Setup

### 1. Add these to `.env`:
```
LIVEKIT_URL=wss://your-project.livekit.cloud
LIVEKIT_API_KEY=your_key
LIVEKIT_API_SECRET=your_secret
VOBIZ_SIP_DOMAIN=a32d2301.sip.vobiz.ai
VOBIZ_SIP_USERNAME=nova_agent
VOBIZ_SIP_PASSWORD=your_password
VOBIZ_PHONE_NUMBER=+911171366938
```

### 2. Install dependencies:
```bash
pip install -r voice_agent/requirements.txt
```

### 3. Run one-time setup (creates LiveKit trunks + dispatch):
```bash
python voice_agent/setup_livekit.py
```

### 4. Configure Vobiz inbound destination:
Set the LiveKit SIP URI as the inbound destination on the Vobiz trunk (script prints the exact command).

### 5. Start the agent:
```bash
python voice_agent/agent.py dev
```

## Architecture
```
Phone call → Vobiz (+911171366938) → LiveKit SIP → Voice Agent → Claude
```

## PM2 (production):
```bash
pm2 start voice_agent/agent.py --name nova-voice --interpreter ./venv/bin/python3 -- start
```
