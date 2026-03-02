#!/bin/bash
# vps-setup.sh — One-time VPS setup for RAAF
#
# Run this on a fresh VPS (Ubuntu 22.04+) after cloning the repo.
# It installs Docker, sets up SSL, and starts all services.
#
# Usage:
#   chmod +x vps-setup.sh
#   sudo ./vps-setup.sh --domain raaf.yourdomain.com --email you@example.com

set -e

DOMAIN=""
EMAIL=""

# ── Parse args ────────────────────────────────────────────────────────────────
while [[ $# -gt 0 ]]; do
    case $1 in
        --domain) DOMAIN="$2"; shift 2 ;;
        --email)  EMAIL="$2";  shift 2 ;;
        *) echo "Unknown arg: $1"; exit 1 ;;
    esac
done

if [ -z "$DOMAIN" ] || [ -z "$EMAIL" ]; then
    echo "Usage: $0 --domain raaf.yourdomain.com --email you@example.com"
    exit 1
fi

echo ""
echo "========================================"
echo " RAAF VPS Setup"
echo " Domain: $DOMAIN"
echo " Email:  $EMAIL"
echo "========================================"
echo ""

# ── 1. Install Docker ─────────────────────────────────────────────────────────
if ! command -v docker &>/dev/null; then
    echo "[1/6] Installing Docker..."
    curl -fsSL https://get.docker.com | sh
    usermod -aG docker "$SUDO_USER"
    echo "      Docker installed."
else
    echo "[1/6] Docker already installed — skipping."
fi

# ── 2. Create .env from example ───────────────────────────────────────────────
echo ""
echo "[2/6] Setting up .env file..."
if [ ! -f ".env" ]; then
    cp .env.example .env
    echo ""
    echo "  !! ACTION REQUIRED: Edit .env and fill in your secrets before continuing."
    echo "  !! Run:  nano .env"
    echo ""
    read -rp "  Press Enter once you have saved .env to continue..."
else
    echo "      .env already exists — skipping."
fi

# ── 3. Create data directories ────────────────────────────────────────────────
echo ""
echo "[3/6] Creating data directories..."
mkdir -p data clients archive logs certbot/www certbot/conf backups
echo "      Done."

# ── 4. Build image ───────────────────────────────────────────────────────────
echo ""
echo "[4/6] Building Docker image..."
docker compose build

# ── 5. Get SSL certificate ───────────────────────────────────────────────────
echo ""
echo "[5/6] Obtaining SSL certificate for $DOMAIN..."

# Update domain in nginx configs
sed -i "s/raaf\.genapex\.org/$DOMAIN/g" nginx/raaf.conf

# Start with bootstrap HTTP config (no SSL required)
cp nginx/raaf.conf nginx/raaf.conf.bak
cp nginx/raaf-bootstrap.conf nginx/raaf.conf.tmp
cat nginx/raaf.conf.tmp > nginx/raaf.conf

# Start app + nginx (HTTP only)
docker compose up -d raaf-app nginx

echo "      Waiting for services to be ready..."
sleep 8

# Run certbot
docker compose run --rm certbot certonly \
    --webroot \
    --webroot-path=/var/www/certbot \
    --email "$EMAIL" \
    --agree-tos \
    --no-eff-email \
    -d "$DOMAIN"

# Restore full HTTPS nginx config
cp nginx/raaf.conf.bak nginx/raaf.conf
rm -f nginx/raaf.conf.tmp

echo "      SSL certificate obtained."

# ── 6. Start all services ─────────────────────────────────────────────────────
echo ""
echo "[6/6] Starting all services..."
docker compose up -d

echo ""
echo "========================================"
echo " Setup complete!"
echo ""
echo " App:    https://$DOMAIN"
echo " Logs:   docker compose logs -f raaf-app"
echo " Status: docker compose ps"
echo ""
echo " To renew certs manually:"
echo "   docker compose run --rm certbot renew"
echo "========================================"
