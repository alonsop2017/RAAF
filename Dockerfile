FROM python:3.11-slim

# System dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    libmupdf-dev \
    poppler-utils \
    rsync \
    && rm -rf /var/lib/apt/lists/*

# Install Node.js 18
RUN curl -fsSL https://deb.nodesource.com/setup_18.x | bash - \
    && apt-get install -y nodejs \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Install Node dependencies
COPY package.json .
RUN npm install --omit=dev

COPY scripts/package.json scripts/
RUN cd scripts && npm install --omit=dev

# Copy application code (data comes via volumes at runtime)
COPY web/         web/
COPY scripts/     scripts/
COPY templates/   templates/
COPY config/settings.yaml             config/settings.yaml
COPY config/client_template.yaml      config/client_template.yaml
COPY config/requisition_template.yaml config/requisition_template.yaml

# Create volume mount points
RUN mkdir -p data clients logs

EXPOSE 8000

CMD ["python", "-m", "uvicorn", "web.app:app", \
     "--host", "0.0.0.0", "--port", "8000", \
     "--proxy-headers", "--forwarded-allow-ips=*"]
