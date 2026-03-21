"""
main.py — Unified Concord Bot Entry Point
Copyright (c) 2026 Concord Desk. All rights reserved.
PROPRIETARY AND CONFIDENTIAL.
"""

import os
import re
import asyncio
import logging
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

# Load environment variables
load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")
DISABLE_TUI = os.getenv("DISABLE_TUI", "False").lower() == "true"

console = Console()

# Maximum length for error messages shown in the TUI error panel.
# Full messages are always written to the log file.
_TUI_MSG_MAX_LEN = 200

# ─── Error code extractor ────────────────────────────────────────────────────

_ERR_CODE_RE = re.compile(r'\[ERR-[A-Z]+-\d+\]')

def _extract_err_code(msg: str) -> str:
    m = _ERR_CODE_RE.search(msg)
    return m.group(0) if m else ""

def _strip_err_code(msg: str) -> str:
    return _ERR_CODE_RE.sub("", msg).strip()

# ─── Dashboard Backend ───────────────────────────────────────────────────────

class DashboardState:
    def __init__(self):
        self.status       = "INITIALIZING"
        self.latency      = 0.0
        self.start_time   = datetime.now(IST)
        self.guild_name   = "—"
        self.total_errors = 0

        # Per-system log deques (Rich Text objects)
        self.logs_task    = deque(maxlen=12)
        self.logs_leave   = deque(maxlen=12)
        self.logs_dar     = deque(maxlen=12)
        self.logs_system  = deque(maxlen=12)

        # Clean error log: list of (time_str, code, short_message)
        self.error_log    = deque(maxlen=8)

        # Cog health: name → True (ok) / False (failed) / None (pending)
        self.cog_status   = {
            "Discovery": None,
            "Tasks":     None,
            "Leave":     None,
            "DAR":       None,
        }

    def set_cog_status(self, name: str, ok: bool):
        self.cog_status[name] = ok

dashboard_state = DashboardState()

# ─── Log Handler ─────────────────────────────────────────────────────────────

# Keywords that route to each panel
_TASK_TAGS   = ("[Task]", "[Task Cleanup]", "[Task Queue]",
                "[Task Archive]", "[Task Reminder]", "[Task Cache]", "[Task Config]")
_LEAVE_TAGS  = ("[Leave]",)
_DAR_TAGS    = ("[DAR]",)
_SYSTEM_TAGS = ("[System]", "[Task Config]", "[Leave Config]",
                "[DAR Config]", "[Discovery]", "[DB]")

class DashboardLogHandler(logging.Handler):
    def emit(self, record):
        msg      = self.format(record)
        time_str = datetime.now(IST).strftime("%H:%M:%S")

        # Style by level
        if record.levelno >= logging.ERROR:
            style = "bold red"
        elif record.levelno == logging.WARNING:
            style = "yellow"
        elif record.levelno == logging.INFO:
            style = "white"
        else:
            style = "dim white"

        formatted = Text(f"[{time_str}]  {msg}", style=style, no_wrap=True, overflow="ellipsis")

        # Route to correct panel
        if any(tag in msg for tag in _TASK_TAGS):
            dashboard_state.logs_task.append(formatted)
        elif any(tag in msg for tag in _LEAVE_TAGS):
            dashboard_state.logs_leave.append(formatted)
        elif any(tag in msg for tag in _DAR_TAGS):
            dashboard_state.logs_dar.append(formatted)
        else:
            dashboard_state.logs_system.append(formatted)

        # Collect errors cleanly — no raw tracebacks (those go to the log file)
        if record.levelno >= logging.ERROR:
            dashboard_state.total_errors += 1
            code      = _extract_err_code(msg)
            short_msg = _strip_err_code(msg)
            if len(short_msg) > _TUI_MSG_MAX_LEN:
                short_msg = short_msg[:_TUI_MSG_MAX_LEN - 1] + "…"
            dashboard_state.error_log.append((time_str, code, short_msg))


logger = logging.getLogger("Concord")
logger.setLevel(logging.INFO)

# Handler 1: Dashboard UI deques
dash_handler = DashboardLogHandler()
dash_handler.setFormatter(logging.Formatter("%(message)s"))
logger.addHandler(dash_handler)

# Handler 2: Background file log (full detail, with rotation)
from logging.handlers import RotatingFileHandler
file_handler = RotatingFileHandler(
    "Logs/concord_runtime.log",
    mode="a",
    maxBytes=10 * 1024 * 1024,  # 10 MB per file
    backupCount=5
)
file_handler.setFormatter(logging.Formatter("[%(asctime)s] %(levelname)s - %(message)s"))
logger.addHandler(file_handler)

# Handler 3: Stdout (only if TUI is disabled)
if DISABLE_TUI:
    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(logging.Formatter("[%(asctime)s] %(levelname)s - %(message)s"))
    logger.addHandler(stream_handler)

# ─── Layout ──────────────────────────────────────────────────────────────────

