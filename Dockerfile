FROM python:3.11-slim

# ── System dependencies ──────────────────────────────────────────────────────
RUN apt-get update && apt-get install -y --no-install-recommends \
        curl \
        # pymupdf / pdfplumber
        libmupdf-dev \
        libglib2.0-0 \
        libgl1 \
        poppler-utils \
        # Pillow (favicon generation, image processing)
        libjpeg-dev \
        libpng-dev \
        fonts-dejavu-core \
        # Utilities
        rsync \
        sqlite3 \
    && rm -rf /var/lib/apt/lists/*

# ── Node.js 18 ───────────────────────────────────────────────────────────────
RUN curl -fsSL https://deb.nodesource.com/setup_18.x | bash - \
    && apt-get install -y --no-install-recommends nodejs \
    && rm -rf /var/lib/apt/lists/*

# ── Supercronic (lightweight cron for containers) ────────────────────────────
# Supports amd64 (VPS) and arm64 (Pi)
RUN ARCH=$(dpkg --print-architecture) && \
    case "$ARCH" in \
      amd64)   SC_ARCH="supercronic-linux-amd64" ;; \
      arm64)   SC_ARCH="supercronic-linux-arm64" ;; \
      *)       echo "Unsupported arch: $ARCH" && exit 1 ;; \
    esac && \
    curl -fsSL "https://github.com/aptible/supercronic/releases/latest/download/${SC_ARCH}" \
         -o /usr/local/bin/supercronic && \
    chmod +x /usr/local/bin/supercronic

# ── Non-root user ────────────────────────────────────────────────────────────
RUN groupadd -r raaf && useradd -r -g raaf -d /app raaf

WORKDIR /app

# ── Python dependencies ──────────────────────────────────────────────────────
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# ── Node dependencies ────────────────────────────────────────────────────────
COPY package.json package-lock.json* ./
RUN npm ci --omit=dev

COPY scripts/package.json scripts/package-lock.json* scripts/
RUN cd scripts && npm ci --omit=dev

# ── Application code ─────────────────────────────────────────────────────────
# Data directories (clients/, data/, logs/) come via bind mounts at runtime
COPY web/         web/
COPY scripts/     scripts/
COPY templates/   templates/
COPY docs/        docs/
COPY config/settings.yaml               config/settings.yaml
COPY config/client_template.yaml        config/client_template.yaml
COPY config/requisition_template.yaml   config/requisition_template.yaml
COPY config/pcr_credentials_template.yaml  config/pcr_credentials_template.yaml
COPY config/claude_credentials_template.yaml  config/claude_credentials_template.yaml

# ── Entrypoint & cron ────────────────────────────────────────────────────────
COPY docker/entrypoint.sh /entrypoint.sh
COPY docker/crontab       /app/docker/crontab
RUN chmod +x /entrypoint.sh

# ── Volume mount points (created here so ownership is correct) ───────────────
RUN mkdir -p data clients archive logs config/clients \
    && chown -R raaf:raaf /app

ENV PYTHONPATH=/app
ENV PYTHONIOENCODING=utf-8
ENV RAAF_DB_MODE=db

EXPOSE 8000

USER raaf

ENTRYPOINT ["/entrypoint.sh"]
CMD ["uvicorn"]
