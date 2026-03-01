"""
main.py — Unified Concord Bot entry point
Loads Task, Leave, and DAR cogs into a single Discord bot process.
"""

import asyncio
import logging
import os
import sys

import discord
from discord.ext import commands

# ─── Logging ─────────────────────────────────────────────────────────────────
logging.basicConfig(level=logging.DEBUG)

# ─── Intents ─────────────────────────────────────────────────────────────────
intents = discord.Intents.default()
intents.members = True
intents.message_content = True
intents.messages = True


# ─── Bot with exponential backoff reconnect (from original Task.py) ───────────
class ConcordBot(commands.Bot):
    async def connect(self, *, reconnect=True):
        backoff = 1
        while not self.is_closed():
            try:
                await super().connect(reconnect=reconnect)
                backoff = 1
            except (OSError, discord.GatewayNotFound, discord.ConnectionClosed, discord.HTTPException) as exc:
                logging.error(f"Connection error: {exc}. Reconnecting in {backoff}s...")
                if not reconnect:
                    await self.close()
                    if isinstance(exc, discord.ConnectionClosed):
                        raise
                    return
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 60)
            except asyncio.TimeoutError:
                logging.error(f"Connection timed out. Reconnecting in {backoff}s...")
                if not reconnect:
                    await self.close()
                    return
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 60)


bot = ConcordBot(command_prefix="!", intents=intents)


# ─── Events ───────────────────────────────────────────────────────────────────
@bot.event
async def on_disconnect():
    logging.warning("Bot disconnected from Discord.")

@bot.event
async def on_resumed():
    logging.info("Bot reconnected to Discord.")


# ─── Startup ─────────────────────────────────────────────────────────────────
async def main():
    token = os.getenv("BOT_TOKEN")
    if not token:
        raise ValueError(
            "BOT_TOKEN environment variable not set.\n"
            "Run: export BOT_TOKEN=your_token_here\n"
            "Or copy .env.example → .env and set the value."
        )

    async with bot:
        await bot.load_extension("cogs.task_cog")
        await bot.load_extension("cogs.leave_cog")
        await bot.load_extension("cogs.dar_cog")
        logging.info("All cogs loaded. Starting bot...")
        await bot.start(token)


if __name__ == "__main__":
    asyncio.run(main())