def generate_layout() -> Layout:
    layout = Layout()
    layout.split_column(
        Layout(name="header", size=5),
        Layout(name="cogs",   size=3),
        Layout(name="main"),
        Layout(name="errors", size=9),
    )
    layout["main"].split_row(
        Layout(name="left_col"),
        Layout(name="right_col"),
    )
    layout["left_col"].split_column(
        Layout(name="system_box"),
        Layout(name="task_box"),
    )
    layout["right_col"].split_column(
        Layout(name="leave_box"),
        Layout(name="dar_box"),
    )
    return layout

# ─── Render helpers ──────────────────────────────────────────────────────────

def _uptime_str() -> str:
    total = int((datetime.now(IST) - dashboard_state.start_time).total_seconds())
    h, rem = divmod(total, 3600)
    m, s   = divmod(rem, 60)
    return f"{h}h {m:02d}m {s:02d}s"

def _latency_style() -> str:
    lat = dashboard_state.latency
    if lat == 0:
        return "dim white"
    if lat < 100:
        return "bold green"
    if lat < 250:
        return "bold yellow"
    return "bold red"

def _log_panel(entries, title: str, border_style: str) -> Panel:
    if entries:
        content = Group(*entries)
    else:
        content = Text("No recent activity", style="dim italic", justify="center")
    count_label = f"[dim]({len(entries)})[/]  " if entries else ""
    return Panel(
        content,
        title=f"{title}  {count_label}",
        border_style=border_style,
        padding=(0, 1),
    )

# ─── Dashboard Renderer ──────────────────────────────────────────────────────

def render_dashboard() -> Layout:
    layout = generate_layout()

    # ── Status dot ────────────────────────────────────────────────────────────
    status = dashboard_state.status
    if status == "ONLINE":
        dot, status_style = "●", "bold green"
    elif status in ("CONNECTING", "INITIALIZING"):
        dot, status_style = "◐", "bold yellow"
    else:
        dot, status_style = "○", "bold red"

    now_str = datetime.now(IST).strftime("%H:%M:%S IST")
    lat_str = f"{dashboard_state.latency:.0f} ms" if dashboard_state.latency else "— ms"

    # ── Header ────────────────────────────────────────────────────────────────
    header_grid = Table.grid(expand=True, padding=(0, 2))
    header_grid.add_column(justify="left",  ratio=2)
    header_grid.add_column(justify="center", ratio=1)
    header_grid.add_column(justify="right", ratio=2)

    header_grid.add_row(
        Text("  CONCORD UNIFIED ENGINE", style="bold cyan"),
        Text(f"{dot}  {status}", style=status_style),
        Text(now_str, style="dim cyan"),
    )
    header_grid.add_row(
        Text(f"  Guild: {dashboard_state.guild_name}", style="dim white"),
        Text(""),
        Text(
            f"Uptime  {_uptime_str()}     Latency  {lat_str}",
            style=_latency_style(),
        ),
    )
    layout["header"].update(Panel(header_grid, style="bold blue", padding=(0, 1)))

    # ── Cog status bar ────────────────────────────────────────────────────────
    cog_grid = Table.grid(expand=True, padding=(0, 3))
    cog_grid.add_column(justify="center", ratio=1)
    cog_grid.add_column(justify="center", ratio=1)
    cog_grid.add_column(justify="center", ratio=1)
    cog_grid.add_column(justify="center", ratio=1)
    cog_grid.add_column(justify="right",  ratio=1)

    cells = []
    icons = {"Discovery": "🔍", "Tasks": "📋", "Leave": "🌿", "DAR": "📊"}
    for name, ok in dashboard_state.cog_status.items():
        icon = icons.get(name, "")
        if ok is True:
            cells.append(Text(f"{icon} {name}  ✔", style="bold green"))
        elif ok is False:
            cells.append(Text(f"{icon} {name}  ✘", style="bold red"))
        else:
            cells.append(Text(f"{icon} {name}  …", style="dim yellow"))

    err_color = "bold red" if dashboard_state.total_errors > 0 else "dim white"
    cells.append(Text(f"Errors today:  {dashboard_state.total_errors}", style=err_color))
    cog_grid.add_row(*cells)

    layout["cogs"].update(Panel(cog_grid, style="blue", padding=(0, 1)))

    # ── Log panels ────────────────────────────────────────────────────────────
    layout["system_box"].update(_log_panel(
        dashboard_state.logs_system, "[bold magenta]Core & Discovery[/]", "magenta"))
    layout["task_box"].update(_log_panel(
        dashboard_state.logs_task,   "[bold cyan]Task Management[/]",    "cyan"))
    layout["leave_box"].update(_log_panel(
        dashboard_state.logs_leave,  "[bold green]Leave Pipeline[/]",    "green"))
    layout["dar_box"].update(_log_panel(
        dashboard_state.logs_dar,    "[bold yellow]DAR Reporting[/]",    "yellow"))

    # ── Error log (clean, no tracebacks) ──────────────────────────────────────
    err_table = Table(
        show_header=True,
        header_style="bold red",
        border_style="red",
        expand=True,
        show_edge=False,
        padding=(0, 1),
    )
    err_table.add_column("Time",    style="dim white",  width=10, no_wrap=True)
    err_table.add_column("Code",    style="bold red",   width=16, no_wrap=True)
    err_table.add_column("Message", style="white")

    if dashboard_state.error_log:
        for time_s, code, msg in dashboard_state.error_log:
            err_table.add_row(time_s, code or "—", msg)
    else:
        err_table.add_row("—", "—", Text("No errors recorded", style="dim italic"))

    layout["errors"].update(Panel(
        err_table,
        title="[bold red]Recent Errors[/]  [dim](details in Logs/concord_runtime.log)[/]",
        border_style="red",
        padding=(0, 1),
    ))

    return layout

