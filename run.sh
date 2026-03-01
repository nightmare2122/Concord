#!/bin/bash

# run.sh — Concord Unified Bot Startup Script
# This script ensures the virtual environment is set up, 
# dependencies are installed, and the bot starts running.

# Exit on any error
set -e

# Project root
PROJECT_ROOT="/home/am.k/Concord"
cd "$PROJECT_ROOT"

echo "--------------------------------------------------"
echo "🚀 Starting Concord Unified Bot Setup..."
echo "--------------------------------------------------"

# 1. Check for .env file
if [ ! -f ".env" ]; then
    echo "❌ Error: .env file not found!"
    echo "Please create a .env file from .env.example and add your BOT_TOKEN."
    exit 1
fi

# 2. Check/Create Virtual Environment
if [ ! -d ".venv" ]; then
    echo "📦 Creating virtual environment (.venv)..."
    python3 -m venv .venv
else
    echo "✅ Virtual environment found."
fi

# 3. Activate Virtual Environment
echo "🔗 Activating virtual environment..."
source .venv/bin/activate

# 4. Install/Update Dependencies
echo "📥 Installing/Updating dependencies from requirements.txt..."
pip install --upgrade pip
pip install -r requirements.txt

echo "--------------------------------------------------"
echo "✅ Setup complete! Starting the bot..."
echo "--------------------------------------------------"

# 5. Run the Bot
python3 main.py
