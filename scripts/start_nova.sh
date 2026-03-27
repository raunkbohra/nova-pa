#!/bin/bash
# =============================================================================
# Start NOVA with PM2 (app + tunnel together)
# =============================================================================
# Run after setup_vps.sh and start_tunnel.sh are complete.
# =============================================================================
set -e

NOVA_DIR="$HOME/nova-pa"
cd "$NOVA_DIR"

# Activate venv
source venv/bin/activate

echo "Starting NOVA..."

# Stop existing processes if running
pm2 delete nova 2>/dev/null || true
pm2 delete nova-tunnel 2>/dev/null || true

# Initialize DB tables
echo "Initializing database tables..."
python3 -c "
import asyncio
from sqlalchemy.ext.asyncio import create_async_engine
from app.config import settings
from app.memory import Base

async def init():
    engine = create_async_engine(settings.database_url, echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    await engine.dispose()
    print('  Tables created')

asyncio.run(init())
"

# Start using ecosystem config
pm2 start ecosystem.config.js --env production

# Save PM2 config so it survives reboots
pm2 save

# Enable PM2 startup on boot
pm2 startup systemd -u ubuntu --hp /home/ubuntu 2>/dev/null || \
pm2 startup systemd 2>/dev/null || true

echo ""
pm2 list
echo ""
echo "NOVA is running!"
echo ""
echo "Quick checks:"
echo "  curl http://localhost:8000/health"
echo "  pm2 logs nova --lines 20"
echo "  pm2 logs nova-tunnel --lines 10"
