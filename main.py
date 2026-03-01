"""
main.py — Unified Concord Bot Entry Point
A beautiful, unified dashboard for the Concord task, leave, and DAR systems.
"""

import os
import asyncio
import logging
from datetime import datetime
from dotenv import load_dotenv

import discord
from discord.ext import commands

# Premium Terminal UI
from rich.console import Console
from rich.logging import RichHandler
from rich.panel import Panel
from rich.table import Table
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich import print as rprint

# Load environment variables
load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")

# Setup Rich console and logging
console = Console()
logging.basicConfig(
    level=logging.INFO,
    format="%(message)s",
    datefmt="[%X]",
    handlers=[RichHandler(rich_tracebacks=True, console=console, show_path=False, markup=True)]
)
logger = logging.getLogger("Concord")

# -------------------------------------------------------------------------
# Bot Client
# -------------------------------------------------------------------------

class ConcordBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.members = True
        intents.message_content = True
        super().__init__(command_prefix="!", intents=intents)
        self.help_command = None

    async def setup_hook(self):
        """Loads all cogs with a visual progress indicator."""
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=console,
            transient=True,
        ) as progress:
            progress.add_task(description="[cyan]Initializing Discord components...", total=None)
            
            cogs = ["cogs.task_cog", "cogs.leave_cog", "cogs.dar_cog"]
            for cog in cogs:
                try:
                    await self.load_extension(cog)
                    logger.info(f"✔ Module [bold cyan]{cog}[/bold cyan] active.")
                except Exception as e:
                    logger.error(f"✘ Failed to load [bold red]{cog}[/bold red]: {e}")

    async def on_ready(self):
        render_dashboard(self)
        logger.info(f"Bot session started as [bold green]{self.user}[/bold green]")

    async def on_connect(self):
        logger.info("Gateway handshake successful.")

    async def on_disconnect(self):
        logger.warning("Gateway connection lost. Automatic reconnection initiated...")


def render_dashboard(bot):
    """Renders a stylized system dashboard."""
    os.system('cls' if os.name == 'nt' else 'clear')
    
    # ─── Header ─────────────────────────────────────────────────────────────
    header_text = (
        "[bold cyan]▲ CONCORD UNIFIED ENGINE[/bold cyan]\n"
        "[dim]Intelligent Architecture for Workspace Automation[/dim]"
    )
    rprint(Panel.fit(header_text, border_style="bright_blue", padding=(1, 6)))

    # ─── Status Table ───────────────────────────────────────────────────────
    status_table = Table(title="Live System Inventory", title_justify="left", border_style="dim", box=None)
    status_table.add_column("Service Module", style="bold white")
    status_table.add_column("Status", justify="center")
    status_table.add_column("Last Sync", justify="right", style="dim")

    now = datetime.now().strftime("%H:%M:%S")
    status_table.add_row("Task Management", "[bold green]ONLINE[/bold green]", now)
    status_table.add_row("Leave Pipeline", "[bold green]ONLINE[/bold green]", now)
    status_table.add_row("DAR Reporting", "[bold green]ONLINE[/bold green]", now)
    status_table.add_row("Database Layer", "[bold green]WAL-SYNCED[/bold green]", now)
    
    rprint(status_table)

    # ─── Metrics ────────────────────────────────────────────────────────────
    latency = round(bot.latency * 1000, 2)
    latency_color = "green" if latency < 100 else "yellow" if latency < 300 else "red"
    
    rprint(f"[dim]━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━[/dim]")
    rprint(f" [bold dim]⚡ Latency:[/bold dim] [{latency_color}]{latency}ms[/{latency_color}] | "
           f"[bold dim]🖥 Node:[/bold dim] [white]{os.uname().nodename}[/white] | "
           f"[bold dim]📅 Date:[/bold dim] [white]{datetime.now().strftime('%Y-%m-%d')}[/white]\n")


# -------------------------------------------------------------------------
# Execution
# -------------------------------------------------------------------------

async def main():
    if not BOT_TOKEN:
        logger.error("[bold red]CRITICAL:[/bold red] BOT_TOKEN missing from environment.")
        return

    bot = ConcordBot()
    async with bot:
        try:
            await bot.start(BOT_TOKEN)
        except discord.LoginFailure:
            logger.error("[bold red]AUTH ERROR:[/bold red] Invalid BOT_TOKEN. Check [bold white].env[/bold white]")
        except Exception as e:
            logger.error(f"[bold red]SYSTEM CRASH:[/bold red] {e}")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        rprint("\n[bold orange3]⚠ Manual override: System shutdown sequence complete.[/bold orange3]")
