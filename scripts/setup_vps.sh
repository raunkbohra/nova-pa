#!/bin/bash
# =============================================================================
# NOVA VPS Setup Script — Run ONCE on a fresh Ubuntu 24.04 Hetzner CX22
# =============================================================================
# Usage: bash setup_vps.sh
# Prereqs: SSH access as ubuntu/root, git repo cloned to ~/nova-pa
# =============================================================================
set -e

NOVA_DIR="$HOME/nova-pa"
NOVA_USER="ubuntu"
DB_NAME="nova_db"
DB_USER="nova"
DB_PASS="${NOVA_DB_PASSWORD:-$(openssl rand -base64 24)}"

echo "=========================================="
echo "  NOVA VPS Setup"
echo "=========================================="

# --- 1. System packages ---
echo "[1/8] Installing system packages..."
sudo apt-get update -qq
sudo apt-get install -y -qq \
    python3.12 python3.12-venv python3-pip \
    postgresql postgresql-contrib \
    ffmpeg \
    git curl wget unzip \
    build-essential libssl-dev libffi-dev python3-dev

# --- 2. PostgreSQL setup ---
echo "[2/8] Setting up PostgreSQL..."
sudo systemctl enable postgresql
sudo systemctl start postgresql

sudo -u postgres psql -c "CREATE USER $DB_USER WITH PASSWORD '$DB_PASS';" 2>/dev/null || \
    sudo -u postgres psql -c "ALTER USER $DB_USER WITH PASSWORD '$DB_PASS';"
sudo -u postgres psql -c "CREATE DATABASE $DB_NAME OWNER $DB_USER;" 2>/dev/null || \
    echo "Database $DB_NAME already exists"
sudo -u postgres psql -c "GRANT ALL PRIVILEGES ON DATABASE $DB_NAME TO $DB_USER;"

echo "  DB_USER=$DB_USER"
echo "  DB_PASS=$DB_PASS  ← SAVE THIS"
echo "  DATABASE_URL=postgresql+asyncpg://$DB_USER:$DB_PASS@localhost/$DB_NAME"

# --- 3. Python virtualenv + deps ---
echo "[3/8] Creating virtualenv and installing dependencies..."
cd "$NOVA_DIR"
python3.12 -m venv venv
source venv/bin/activate
pip install --quiet --upgrade pip
pip install --quiet -r requirements.txt

# --- 4. Whisper model download ---
echo "[4/8] Downloading Whisper base model (~140MB)..."
python3 -c "import whisper; whisper.load_model('base')" && echo "  Whisper ready"

# --- 5. cloudflared install ---
echo "[5/8] Installing cloudflared..."
if ! command -v cloudflared &> /dev/null; then
    curl -fsSL https://pkg.cloudflare.com/cloudflare-main.gpg | \
        sudo tee /usr/share/keyrings/cloudflare-main.gpg >/dev/null
    echo 'deb [signed-by=/usr/share/keyrings/cloudflare-main.gpg] https://pkg.cloudflare.com/cloudflared focal main' | \
        sudo tee /etc/apt/sources.list.d/cloudflared.list
    sudo apt-get update -qq && sudo apt-get install -y cloudflared
    echo "  cloudflared $(cloudflared --version)"
else
    echo "  cloudflared already installed: $(cloudflared --version)"
fi

# --- 6. Node.js + PM2 ---
echo "[6/8] Installing Node.js and PM2..."
if ! command -v node &> /dev/null; then
    curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash -
    sudo apt-get install -y -qq nodejs
fi
sudo npm install -g pm2 --quiet
pm2 install pm2-logrotate

# --- 7. .env file ---
echo "[7/8] Creating .env file..."
if [ ! -f "$NOVA_DIR/.env" ]; then
    cat > "$NOVA_DIR/.env" <<EOF
# ============ Anthropic ============
ANTHROPIC_API_KEY=sk-ant-FILL_ME_IN

# ============ Meta Cloud API ============
META_VERIFY_TOKEN=nova_verify_$(openssl rand -hex 8)
META_ACCESS_TOKEN=EAA_FILL_ME_IN
META_PHONE_NUMBER_ID=FILL_ME_IN

# ============ Raunk's number ============
RAUNAK_PHONE=+91XXXXXXXXXX

# ============ Google APIs ============
GOOGLE_CREDENTIALS_FILE=data/google_credentials.json
GOOGLE_TOKEN_FILE=data/google_token.json

# ============ External APIs ============
OPENWEATHER_API_KEY=FILL_ME_IN
NEWS_API_KEY=FILL_ME_IN

# ============ Database ============
DATABASE_URL=postgresql+asyncpg://$DB_USER:$DB_PASS@localhost/$DB_NAME

# ============ App ============
MAX_CONVERSATION_HISTORY=50
LOG_LEVEL=INFO
HOST=0.0.0.0
PORT=8000
WORKERS=1
TRANSCRIPTION_BACKEND=whisper
EOF
    echo "  .env created — fill in FILL_ME_IN values before starting NOVA"
else
    echo "  .env already exists, skipping"
fi

# --- 8. data/ directory ---
echo "[8/8] Creating data directory..."
mkdir -p "$NOVA_DIR/data"
chmod 700 "$NOVA_DIR/data"

echo ""
echo "=========================================="
echo "  Setup complete!"
echo "=========================================="
echo ""
echo "Next steps:"
echo "  1. Edit $NOVA_DIR/.env — fill in all API keys"
echo "  2. Run: bash scripts/start_tunnel.sh  (sets up Cloudflare Tunnel)"
echo "  3. Run: bash scripts/start_nova.sh    (starts NOVA with PM2)"
echo "  4. Configure Meta webhook URL to your tunnel domain"
echo ""
