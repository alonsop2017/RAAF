# RAAF — VPS Migration Plan
## Raspberry Pi → OVHCloud VPS (Dockerized)

**Revised:** March 2026
**Status:** Ready to execute

> This document supersedes the February 2026 Hostinger draft. The Docker infrastructure
> (`Dockerfile`, `docker-compose.yml`, `backup.sh`, `docker/data-init.sh`) is now complete
> and tested on the Pi, so the migration is largely a clone-configure-start operation.

---

## Overview

RAAF currently runs as a systemd service (`raaf-web`) on a Raspberry Pi 5 (ARM64, Debian).
The target is an OVHCloud VPS (x86_64, Ubuntu 22.04 LTS) running the same codebase inside
Docker Compose.

**What the Docker stack already handles for you:**

| Concern | Handled by |
|---------|-----------|
| Restore data on first boot | `raaf-data-init` pulls latest backup from Google Drive |
| Data integrity check | `raaf-verify` runs before the app starts |
| Web app + cron | `raaf-app` + `raaf-cron` containers |
| SSL termination | `nginx` + `certbot` containers |
| PCR sync (every 5 min) | `supercronic` inside `raaf-cron` |
| Daily local backup | `docker/crontab` → `backup.sh --target local` |

**What requires manual steps:**

- Creating the nginx config file (not in the repo yet)
- Creating the `.env` secrets file on the VPS
- Setting up rclone on the VPS so `raaf-data-init` can reach Google Drive
- Obtaining the initial SSL certificate before nginx can start in HTTPS mode
- Running `backfill_data.py` on first boot (the DB is not included in the Google Drive backup)
- Updating `backup.sh`'s hardcoded `RAAF_DIR` path

---

## Architecture on the VPS

```
Internet (HTTPS :443)
        │
  ┌─────▼──────┐
  │   nginx    │   terminates TLS, proxies to raaf-app:8000
  └─────┬──────┘
        │  http://raaf-app:8000 (Docker network, not exposed)
  ┌─────▼────────────────────────────────────────────────────┐
  │  raaf-app  (FastAPI / Uvicorn)                           │
  │  raaf-cron (supercronic — PCR sync every 5 min)          │
  │                                                          │
  │  Bind-mount volumes:                                     │
  │    /app/data     ← ../data     (SQLite DB)               │
  │    /app/clients  ← ../clients  (client/requisition data) │
  │    /app/archive  ← ../archive  (archived requisitions)   │
  │    /app/logs     ← ../logs     (application logs)        │
  │    /app/config   ← ../config   (credentials, users.db)   │
  │    /app/backups  ← ../backups  (local backup target)     │
  └──────────────────────────────────────────────────────────┘
  certbot container: auto-renews Let's Encrypt certs every 12 h
```

The compose file uses **host bind mounts** (not named volumes), so data lives at predictable
paths on the host filesystem and is easy to inspect, back up, and rsync.

---

## Pre-Migration Checklist (Complete on Pi Before Starting)

- [ ] Run a fresh Google Drive backup:
  ```bash
  cd /home/alonsop/RAAF
  ./backup.sh --target gdrive --gdrive-remote raaf-backup:RAAF-Backups
  ```
  Confirm the new archive appears in Google Drive before proceeding.

- [ ] Collect all secrets from the Pi (you will need them for the VPS `.env`):
  - `SESSION_SECRET_KEY` — from `/home/alonsop/RAAF/.env` or the systemd override
  - `GOOGLE_CLIENT_SECRET` — same source
  - `ANTHROPIC_API_KEY` — same source
  - Contents of `config/pcr_credentials.yaml`
  - Contents of `config/claude_credentials.yaml`

- [ ] Export your rclone Google Drive config from the Pi — you will need it on the VPS:
  ```bash
  cat ~/.config/rclone/rclone.conf
  ```
  Copy the `[raaf-backup]` stanza; you will paste it on the VPS.

- [ ] Note your domain name (e.g., `raaf.genapex.org`) and confirm you have DNS access.

- [ ] Confirm the OVHCloud VPS spec: Ubuntu 22.04 LTS, ≥ 2 GB RAM, ≥ 40 GB disk.

---

## Phase 1 — Provision the OVHCloud VPS

### 1.1 — Initial server login and user setup

