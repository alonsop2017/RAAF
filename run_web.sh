#!/bin/bash
# RAAF Web Application Startup Script

echo "Starting RAAF Web Application..."
echo "Access at: http://localhost:8000"
echo ""

# Run uvicorn with auto-reload for development
python3 -m uvicorn web.app:app --host 0.0.0.0 --port 8000 --reload
