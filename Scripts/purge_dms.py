#!/usr/bin/env python3
"""
purge_dms.py — Standalone utility to purge DMs sent by the bot.
Copyright (c) 2026 Concord Desk. All rights reserved.
"""

import os
import asyncio
import logging
from dotenv import load_dotenv
import discord

# Load environment variables
load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")

# Setup logging
logging.basicConfig(level=logging.INFO, format="[%(levelname)s] %(message)s")
logger = logging.getLogger("PurgeDMs")

# DRY_RUN mode: Set to False to actually delete messages
DRY_RUN = os.getenv("DRY_RUN", "True").lower() == "True"

class DMScanner(discord.Client):
    def __init__(self, *args, **kwargs):
        intents = discord.Intents.default()
        intents.members = True
        intents.message_content = True
        super().__init__(intents=intents, *args, **kwargs)

    async def on_ready(self):
        logger.info(f"Logged in as {self.user} (ID: {self.user.id})")
        logger.info(f"Dry Run Mode: {DRY_RUN}")
        
        total_deleted = 0
        total_channels = 0
        
        logger.info("Scanning for DM channels via known members...")
        
        # Collect all unique users across all guilds
        users = set()
        for guild in self.guilds:
            for member in guild.members:
                if not member.bot:
                    users.add(member)
        
        logger.info(f"Found {len(users)} unique users across {len(self.guilds)} guilds.")
        
        for user in users:
            try:
                # This doesn't send a message, just gets or creates the DM channel object
                channel = user.dm_channel
                if channel is None:
                    # We might need to create it to see if there's history
                    # But if we create it for everyone, it might be excessive.
                    # However, history() will only have messages if the bot already sent some.
                    channel = await user.create_dm()
                
                total_channels += 1
                logger.info(f"Scanning DM history with {user} (ID: {user.id})")
                
                count = 0
                async for message in channel.history(limit=None):
                    if message.author == self.user:
                        count += 1
                        if not DRY_RUN:
                            try:
                                await message.delete()
                                await asyncio.sleep(0.5) # Avoid rate limits
                            except discord.HTTPException as e:
                                logger.error(f"Failed to delete message to {user}: {e}")
                
                if count > 0:
                    logger.info(f"Found {count} messages from bot in DM with {user}")
                total_deleted += count
            except discord.Forbidden:
                logger.warning(f"Cannot access DMs for {user}")
            except Exception as e:
                logger.error(f"Error scanning DMs for {user}: {e}")

        logger.info("-" * 40)
        if DRY_RUN:
            logger.info(f"DRY RUN COMPLETE: Would have deleted {total_deleted} messages across {total_channels} DM channels.")
        else:
            logger.info(f"PURGE COMPLETE: Deleted {total_deleted} messages across {total_channels} DM channels.")
        
        await self.close()

async def main():
    if not BOT_TOKEN:
        logger.error("BOT_TOKEN missing in .env")
        return

    client = DMScanner()
    async with client:
        await client.start(BOT_TOKEN)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
    except Exception as e:
        logger.error(f"Fatal error: {e}")
