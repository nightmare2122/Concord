#!/bin/bash

# run.sh — Concord Unified Bot Startup Script
# Professional automation for environment setup and bot execution.

# ANSI Color Codes
CYAN='\033[0;36m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
BOLD='\033[1m'
NC='\033[0m'

# Exit on any error
set -e

# Project root
PROJECT_ROOT="/home/am.k/Concord"
cd "$PROJECT_ROOT"

clear
echo -e "${CYAN}${BOLD}--------------------------------------------------${NC}"
echo -e "${CYAN}${BOLD}        🛸 CONCORD UNIFIED BOT SETUP            ${NC}"
echo -e "${CYAN}${BOLD}--------------------------------------------------${NC}"

# 1. Check for .env file
echo -e "${YELLOW}🔍 Checking configuration...${NC}"
if [ ! -f ".env" ]; then
    echo -e "${RED}❌ Error: .env file missing!${NC}"
    echo -e "   Please create a .env file from .env.example with your BOT_TOKEN."
    exit 1
fi
echo -e "${GREEN}✅ Configuration verified.${NC}"

# 2. Check/Create Virtual Environment
if [ ! -d ".venv" ]; then
    echo -e "${YELLOW}📦 Initializing virtual environment (.venv)...${NC}"
    python3 -m venv .venv
else
    echo -e "${GREEN}✅ Virtual environment exists.${NC}"
fi

# 3. Activate Virtual Environment
echo -e "${YELLOW}🔗 Activating environment...${NC}"
source .venv/bin/activate

# 4. Install/Update Dependencies
echo -e "${YELLOW}📥 Synchronizing dependencies...${NC}"
pip install --upgrade pip > /dev/null 2>&1
pip install -r requirements.txt > /dev/null 2>&1
echo -e "${GREEN}✅ All dependencies are up to date.${NC}"

echo -e "${CYAN}${BOLD}--------------------------------------------------${NC}"
echo -e "${GREEN}${BOLD}🚀 Launching Concord Engine...${NC}"
echo -e "${CYAN}${BOLD}--------------------------------------------------${NC}"
echo ""

# 5. Run the Bot
python3 main.py
