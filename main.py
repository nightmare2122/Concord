"""
main.py — Unified Concord Bot Entry Point
Copyright (c) 2026 Concord Desk. All rights reserved.
PROPRIETARY AND CONFIDENTIAL.
"""

import os
import asyncio
import logging
import traceback
from datetime import datetime, timedelta, timezone

# IST Timezone — single source of truth
from Bots.utils.timezone import IST
from dotenv import load_dotenv
from collections import deque

import discord
from discord.ext import commands

# Premium Terminal UI
from rich.console import Console, Group
from rich.panel import Panel
from rich.layout import Layout
from rich.table import Table
from rich.live import Live
from rich.text import Text
from rich.align import Align

# Load environment variables
load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")
DISABLE_TUI = os.getenv("DISABLE_TUI", "False").lower() == "true"

console = Console()

# -------------------------------------------------------------------------
# Dashboard Backend
# -------------------------------------------------------------------------

class DashboardState:
    def __init__(self):
        self.status = "INITIALIZING"
        self.latency = 0.0
        self.start_time = datetime.now(IST)
        
        self.logs_task = deque(maxlen=15)
        self.logs_leave = deque(maxlen=15)
        self.logs_dar = deque(maxlen=15)
        self.logs_system = deque(maxlen=15)
        self.error_dump = deque(maxlen=20)

dashboard_state = DashboardState()

class DashboardLogHandler(logging.Handler):
    def emit(self, record):
        msg = self.format(record)
        time_str = datetime.now(IST).strftime("%H:%M:%S")
        
        if record.levelno >= logging.ERROR:
            formatted_msg = Text(f"[{time_str}] {msg}", style="bold red")
        elif record.levelno == logging.WARNING:
            formatted_msg = Text(f"[{time_str}] {msg}", style="yellow")
        else:
            formatted_msg = Text(f"[{time_str}] {msg}", style="white")

        if "[Task]" in msg:
            dashboard_state.logs_task.append(formatted_msg)
        elif "[Leave]" in msg:
            dashboard_state.logs_leave.append(formatted_msg)
        elif "[DAR]" in msg:
            dashboard_state.logs_dar.append(formatted_msg)
        else:
            dashboard_state.logs_system.append(formatted_msg)
            
        if record.exc_info:
            raw_err = "".join(traceback.format_exception(*record.exc_info))
            dashboard_state.error_dump.append(f"\n[{time_str}] {msg}\n{raw_err}")

logger = logging.getLogger("Concord")
logger.setLevel(logging.INFO)

# Handler 1: Dashboard UI deques
dash_handler = DashboardLogHandler()
dash_handler.setFormatter(logging.Formatter("%(message)s"))
logger.addHandler(dash_handler)

# Handler 2: Background File Log
file_handler = logging.FileHandler("concord_runtime.log", mode="a")
file_handler.setFormatter(logging.Formatter("[%(asctime)s] %(levelname)s - %(message)s"))
logger.addHandler(file_handler)

# Handler 3: Stdout (only if TUI is disabled)
if DISABLE_TUI:
    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(logging.Formatter("[%(asctime)s] %(levelname)s - %(message)s"))
    logger.addHandler(stream_handler)

def generate_layout() -> Layout:
    layout = Layout()
    layout.split_column(
        Layout(name="header", size=3),
        Layout(name="main"),
        Layout(name="errors", size=10)
    )
    layout["main"].split_row(
        Layout(name="left_col"),
        Layout(name="right_col")
    )
    layout["left_col"].split_column(
        Layout(name="system_box"),
        Layout(name="task_box")
    )
    layout["right_col"].split_column(
        Layout(name="leave_box"),
        Layout(name="dar_box")
    )
    return layout

