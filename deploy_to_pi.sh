#!/bin/bash
# RAAF Deployment Script for Raspberry Pi
# Usage: ./deploy_to_pi.sh

PI_HOST="alonsop@192.168.2.71"
PI_DIR="/home/alonsop/RAAF"
LOCAL_DIR="/home/alonsop/RAAF"

echo "=============================================="
echo "RAAF Deployment to Raspberry Pi"
echo "=============================================="
echo ""
echo "Target: $PI_HOST:$PI_DIR"
echo ""

# Step 1: Create directory on Pi
echo "[1/5] Creating directory on Raspberry Pi..."
ssh $PI_HOST "mkdir -p $PI_DIR"

# Step 2: Copy files using rsync
echo "[2/5] Copying files to Raspberry Pi..."
rsync -avz --progress \
    --exclude '__pycache__' \
    --exclude '*.pyc' \
    --exclude '.git' \
    --exclude 'node_modules' \
    --exclude 'venv' \
    --exclude '.venv' \
    --exclude 'config/pcr_credentials.yaml' \
    $LOCAL_DIR/ $PI_HOST:$PI_DIR/

# Step 3: Install Python dependencies
echo "[3/5] Installing Python dependencies..."
ssh $PI_HOST "cd $PI_DIR && pip3 install -r requirements.txt"

# Step 4: Install Node.js dependencies
echo "[4/5] Installing Node.js dependencies..."
ssh $PI_HOST "cd $PI_DIR/scripts && npm install"

# Step 5: Set up run script permissions
echo "[5/5] Setting up permissions..."
ssh $PI_HOST "chmod +x $PI_DIR/run_web.sh"

echo ""
echo "=============================================="
echo "Deployment Complete!"
echo "=============================================="
echo ""
echo "To start the web application on the Pi:"
echo "  ssh $PI_HOST"
echo "  cd $PI_DIR"
echo "  ./run_web.sh"
echo ""
echo "Then access: http://192.168.2.71:8000"
echo ""
