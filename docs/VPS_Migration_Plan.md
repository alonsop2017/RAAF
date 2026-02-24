# RAAF — VPS Migration Plan
## Raspberry Pi → Hostinger VPS (Dockerized)

**Prepared:** February 2026
**Status:** Ready to execute — awaiting VPS activation

---

## Overview

This plan migrates the RAAF web application from a self-hosted Raspberry Pi (ARM64) to a Hostinger VPS (x86_64), running inside a Docker container to isolate it from other websites that may be hosted on the same server.

**What moves via GitHub clone (no manual transfer needed):**
- All application code (`web/`, `scripts/`, `templates/`)
- Static assets (`web/static/`)
- Configuration templates and non-secret settings (`config/settings.yaml`)
- Documentation (`docs/`)

**What requires manual transfer (not in git):**
- SQLite database: `data/raaf.db` (4.8 MB)
- All client data: `clients/` directory (~255 MB — resumes, assessments, reports)
- Secret credential files: `config/pcr_credentials.yaml`, `config/claude_credentials.yaml`, `config/.token_store.json`

---

## Architecture on the VPS

```
Internet (HTTPS :443)
        │
  ┌─────▼──────┐
  │   nginx    │  ← Host-level or Docker container
  │  (reverse  │    Terminates SSL, forwards to RAAF
  │   proxy)   │
  └─────┬──────┘
        │ http://raaf-app:8000
  ┌─────▼──────────────────────────────┐
  │         raaf-app container         │
  │                                    │
  │  Python 3.11 + Node.js 18          │
  │  uvicorn web.app:app --port 8000   │
  │                                    │
  │  Volumes:                          │
  │    /app/data      ← raaf-data      │
  │    /app/clients   ← raaf-clients   │
  │    /app/config    ← raaf-config    │
  │    /app/logs      ← raaf-logs      │
  └────────────────────────────────────┘
```

**Docker Compose** manages the two containers (raaf-app + nginx).
**Named volumes** ensure data survives container restarts and upgrades.
**Certbot** (or nginx-certbot image) handles Let's Encrypt SSL automatically.

---

## Pre-Migration Checklist (Do Before VPS is Activated)