```bash
# SSH as root (OVH sends credentials by email)
ssh root@<VPS_IP>

# Create a non-root user
adduser alonsop
usermod -aG sudo alonsop

# Copy SSH key for the new user
rsync --archive --chown=alonsop:alonsop ~/.ssh /home/alonsop/

# Disable root SSH login
sed -i 's/^PermitRootLogin yes/PermitRootLogin no/' /etc/ssh/sshd_config
systemctl restart sshd

# Log back in as alonsop
exit
ssh alonsop@<VPS_IP>
```

### 1.2 — System updates

```bash
sudo apt-get update && sudo apt-get upgrade -y
sudo apt-get install -y git curl rsync sqlite3 ufw
```

### 1.3 — Configure firewall

```bash
sudo ufw allow OpenSSH
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp
sudo ufw enable
sudo ufw status
```

### 1.4 — Install Docker Engine and Compose plugin

```bash
# Official Docker install script
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker alonsop

# Re-login so the group takes effect
newgrp docker

# Verify
docker --version
docker compose version
```

### 1.5 — Install rclone and restore Google Drive config

```bash
curl https://rclone.org/install.sh | sudo bash

mkdir -p ~/.config/rclone

# Paste the [raaf-backup] stanza from your Pi into this file
nano ~/.config/rclone/rclone.conf

# Verify connectivity
rclone lsf raaf-backup:RAAF-Backups --include "raaf_backup_*.tar.gz" | tail -5
```

---

## Phase 2 — DNS Configuration

In your DNS provider, update the A record for `raaf.genapex.org`:

```
raaf.genapex.org.   300   IN   A   <VPS_IP>
```

Set TTL to 300 seconds for fast cutover. DNS does not need to propagate before the next
phases — you can test using `/etc/hosts` overrides on your local machine.

If using Cloudflare as proxy:
- Set the record to **DNS only (grey cloud)** initially so Let's Encrypt can reach port 80.
- Switch to **Proxied (orange cloud)** after the certificate is issued.

---

## Phase 3 — Deploy the Application Code

### 3.1 — Clone the repository

```bash
git clone https://github.com/alonsop2017/RAAF.git /home/alonsop/RAAF
cd /home/alonsop/RAAF
```

### 3.2 — Create the `.env` file

```bash
cat > /home/alonsop/RAAF/.env << 'EOF'
# Required: Google OAuth
GOOGLE_CLIENT_SECRET=<paste from Pi>

# Required: Session signing key
SESSION_SECRET_KEY=<paste from Pi>

# Required: Anthropic Claude API
ANTHROPIC_API_KEY=<paste from Pi>

# Google Drive backup (rclone remote:path)
GDRIVE_REMOTE=raaf-backup:RAAF-Backups

# Set to "true" only if you want to force a fresh restore from Drive
FORCE_RESTORE=false
EOF

chmod 600 /home/alonsop/RAAF/.env
```

### 3.3 — Create the nginx config

The `docker-compose.yml` expects `nginx/raaf.conf` relative to the compose file.
This file does not exist in the repo and must be created on the VPS:

```bash
mkdir -p /home/alonsop/RAAF/nginx
cat > /home/alonsop/RAAF/nginx/raaf.conf << 'NGINX'
server {
    listen 80;
    server_name raaf.genapex.org;

    # Certbot ACME challenge
    location /.well-known/acme-challenge/ {
        root /var/www/certbot;
    }

    # Redirect everything else to HTTPS
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
    ssl_session_cache   shared:SSL:10m;

    # Allow large resume batch uploads
    client_max_body_size 50M;

    location / {
        proxy_pass         http://raaf-app:8000;
        proxy_http_version 1.1;
        proxy_set_header   Upgrade           $http_upgrade;
        proxy_set_header   Connection        "upgrade";
        proxy_set_header   Host              $host;
        proxy_set_header   X-Real-IP         $remote_addr;
        proxy_set_header   X-Forwarded-For   $proxy_add_x_forwarded_for;
        proxy_set_header   X-Forwarded-Proto $scheme;
        proxy_read_timeout 300s;
    }
}
NGINX
```

### 3.4 — Fix the hardcoded path in `backup.sh`

The script has `RAAF_DIR="/home/alonsop/RAAF"` which is correct on the VPS as written above.
If you cloned to a different path, update line 10:

```bash
# Confirm the path is correct — should match where you cloned the repo
grep "RAAF_DIR" /home/alonsop/RAAF/backup.sh
```

---

## Phase 4 — Obtain the Initial SSL Certificate

nginx cannot start in HTTPS mode until the certificate exists on disk.
Use Certbot standalone mode to issue the first certificate before starting the full stack.

