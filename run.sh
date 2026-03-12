#!/bin/bash
# run.sh — Concord Unified Bot Startup Wrapper

CYAN='\033[0;36m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

set -e

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$PROJECT_ROOT"

clear
echo -e "${YELLOW}Terminating existing bot instances...${NC}"
pkill -f "python3 main.py" 2>/dev/null || true

echo -e "${CYAN}■■■ CONCORD PRE-FLIGHT CHECKS ■■■${NC}"

if [ ! -f ".env" ]; then
    echo -e "${RED}❌ Error: .env file missing! Setup required.${NC}"
    exit 1
fi

if [ ! -d ".venv" ]; then
    echo -e "${YELLOW}Initializing missing .venv...${NC}"
    python3 -m venv .venv
fi

source .venv/bin/activate

echo -e "${YELLOW}Syncing core dependencies...${NC}"
pip install --upgrade pip > /dev/null 2>&1
pip install -r requirements.txt > /dev/null 2>&1

clear

python3 main.py
