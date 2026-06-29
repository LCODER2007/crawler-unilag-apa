#!/usr/bin/env bash
# ──────────────────────────────────────────────────────────────────────────────
#  URAAS — One-shot deployment script for Ubuntu 22.04 / Debian 12
#
#  Run on a fresh VPS as root or a sudo user:
#    curl -sSL https://raw.githubusercontent.com/YOUR/repo/main/scripts/deploy.sh | bash
#  OR after cloning:
#    bash scripts/deploy.sh
#
#  What it does:
#    1. Install Docker + Docker Compose plugin
#    2. Generate password hashes interactively
#    3. Build and start all containers (postgres, redis, app, nginx)
#    4. Print the URL to reach the dashboard
# ──────────────────────────────────────────────────────────────────────────────
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_DIR"

echo ""
echo "═══════════════════════════════════════════════════"
echo "  URAAS Deployment — $(date +%Y-%m-%d)"
echo "═══════════════════════════════════════════════════"

# ── 1. Docker ─────────────────────────────────────────────────────────────────
if ! command -v docker &>/dev/null; then
  echo ""
  echo "▶  Installing Docker..."
  curl -fsSL https://get.docker.com | sh
  usermod -aG docker "$USER" || true
  echo "   Docker installed. You may need to log out and back in."
fi

if ! docker compose version &>/dev/null 2>&1; then
  echo ""
  echo "▶  Installing Docker Compose plugin..."
  apt-get install -y docker-compose-plugin 2>/dev/null || \
    pip install docker-compose 2>/dev/null || \
    echo "   Install docker-compose manually from docs.docker.com/compose/install/"
fi

# ── 2. .env.prod ──────────────────────────────────────────────────────────────
if [ ! -f .env.prod ]; then
  echo ""
  echo "▶  Creating .env.prod from example..."
  cp .env.prod.example .env.prod

  # Get server IP
  SERVER_IP=$(curl -s https://ifconfig.me || curl -s https://api.ipify.org || echo "YOUR_SERVER_IP")
  sed -i "s/YOUR_SERVER_IP/$SERVER_IP/g" .env.prod

  # Generate secret key
  SECRET_KEY=$(python3 -c "import secrets; print(secrets.token_hex(32))" 2>/dev/null || \
               openssl rand -hex 32)
  sed -i "s/REPLACE_WITH_STRONG_RANDOM_KEY/$SECRET_KEY/" .env.prod

  # Generate password hashes
  echo ""
  echo "Enter the ADMIN password (for dashboard login):"
  read -rs ADMIN_PASS
  ADMIN_HASH=$(python3 -c "from werkzeug.security import generate_password_hash as g; print(g('$ADMIN_PASS'))" 2>/dev/null || \
               python3 -c "import hashlib, os; print('pbkdf2:sha256:' + hashlib.pbkdf2_hmac('sha256', b'$ADMIN_PASS', os.urandom(16), 150000).hex())")
  sed -i "s|REPLACE_WITH_WERKZEUG_HASH|$ADMIN_HASH|g" .env.prod

  echo ""
  echo "   .env.prod created. Edit it to add SMTP_PASSWORD and API keys before running."
  echo ""
  echo "   IMPORTANT: Set these in .env.prod before the demo:"
  echo "     SMTP_PASSWORD=<your-gmail-app-password>"
  echo "     S2_API_KEY=<from semanticscholar.org>"
  echo "     CORE_API_KEY=<from core.ac.uk/api-keys>"
fi

# ── 3. Required directories ───────────────────────────────────────────────────
mkdir -p storage/pdfs data logs backups nginx/ssl

# ── 4. Build + Start ──────────────────────────────────────────────────────────
echo ""
echo "▶  Building and starting containers (this takes ~3 min first time)..."
echo ""
# docker-compose.demo.yml = HTTP-only, works on bare IP (no SSL cert needed).
# Switch to docker-compose.prod.yml once you have a domain + SSL certificate.
docker compose --env-file .env.prod -f docker-compose.demo.yml up --build -d

# ── 5. Wait for health ────────────────────────────────────────────────────────
echo ""
echo "▶  Waiting for app to become healthy..."
for i in $(seq 1 20); do
  STATUS=$(docker inspect --format='{{.State.Health.Status}}' uraas-app 2>/dev/null || echo "starting")
  if [ "$STATUS" = "healthy" ]; then
    echo "   App is healthy!"
    break
  fi
  echo "   [$i/20] Status: $STATUS — waiting 5s..."
  sleep 5
done

# ── 6. Done ───────────────────────────────────────────────────────────────────
SERVER_IP=$(curl -s https://ifconfig.me 2>/dev/null || echo "YOUR_SERVER_IP")
echo ""
echo "═══════════════════════════════════════════════════"
echo "  URAAS is running!"
echo ""
echo "  Dashboard (direct):  http://$SERVER_IP:8080"
echo "  Dashboard (nginx):   http://$SERVER_IP"
echo ""
echo "  Logs:  docker compose -f docker-compose.prod.yml logs -f app"
echo "  Stop:  docker compose -f docker-compose.prod.yml down"
echo "═══════════════════════════════════════════════════"