> Prerequisite: DNS for `raaf.genapex.org` must already point to the VPS IP and port 80
> must be reachable (not blocked by Cloudflare proxy).

```bash
# Install Certbot on the host
sudo apt-get install -y certbot

# Stop anything using port 80 (nothing should be running yet)
# Issue the certificate
sudo certbot certonly --standalone \
  -d raaf.genapex.org \
  --email alonso.perez@archtektconsultinginc.com \
  --agree-tos \
  --non-interactive

# Verify the cert was issued
sudo ls /etc/letsencrypt/live/raaf.genapex.org/
```

Make the certs readable by the nginx container:

```bash
# Create the certbot bind-mount directory that docker-compose.yml expects
mkdir -p /home/alonsop/RAAF/docker/certbot/conf
mkdir -p /home/alonsop/RAAF/docker/certbot/www

# Symlink (or copy) Let's Encrypt certs into the compose mount path
sudo ln -s /etc/letsencrypt /home/alonsop/RAAF/docker/certbot/conf
# If the above conflicts, copy the live directory instead:
# sudo cp -rL /etc/letsencrypt /home/alonsop/RAAF/docker/certbot/conf/
```

> **Note:** The `certbot` service in `docker-compose.yml` handles *renewal* only.
> The initial issuance must be done on the host as shown above.

---

## Phase 5 — First Boot (Docker Compose)

### 5.1 — Build the image

```bash
cd /home/alonsop/RAAF
docker compose build
```

This builds the `raaf:latest` image. The Dockerfile supports both arm64 (Pi) and amd64 (VPS)
via multi-arch supercronic download.

### 5.2 — Run data initialization

On first `docker compose up`, the `raaf-data-init` container automatically:
1. Creates the directory structure (`data/`, `clients/`, `archive/`, `logs/`, `config/`)
2. Downloads the latest `raaf_backup_*.tar.gz` from Google Drive
3. Extracts and distributes `clients/`, `config/`, and `archive/` to their bind mounts
4. Sets `chmod 600` on credential files

```bash
# Run data-init alone first to watch it work
docker compose run --rm raaf-data-init
```

Watch the output for the summary lines:
```
[data-init] Clients  : 2 folder(s)
[data-init] Archive  : 0 folder(s)
[data-init] Config   : 8 file(s)
[data-init] Data initialization complete.
```

If it reports "rclone remote not configured", verify Step 1.5 and that rclone.conf is
mounted correctly (the compose file mounts `${HOME}/.config/rclone:/root/.config/rclone:ro`).

### 5.3 — Run the verification check

```bash
docker compose run --rm raaf-verify
```

This checks directory structure, SQLite schema, and critical config files.
It will warn (not fail) if `raaf.db` is missing — that is expected at this point.

### 5.4 — Restore secret credential files

The Google Drive backup includes `config/`, but you should confirm the credential files
arrived correctly and add the PCR token store if available:

```bash
ls -la /home/alonsop/RAAF/config/
# Expect: pcr_credentials.yaml, claude_credentials.yaml, settings.yaml, users.db (maybe)
```

If any credential file is missing, copy it from the Pi:
```bash
# Run from the Pi
scp /home/alonsop/RAAF/config/pcr_credentials.yaml \
    /home/alonsop/RAAF/config/claude_credentials.yaml \
    alonsop@<VPS_IP>:/home/alonsop/RAAF/config/
```

### 5.5 — Start the full stack

```bash
cd /home/alonsop/RAAF
docker compose up -d
```

Watch the startup sequence:
```bash
docker compose logs -f
```

Expected startup order:
1. `raaf-data-init` → exits 0 (data already present from Step 5.2, skips restore)
2. `raaf-verify` → exits 0
3. `raaf-app` → starts uvicorn, becomes healthy
4. `raaf-cron` → starts supercronic
5. `nginx` → starts, serves HTTP on 80 and HTTPS on 443

---

## Phase 6 — Rebuild the SQLite Database

The Google Drive backup contains `clients/`, `config/`, and `archive/` — **not** `data/raaf.db`.
The database must be rebuilt from the restored file data:

```bash
# Run the backfill script inside the app container
docker exec raaf-app python scripts/migrate/backfill_data.py

# Verify the result
docker exec raaf-app python -c "
from scripts.utils.database import get_db
db = get_db()
stats = db.get_db_stats()
print(stats)
"
```

Expected output should reflect candidate and assessment counts matching your Pi numbers.

