#!/bin/bash
# =============================================================================
# Cloudflare Tunnel Setup for NOVA
# =============================================================================
# Run this ONCE to create a named tunnel, then it auto-starts via PM2.
# Your tunnel URL will be: https://nova.<yourdomain>.com
# =============================================================================
set -e

TUNNEL_NAME="nova"
TUNNEL_CONFIG="$HOME/.cloudflared/config.yml"

echo "Setting up Cloudflare Tunnel for NOVA..."

# Login to Cloudflare (opens browser)
if [ ! -f "$HOME/.cloudflared/cert.pem" ]; then
    echo "Logging in to Cloudflare..."
    cloudflared tunnel login
fi

# Create tunnel if it doesn't exist
if ! cloudflared tunnel list 2>/dev/null | grep -q "$TUNNEL_NAME"; then
    echo "Creating tunnel '$TUNNEL_NAME'..."
    cloudflared tunnel create "$TUNNEL_NAME"
else
    echo "Tunnel '$TUNNEL_NAME' already exists"
fi

# Get tunnel ID
TUNNEL_ID=$(cloudflared tunnel list 2>/dev/null | grep "$TUNNEL_NAME" | awk '{print $1}')
echo "Tunnel ID: $TUNNEL_ID"

# Write tunnel config
mkdir -p "$HOME/.cloudflared"
cat > "$TUNNEL_CONFIG" <<EOF
tunnel: $TUNNEL_ID
credentials-file: $HOME/.cloudflared/$TUNNEL_ID.json

ingress:
  - hostname: nova.YOURDOMAIN.COM
    service: http://localhost:8000
  - service: http_status:404
EOF

echo ""
echo "Config written to $TUNNEL_CONFIG"
echo ""
echo "IMPORTANT: Edit $TUNNEL_CONFIG and replace 'nova.YOURDOMAIN.COM' with your domain."
echo ""
echo "Then add a DNS CNAME record in Cloudflare:"
echo "  Type: CNAME"
echo "  Name: nova"
echo "  Target: $TUNNEL_ID.cfargotunnel.com"
echo "  Proxied: Yes"
echo ""
echo "Or run: cloudflared tunnel route dns $TUNNEL_NAME nova.YOURDOMAIN.COM"
echo ""
echo "Once DNS is set, run: bash scripts/start_nova.sh"