- [ ] Note your current `SESSION_SECRET_KEY` value (from the Pi's systemd service file)
- [ ] Note your current `GOOGLE_CLIENT_SECRET` value
- [ ] Note your current `ANTHROPIC_API_KEY` value (or confirm it's in `claude_credentials.yaml`)
- [ ] Decide on the VPS domain name (e.g., keep `raaf.genapex.org` or use a new one)
- [ ] Confirm the Hostinger VPS OS will be Ubuntu 22.04 or 24.04 LTS (recommended)
- [ ] Confirm the VPS has at least 2 GB RAM and 20 GB disk (recommended minimums)

---

## Files to Create Before Migration

The following files do not exist in the repo yet and must be created as part of this migration. They should be created and tested on the Pi first, then committed.

### 1. `Dockerfile`

```dockerfile
FROM python:3.11-slim

# System dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    nodejs npm \
    libmupdf-dev \
    poppler-utils \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install Node.js 18 (apt default may be older)
RUN curl -fsSL https://deb.nodesource.com/setup_18.x | bash - \
    && apt-get install -y nodejs \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Install Node dependencies (both package.json files)
COPY package.json .
RUN npm install --omit=dev

COPY scripts/package.json scripts/
RUN cd scripts && npm install --omit=dev

# Copy application code (not data — that comes via volumes)
COPY web/         web/
COPY scripts/     scripts/
COPY templates/   templates/
COPY config/settings.yaml        config/settings.yaml
COPY config/client_template.yaml config/client_template.yaml
COPY config/requisition_template.yaml config/requisition_template.yaml

# Create directories that will be mounted as volumes
RUN mkdir -p data clients logs

EXPOSE 8000

CMD ["python", "-m", "uvicorn", "web.app:app", \
     "--host", "0.0.0.0", "--port", "8000", \
     "--proxy-headers", "--forwarded-allow-ips=*"]
```

> **Note:** `clients/`, `data/`, `config/` (secrets), and `logs/` are mounted as volumes
> at runtime — they are NOT baked into the image.

---

### 2. `docker-compose.yml`

```yaml
services:

  raaf-app:
    build: .
    container_name: raaf-app
    restart: unless-stopped
    environment:
      - RAAF_DB_MODE=db
      - SESSION_SECRET_KEY=${SESSION_SECRET_KEY}
      - GOOGLE_CLIENT_SECRET=${GOOGLE_CLIENT_SECRET}
      - ANTHROPIC_API_KEY=${ANTHROPIC_API_KEY}
    volumes:
      - raaf-data:/app/data
      - raaf-clients:/app/clients
      - raaf-config:/app/config
      - raaf-logs:/app/logs
    networks:
      - raaf-network
    expose:
      - "8000"
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8000/health"]
      interval: 30s
      timeout: 10s
      retries: 3

  nginx:
    image: nginx:alpine
    container_name: raaf-nginx
    restart: unless-stopped
    ports:
      - "80:80"
      - "443:443"
    volumes:
      - ./nginx/raaf.conf:/etc/nginx/conf.d/raaf.conf:ro
      - raaf-certs:/etc/letsencrypt:ro
      - raaf-certbot-webroot:/var/www/certbot:ro
    networks:
      - raaf-network
    depends_on:
      - raaf-app

volumes:
  raaf-data:
  raaf-clients:
  raaf-config:
  raaf-logs:
  raaf-certs:
  raaf-certbot-webroot:

networks:
  raaf-network:
    driver: bridge
```

---

### 3. `.env` (on VPS only — never committed to git)

```dotenv
SESSION_SECRET_KEY=<copy from Pi systemd service>
GOOGLE_CLIENT_SECRET=<copy from Pi systemd service>
ANTHROPIC_API_KEY=<copy from Pi or claude_credentials.yaml>
```

---

### 4. `nginx/raaf.conf`

```nginx
server {
    listen 80;
    server_name raaf.genapex.org;

    # Certbot challenge
    location /.well-known/acme-challenge/ {
        root /var/www/certbot;
    }

    # Redirect all HTTP to HTTPS
    location / {
        return 301 https://$host$request_uri;
    }
}

server {
    listen 443 ssl;
    server_name raaf.genapex.org;

    ssl_certificate     /etc/letsencrypt/live/raaf.genapex.org/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/raaf.genapex.org/privkey.pem;

    ssl_protocols       TLSv1.2 TLSv1.3;
    ssl_ciphers         HIGH:!aNULL:!MD5;

    client_max_body_size 50M;   # Allow large resume batch uploads

    location / {
        proxy_pass         http://raaf-app:8000;
        proxy_http_version 1.1;
        proxy_set_header   Upgrade           $http_upgrade;
        proxy_set_header   Connection        "upgrade";
        proxy_set_header   Host              $host;
        proxy_set_header   X-Real-IP         $remote_addr;
        proxy_set_header   X-Forwarded-For   $proxy_add_x_forwarded_for;
        proxy_set_header   X-Forwarded-Proto $scheme;
        proxy_read_timeout 86400;
    }
}
```

---

## Step-by-Step Migration Procedure

### Phase 1 — Prepare the VPS

**Step 1.1 — Initial server setup**
```bash
# SSH into the VPS as root, then create a non-root user
adduser raaf
usermod -aG sudo raaf
# Log in as raaf for remaining steps
```

**Step 1.2 — Install Docker and Docker Compose**
```bash
# Install Docker Engine (official script)
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker raaf

# Install Docker Compose plugin
sudo apt-get install -y docker-compose-plugin

# Verify
docker --version
docker compose version
```

**Step 1.3 — Point DNS to the VPS**

In your DNS provider (wherever `raaf.genapex.org` is managed):
- Create/update an **A record**: `raaf.genapex.org` → `<VPS public IP>`
- TTL: 300 seconds for fast cutover
- Wait for propagation before proceeding to SSL step

---

### Phase 2 — Deploy the Application

**Step 2.1 — Clone the repository**
```bash
git clone https://github.com/alonsop2017/RAAF.git /home/raaf/RAAF
cd /home/raaf/RAAF
```

**Step 2.2 — Create the `.env` file**
```bash
cat > .env << 'EOF'
SESSION_SECRET_KEY=<paste value from Pi>
GOOGLE_CLIENT_SECRET=<paste value from Pi>
ANTHROPIC_API_KEY=<paste value from Pi or credentials file>
EOF
chmod 600 .env
```

**Step 2.3 — Create the nginx config directory**
```bash
mkdir -p nginx
# Create nginx/raaf.conf using the template in this document
```

**Step 2.4 — Obtain SSL certificate (before starting nginx in SSL mode)**

Use Certbot standalone mode for the initial certificate:
```bash
sudo apt-get install -y certbot
sudo certbot certonly --standalone \
  -d raaf.genapex.org \
  --email alonso@peoplefindinc.com \
  --agree-tos --non-interactive

# Copy certs to the Docker volume location
# (Certbot in Docker is configured later for auto-renewal)
```

Or use the `certbot/certbot` Docker image approach — whichever is simpler at the time.

**Step 2.5 — Build and start containers (app only, no nginx yet)**
```bash
docker compose up -d raaf-app
docker compose logs raaf-app   # Watch for startup errors
```

---

### Phase 3 — Transfer Data from the Pi

> Run these commands **from the Pi**, substituting `<VPS_IP>` and `<VPS_USER>`.

**Step 3.1 — Transfer the SQLite database**
```bash
# On the Pi — stop the service first to ensure a clean DB snapshot
sudo systemctl stop raaf-web

# Transfer the database
scp /home/alonsop/RAAF/data/raaf.db <VPS_USER>@<VPS_IP>:/tmp/raaf.db

# On the VPS — copy into the Docker volume
docker run --rm \
  -v raaf_raaf-data:/app/data \
  -v /tmp:/tmp \
  python:3.11-slim \
  cp /tmp/raaf.db /app/data/raaf.db
```

**Step 3.2 — Transfer the clients/ directory (~255 MB)**
```bash
# On the Pi — rsync clients/ to VPS
rsync -avz --progress \
  /home/alonsop/RAAF/clients/ \
  <VPS_USER>@<VPS_IP>:/tmp/raaf-clients/

# On the VPS — copy into the Docker volume
docker run --rm \
  -v raaf_raaf-clients:/app/clients \
  -v /tmp/raaf-clients:/tmp/src \
  python:3.11-slim \
  bash -c "cp -r /tmp/src/. /app/clients/"
```

**Step 3.3 — Transfer secret config files**
```bash
# On the Pi
scp /home/alonsop/RAAF/config/pcr_credentials.yaml \
    /home/alonsop/RAAF/config/claude_credentials.yaml \
    <VPS_USER>@<VPS_IP>:/tmp/raaf-config/

# On the VPS — copy into the config volume
docker run --rm \
  -v raaf_raaf-config:/app/config \
  -v /tmp/raaf-config:/tmp/src \
  python:3.11-slim \
  bash -c "cp /tmp/src/*.yaml /app/config/"
```

> **Note on `.token_store.json`:** This file holds Google OAuth tokens for the Drive integration.
> It is safe to omit — users will simply re-authenticate with Google Drive on first use.
> The session secret key is the same, so regular login sessions are unaffected.

**Step 3.4 — Restart the Pi service** (keep it running during testing)
```bash
# On the Pi
sudo systemctl start raaf-web
```

---

### Phase 4 — Update Google OAuth

The Google OAuth redirect URI must be updated before the new deployment will accept logins.

1. Go to [Google Cloud Console](https://console.cloud.google.com/) → APIs & Services → Credentials
2. Open the OAuth 2.0 Client ID for RAAF (client ID: `344797612488-...`)
3. Under **Authorized redirect URIs**, add: `https://raaf.genapex.org/auth/callback`
4. If the domain is unchanged (`raaf.genapex.org`), the existing URI is already correct — no change needed.
5. If using a new domain, also update `auth.google.redirect_uri` in `config/settings.yaml` and rebuild the container.

---

### Phase 5 — Start nginx and Test

**Step 5.1 — Start the nginx container**
```bash
docker compose up -d nginx
docker compose ps          # Both containers should show "running"
docker compose logs nginx  # Check for SSL/config errors
```

**Step 5.2 — Smoke test before DNS cutover**

Test directly via the VPS IP (bypass DNS):
```bash
curl -k https://<VPS_IP>/health        # Expect: {"status":"healthy"}
curl -I http://<VPS_IP>/               # Expect: 301 redirect to https
```

Test from a browser using `/etc/hosts` override:
```
# Add temporarily to your local /etc/hosts:
<VPS_IP>   raaf.genapex.org
```
Then visit `https://raaf.genapex.org` and verify:
- [ ] Login page loads
- [ ] Google OAuth login completes successfully
- [ ] Dashboard shows correct client/requisition counts
- [ ] Open a requisition and confirm candidates are visible
- [ ] Generate a test report (confirm Node.js is working)
- [ ] PCR Integration page connects successfully
- [ ] Upload a test resume and run a quick assessment

**Step 5.3 — Verify DB integrity**
```bash
docker exec raaf-app \
  python -c "from scripts.utils.database import get_db; print(get_db().get_db_stats())"
```

---

### Phase 6 — DNS Cutover

Once all smoke tests pass:

1. Update the DNS A record for `raaf.genapex.org` to point to the VPS IP (if not already done)
2. Wait for TTL to expire (5 minutes at TTL 300)
3. Test from a fresh browser (no `/etc/hosts` override) — confirm full login and dashboard
4. Monitor logs for 30 minutes: `docker compose logs -f raaf-app`

---

### Phase 7 — PCR Sync Cron (on VPS)

The Pi currently runs `scripts/pcr/cron_sync.sh` on a schedule. On the VPS, replicate this with a host cron entry that runs inside the container:

```bash
# On the VPS host, add to crontab (crontab -e):
*/15 * * * * docker exec raaf-app python scripts/pcr/watch_applicants.py --once --auto-download >> /home/raaf/logs/pcr_sync.log 2>&1
```

Or add a `cron` service to the Docker Compose setup if preferred.

---

### Phase 8 — SSL Auto-Renewal

Let's Encrypt certificates expire every 90 days. Set up auto-renewal:

```bash
# On the VPS host — add to crontab:
0 3 * * * certbot renew --quiet && \
  docker compose -f /home/raaf/RAAF/docker-compose.yml restart nginx
```

Or use the `certbot/certbot` Docker image with the `--webroot` method alongside the nginx container for fully containerized renewal.

---

### Phase 9 — Decommission Pi (After Stabilization)

Run both environments in parallel for **at least 1 week** before decommissioning the Pi.

Once the VPS is confirmed stable:
```bash
# On the Pi — stop and disable the service
sudo systemctl stop raaf-web
sudo systemctl disable raaf-web
```

The Pi can then be repurposed or kept as a cold backup.

---

## Architecture Differences — Pi vs VPS

| Aspect | Raspberry Pi (current) | Hostinger VPS (target) |
|--------|----------------------|----------------------|
| CPU architecture | ARM64 | x86_64 |
| Python binary wheels | ARM wheels | x86_64 wheels (auto via pip) |
| Process manager | systemd unit file | Docker Compose + restart policy |
| SSL | Certbot on host | Certbot on host or in Docker |
| Secrets | Inline in systemd unit | `.env` file (chmod 600) |
| Data persistence | Plain filesystem | Docker named volumes |
| Port exposure | 8000 via nginx | 8000 inside Docker network only |
| Isolation | None (shared OS) | Full container isolation |
| Other websites | Not applicable | Isolated in separate containers |

---

## Known Risks and Mitigations

| Risk | Mitigation |
|------|-----------|
| **Architecture mismatch** (ARM → x86_64) | Clean `pip install -r requirements.txt` inside Docker handles this automatically. PyMuPDF and pypdfium2 have x86_64 wheels on PyPI. |
| **DB corruption during transfer** | Stop the Pi service before copying `raaf.db`. Run `PRAGMA integrity_check` after transfer. |
| **Google OAuth redirect URI mismatch** | If keeping the same domain, no change needed. Add new URI in Google Cloud Console before testing. |
| **PCR session token expiry** | The PCR session token in `pcr_credentials.yaml` may be stale after transfer. Run `python scripts/pcr/test_connection.py` inside the container and refresh if needed. |
| **Volume permissions** | Files copied into Docker volumes must be owned by the user running uvicorn inside the container (typically `root` in slim images — confirm with `id` inside the container). |
| **Large upload timeouts** | `client_max_body_size 50M` in nginx config handles batch resume uploads. The current Pi config has no explicit limit — keep it at 50M. |
| **`playwright` not available** | Playwright and Chromium are not included in the Docker image by default (screenshot utility only). If screenshots are needed, add `playwright install chromium` to the Dockerfile. |

---

## Quick Reference — Key Commands on VPS

```bash
# Start everything
docker compose up -d

# Stop everything
docker compose down

# View live logs
docker compose logs -f raaf-app

# Restart app only (after code change)
docker compose restart raaf-app

# Rebuild after Dockerfile or requirements change
docker compose up -d --build raaf-app

# Open a shell inside the app container
docker exec -it raaf-app bash

# Backup the database
docker exec raaf-app \
  cp /app/data/raaf.db /app/data/raaf_backup_$(date +%Y%m%d).db

# Check DB integrity
docker exec raaf-app \
  python -c "import sqlite3; c=sqlite3.connect('data/raaf.db'); print(c.execute('PRAGMA integrity_check').fetchone())"

# Update application code
cd /home/raaf/RAAF && git pull
docker compose up -d --build raaf-app
```

---

*RAAF VPS Migration Plan — Archtekt Consulting Inc. — February 2026*