---

## Phase 7 — Update Google OAuth Redirect URIs

If you are **keeping the same domain** (`raaf.genapex.org`), the existing redirect URI in
Google Cloud Console is already correct — skip this step.

If you are using a **new domain**, or adding the VPS as an additional authorized origin:

1. Go to [Google Cloud Console](https://console.cloud.google.com/) → APIs & Services → Credentials
2. Open the OAuth 2.0 Client ID (client ID starts with `344797612488-...`)
3. Under **Authorized redirect URIs**, add: `https://<your-domain>/auth/callback`
4. Under **Authorized JavaScript origins**, add: `https://<your-domain>`
5. Save. Changes propagate within minutes.

---

## Phase 8 — Smoke Testing

Test before updating public DNS (use `/etc/hosts` on your local machine to bypass DNS):

```
# Add to your local /etc/hosts temporarily:
<VPS_IP>   raaf.genapex.org
```

Then run through this checklist:

- [ ] `https://raaf.genapex.org` loads the login page with a valid SSL certificate
- [ ] `http://raaf.genapex.org` redirects to HTTPS (301)
- [ ] Google OAuth login completes successfully
- [ ] Dashboard shows the correct client and requisition counts
- [ ] Open a requisition — candidates and assessments are visible
- [ ] Open an individual assessment — detail view renders
- [ ] PCR Integration page → Test Connection returns success
- [ ] Upload a test resume (PDF) and run a quick assessment
- [ ] Generate a report (confirms Node.js is working inside the container)
- [ ] Admin → DB Status panel shows correct table counts
- [ ] Admin → Usage log shows your login event

```bash
# Check the health endpoint directly
curl -k https://raaf.genapex.org/health

# Check DB integrity
docker exec raaf-app sqlite3 data/raaf.db "PRAGMA integrity_check;"

# Tail app logs for errors
docker compose logs -f raaf-app
```

---

## Phase 9 — DNS Cutover

Once all smoke tests pass:

1. Remove the `/etc/hosts` override from your local machine
2. Update the DNS A record for `raaf.genapex.org` to point to `<VPS_IP>` (if not already done)
3. If using Cloudflare: switch the record from grey cloud (DNS only) to orange cloud (Proxied)
4. Wait for TTL to expire (~5 minutes at TTL 300)
5. Test from a fresh browser session: confirm login and dashboard work end-to-end
6. Monitor for 30 minutes: `docker compose logs -f raaf-app`

---

## Phase 10 — Post-Cutover Configuration

### 10.1 — Configure Google Drive backup from the VPS

The daily cron inside `raaf-cron` currently only runs a **local** backup
(`backup.sh --target local --local-path /app/backups`). Enable Google Drive backup
by adding a second cron entry or modifying `docker/crontab`:

```cron
# Daily backup to Google Drive at 1:00 AM UTC
0 1 * * * PYTHONPATH=/app /app/backup.sh --target gdrive --gdrive-remote raaf-backup:RAAF-Backups --quiet >> /app/logs/backup.log 2>&1
```

The `raaf-cron` container mounts `~/.config/rclone` from the host, so the rclone config
set up in Phase 1.5 is available inside the container.

> Do not remove the Google Drive backup from the Pi until the VPS backup is confirmed
> working. Both can run simultaneously — they write to the same Drive folder and the
> retention policy keeps only the last 30 archives.

### 10.2 — Verify PCR sync is running

```bash
# Check that supercronic started the 5-minute PCR sync
docker compose logs raaf-cron | head -20

# After 5 minutes, check the sync log
docker exec raaf-app tail -20 /app/logs/pcr_sync.log
```

### 10.3 — Set up SSL auto-renewal

The `certbot` container in `docker-compose.yml` runs `certbot renew` every 12 hours and is
included in the stack. Confirm it is running:

```bash
docker compose ps certbot
```

After renewal, nginx needs to reload to pick up the new cert. Add a host cron entry:

```bash
crontab -e
# Add:
0 4 * * * docker compose -f /home/alonsop/RAAF/docker-compose.yml exec nginx nginx -s reload
```

---

## Phase 11 — Parallel Run and Pi Decommission

Run both environments in parallel for **at least 7 days** before decommissioning the Pi.
During this period:
- Pi remains active and continues processing any PCR syncs (stop PCR cron on Pi to avoid
  double-assessment: `sudo systemctl stop raaf-pcr-cron`)
- The VPS is the primary access point
- Monitor VPS logs daily for errors

Once the VPS is confirmed stable:

```bash
# On the Pi — stop and disable the service
sudo systemctl stop raaf-web
sudo systemctl disable raaf-web
echo "RAAF migrated to VPS on $(date)" | sudo tee /etc/motd
```

The Pi can be repurposed or kept as a cold standby.

---

## Architecture Differences — Pi vs VPS

| Aspect | Raspberry Pi (current) | OVHCloud VPS (target) |
|--------|----------------------|----------------------|
| CPU architecture | ARM64 | x86_64 |
| Python wheels | ARM wheels (Pi-specific) | x86_64 wheels (standard PyPI) |
| Process manager | `systemd` unit file | Docker Compose + restart policy |
| Python binary | `/home/alonsop/RAAF/venv/bin/python3` | Inside Docker image |
| PCR sync | Host cron → `cron_sync.sh` | `supercronic` in `raaf-cron` container |
| SSL | Certbot on host | Certbot container + host issuance |
| Secrets | `.env` file (same format) | `.env` file |
| Data persistence | Plain host filesystem | Host bind mounts |
| Data restore | Manual rsync or backup.sh | Automatic via `raaf-data-init` |
| LAN backup path | `/media/alonsop/Backup/...` | Not applicable (remove or comment out) |
| Port exposure | 8000 direct + nginx on host | Nginx container on 80/443 only |

---

## Known Risks and Mitigations

| Risk | Mitigation |
|------|-----------|
| `raaf.db` not in Google Drive backup | Run `backfill_data.py` after first boot (Phase 6). DB rebuilds from the restored `clients/` JSON files. |
| Architecture mismatch (ARM → x86_64) | Docker handles this — `pip install -r requirements.txt` inside the build pulls x86_64 wheels automatically. PyMuPDF, pdfplumber, and all other deps have x86_64 wheels on PyPI. |
| PCR session token stale after transfer | Run `python scripts/pcr/test_connection.py` inside the container. If it fails, re-run `python scripts/pcr/refresh_token.py` to get a fresh token. |
| Google Drive rclone auth not transferred | Paste the `[raaf-backup]` stanza from the Pi's `rclone.conf` into the VPS's `rclone.conf` (Phase 1.5). |
| `nginx/raaf.conf` does not exist in repo | Must be created manually on the VPS as shown in Phase 3.3. Consider committing a sanitized version without the hardcoded domain. |
| SSL cert not present when nginx starts | Always run the standalone Certbot step (Phase 4) before `docker compose up` with nginx. |
| `backup.sh` has hardcoded `/home/alonsop/RAAF` | Correct if you clone to that path. If different, update `RAAF_DIR` on line 10. |
| LAN backup path (`/media/alonsop/Backup`) | `config/settings.yaml` has `lan_path: /media/alonsop/Backup/RBPi5_Backup`. This is ignored at runtime (it's a reference only), but can be removed or updated post-migration. |
| Large resume uploads timing out | `client_max_body_size 50M` in the nginx config handles this. Proxy timeout is set to 300s. |
| `users.db` (session/auth DB) not in backup | The `raaf-data-init` restores `config/` which includes `users.db` if it was present in the latest backup. Worst case: users just need to log in again once. |
| Cloudflare bot challenge converting POST → GET | Already fixed in the codebase with GET fallback routes. Ensure Cloudflare Security Level is not set to "I'm Under Attack" for sustained use. |

---

## Quick Reference — Key Commands on VPS

```bash
# Start everything
cd /home/alonsop/RAAF && docker compose up -d

# Stop everything
docker compose down

# View live logs (all services)
docker compose logs -f

# View app logs only
docker compose logs -f raaf-app

# Restart app after a git pull
git pull && docker compose up -d --build raaf-app

# Open a shell inside the app container
docker exec -it raaf-app bash

# Run a management script
docker exec raaf-app python scripts/pcr/test_connection.py

# Check DB integrity
docker exec raaf-app sqlite3 data/raaf.db "PRAGMA integrity_check;"

# Manual backup to Google Drive
docker exec raaf-app /app/backup.sh --target gdrive --gdrive-remote raaf-backup:RAAF-Backups

# Check PCR sync log
docker exec raaf-app tail -50 /app/logs/pcr_sync.log

# Service status
docker compose ps

# Rebuild DB from files
docker exec raaf-app python scripts/migrate/backfill_data.py
```

---

*RAAF VPS Migration Plan — Archtekt Consulting Inc. — March 2026*