def render_dashboard() -> Layout:
    layout = generate_layout()
    uptime = str(datetime.now(IST) - dashboard_state.start_time).split('.')[0]
    
    if dashboard_state.status == "ONLINE":
        status_color = "bold green"
    elif dashboard_state.status == "CONNECTING":
        status_color = "bold yellow"
    else:
        status_color = "bold red"
    
    header_table = Table.grid(expand=True)
    header_table.add_column(justify="left", ratio=1)
    header_table.add_column(justify="center", ratio=1)
    header_table.add_column(justify="right", ratio=1)
    
    header_table.add_row(
        f"[bold cyan]▲ CONCORD UNIFIED ENGINE[/]",
        f"Status: [{status_color}]{dashboard_state.status}[/]",
        f"[dim]Uptime: {uptime} | Latency: {dashboard_state.latency}ms[/]"
    )
    layout["header"].update(Panel(header_table, style="blue"))

    layout["task_box"].update(Panel(Group(*dashboard_state.logs_task), title="[bold cyan]Task Management[/]", border_style="cyan"))
    layout["leave_box"].update(Panel(Group(*dashboard_state.logs_leave), title="[bold green]Leave Pipeline[/]", border_style="green"))
    layout["dar_box"].update(Panel(Group(*dashboard_state.logs_dar), title="[bold yellow]DAR Reporting[/]", border_style="yellow"))
    layout["system_box"].update(Panel(Group(*dashboard_state.logs_system), title="[bold magenta]Core System[/]", border_style="magenta"))
    
    err_text = Text("\n".join(dashboard_state.error_dump))
    layout["errors"].update(Panel(err_text, title="[bold red]Raw Tracebacks (Last 20)[/]", border_style="red", padding=(0,1)))

    return layout

class ConcordBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.members = True
        intents.message_content = True
        super().__init__(command_prefix="!", intents=intents)
        self.help_command = None

    async def setup_hook(self):
        logger.info("[System] Initializing modules...")
        cogs = ["cogs.discovery_cog", "cogs.task_cog", "cogs.leave_cog", "cogs.dar_cog"]
        for cog in cogs:
            try:
                await self.load_extension(cog)
                logger.info(f"[System] ✔ Ext: {cog} active.")
            except Exception as e:
                logger.error(f"[ERR-COR-001] [System] ✘ Failed to load {cog}: {e}")

    async def on_ready(self):
        dashboard_state.status = "ONLINE"
        logger.info(f"[System] Session started as {self.user} (ID: {self.user.id})")

    async def on_connect(self):
        dashboard_state.status = "CONNECTING"
        logger.info("[System] Gateway handshake successful.")
        
    async def on_resumed(self):
        dashboard_state.status = "ONLINE"
        logger.info("[System] Session resumed.")

    async def on_disconnect(self):
        dashboard_state.status = "OFFLINE"
        logger.warning("[System] Gateway connection lost.")
        
    async def on_error(self, event, *args, **kwargs):
        logger.exception(f"[ERR-COR-099] Unhandled exception in {event}")

async def main():
    if not BOT_TOKEN:
        print("CRITICAL: BOT_TOKEN missing in .env")
        return

    bot = ConcordBot()

    async def ping_updater():
        while not bot.is_closed():
            if bot.latency:
                dashboard_state.latency = round(bot.latency * 1000, 2)
            await asyncio.sleep(2)

    if DISABLE_TUI:
        logger.info("TUI Disabled. Monitoring bot in headless mode.")
        async with bot:
            asyncio.create_task(ping_updater())
            await bot.start(BOT_TOKEN)
    else:
        # Premium Dashboard on Alternate Screen
        with Live(render_dashboard(), refresh_per_second=4, screen=True) as live:
            async def dashboard_refresher():
                while not bot.is_closed():
                    live.update(render_dashboard())
                    await asyncio.sleep(0.25)

            asyncio.create_task(ping_updater())
            asyncio.create_task(dashboard_refresher())
            async with bot:
                try:
                    await bot.start(BOT_TOKEN)
                except discord.LoginFailure:
                    logger.error("[ERR-COR-002] AUTH ERROR: Invalid BOT_TOKEN.")
                except Exception as e:
                    logger.error(f"[ERR-COR-003] SYSTEM CRASH: {e}")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
    except Exception as e:
        print(f"FATAL EXIT: {e}")