# ─── Bot ─────────────────────────────────────────────────────────────────────

class ConcordBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.members = True
        intents.message_content = True
        super().__init__(
            command_prefix="!",
            intents=intents,
            max_messages=1000,
            member_cache_flags=discord.MemberCacheFlags.from_intents(intents),
        )
        self.help_command = None
        self._error_count = 0
        self._last_error_time = None
        self._circuit_breaker_threshold = 10
        self._circuit_breaker_window    = 300

    def _check_circuit_breaker(self):
        now = datetime.now()
        if self._last_error_time and (now - self._last_error_time) > timedelta(seconds=self._circuit_breaker_window):
            self._error_count = 0
        self._error_count += 1
        self._last_error_time = now
        return self._error_count >= self._circuit_breaker_threshold

    async def setup_hook(self):
        logger.info("[System] Initializing modules...")
        discovery_cog  = "cogs.discovery_cog"
        dependent_cogs = {
            "cogs.task_cog":  "Tasks",
            "cogs.leave_cog": "Leave",
            "cogs.dar_cog":   "DAR",
        }
        try:
            await self.load_extension(discovery_cog)
            dashboard_state.set_cog_status("Discovery", True)
            logger.info(f"[System] ✔ Ext: {discovery_cog} active.")
        except Exception as e:
            dashboard_state.set_cog_status("Discovery", False)
            logger.critical(
                f"[ERR-COR-001] [System] ✘ Failed to load {discovery_cog}: {e}. "
                "Aborting dependent cog load — bot cannot function without discovery."
            )
            return
        for cog, label in dependent_cogs.items():
            try:
                await self.load_extension(cog)
                dashboard_state.set_cog_status(label, True)
                logger.info(f"[System] ✔ Ext: {cog} active.")
            except Exception as e:
                dashboard_state.set_cog_status(label, False)
                logger.error(f"[ERR-COR-001] [System] ✘ Failed to load {cog}: {e}")

    async def on_ready(self):
        dashboard_state.status = "ONLINE"
        if self.guilds:
            dashboard_state.guild_name = self.guilds[0].name
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
        if self._check_circuit_breaker():
            logger.error(f"[ERR-COR-099] Circuit breaker active — too many errors. Event: {event}")
            return
        logger.exception(f"[ERR-COR-099] Unhandled exception in {event}")

    async def on_command_error(self, ctx, error):
        if isinstance(error, commands.CommandNotFound):
            return
        elif isinstance(error, commands.MissingPermissions):
            await ctx.send("❌ You don't have permission to use this command.", delete_after=10)
        elif isinstance(error, commands.BotMissingPermissions):
            logger.error(f"[ERR-COR-100] Bot missing permissions: {error}")
        else:
            logger.exception(f"[ERR-COR-101] Command error: {error}")

# ─── Entry Point ─────────────────────────────────────────────────────────────

async def main():
    # Fail fast if any required environment variable is missing
    _required_env = {
        "BOT_TOKEN":    BOT_TOKEN,
        "DB_HOST":      os.getenv("DB_HOST"),
        "DB_PORT":      os.getenv("DB_PORT"),
        "DB_NAME":      os.getenv("DB_NAME"),
        "DB_USER":      os.getenv("DB_USER"),
        "DB_PASSWORD":  os.getenv("DB_PASSWORD"),
    }
    missing = [k for k, v in _required_env.items() if not v or not str(v).strip()]
    if missing:
        print(f"CRITICAL: Missing required environment variables: {', '.join(missing)}")
        return

    bot = ConcordBot()

    async def ping_updater():
        while not bot.is_closed():
            if bot.latency:
                dashboard_state.latency = round(bot.latency * 1000, 2)
            await asyncio.sleep(2)

    if DISABLE_TUI:
        logger.info("TUI Disabled. Running in headless mode.")
        async with bot:
            asyncio.create_task(ping_updater())
            await bot.start(BOT_TOKEN)
    else:
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
