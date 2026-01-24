#!/bin/bash
# RAAF Web Application Startup Script

cd "$(dirname "$0")"

# Activate virtual environment if it exists
if [ -d "venv" ]; then
    source venv/bin/activate
fi

echo "Starting RAAF Web Application..."
echo "Access at: http://$(hostname -I | awk '{print $1}'):8000"
echo ""

python3 -m uvicorn web.app:app --host 0.0.0.0 --port 8000 --reload
