"""
cogs/dar_cog.py — DAR (Daily Activity Report) Cog
Copyright (c) 2026 Concord Desk. All rights reserved.
PROPRIETARY AND CONFIDENTIAL.
"""

import asyncio
import datetime
import logging
import os
import discord
from discord.ext import commands

from Bots.utils.timezone import now_ist
from Bots.db_managers import discovery_db_manager as discovery

# Live config — populated by resolve_dar_config() on bot startup
DAR_SUBMITTED_ROLE_ID = 1281317724294877236
ON_LEAVE_ROLE_ID      = 1284784204403707914
PA_ROLE_ID            = 1281170902368784385
DAR_EXCLUDE_ROLE_ID   = 1282590818376482816

# Channel where employees post their DARs
DAR_CHANNEL_ID = 1281200069416321096

# Linux-compatible log directory
DAR_LOG_DIRECTORY = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'Database', 'DAR exports'))


async def resolve_dar_config():
    """
    Queries discovery.db to resolve role IDs by name.
    Ensures the bot stays 'living' even after a DB reset.
    """
    global DAR_SUBMITTED_ROLE_ID, ON_LEAVE_ROLE_ID, PA_ROLE_ID, DAR_EXCLUDE_ROLE_ID

    logger = logging.getLogger("Concord")

    mappings = {
        'DAR_SUBMITTED_ROLE_ID': 'DAR Submitted',
        'ON_LEAVE_ROLE_ID':      'On Leave',
        'PA_ROLE_ID':            'PA',
        'DAR_EXCLUDE_ROLE_ID':   'DAR Exclude',
    }

    for var_name, role_name in mappings.items():
        resolved = await discovery.get_role_id_by_name(role_name)
        if resolved:
            globals()[var_name] = resolved
            logger.info(f"[DAR Config] @{role_name} → {resolved}")

    logger.info("[DAR Config] Configuration resolved from discovery.db.")


class DARCog(commands.Cog, name="DAR"):
    """Handles DAR role assignment, discussion threads, and submission reminders."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._last_reminder_hour = None
        self._bg_task = None
        self.logger = logging.getLogger("Concord")

    # -------------------------------------------------------------------------
    # Lifecycle
    # -------------------------------------------------------------------------

    async def cog_unload(self):
        if self._bg_task:
            self._bg_task.cancel()

    async def cog_load(self):
        if not hasattr(self.bot, 'discovery_complete'):
            self.bot.discovery_complete = asyncio.Event()

    @commands.Cog.listener()
    async def on_ready(self):
        await self.bot.discovery_complete.wait()
        await resolve_dar_config()
        self._bg_task = asyncio.create_task(self.check_role_expiry())

    # -------------------------------------------------------------------------
    # Message listener — role assignment + thread creation
    # -------------------------------------------------------------------------

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        """Handles DAR submissions posted directly in the DAR channel."""
        if message.author.bot:
            return
        if message.channel.id != DAR_CHANNEL_ID:
            return

        member = message.author
        guild  = message.guild
        if not guild:
            return

        # Assign DAR Submitted role (skip if already held)
        role = discord.utils.get(guild.roles, id=DAR_SUBMITTED_ROLE_ID)
        if role and role not in member.roles:
            try:
                await member.add_roles(role)
                self.logger.info(f"[DAR] Assigned DAR Submitted role to {member.display_name}.")
            except discord.Forbidden:
                self.logger.error(f"[ERR-DAR-001] [DAR] Missing permission to assign role to {member.display_name}.")
            except Exception as e:
                self.logger.error(f"[ERR-DAR-002] [DAR] Failed to assign role to {member.display_name}: {e}")

        # Create a public discussion thread on the post
        try:
            await message.create_thread(
                name=f"Discussion — {member.display_name}",
                auto_archive_duration=1440,  # 24 hours
            )
            self.logger.info(f"[DAR] Created discussion thread for {member.display_name}.")
        except discord.Forbidden:
            self.logger.error(f"[ERR-DAR-003] [DAR] Missing permission to create thread in DAR channel.")
        except discord.HTTPException as e:
            self.logger.error(f"[ERR-DAR-004] [DAR] Failed to create thread for {member.display_name}: {e}")

    # -------------------------------------------------------------------------
    # Background loop
    # -------------------------------------------------------------------------

    async def check_role_expiry(self):
        """Periodically checks for role expiry and sends reminders."""
        await self.bot.wait_until_ready()
        while not self.bot.is_closed():
            now = now_ist()

            # Remove DAR Submitted role at 11:00 AM IST daily
            if now.hour == 11 and now.minute == 0:
                self.logger.info("[DAR] 11:00 AM IST — handling role removal.")
                await self.handle_role_removal()

            # Send DAR reminders every hour from 7 PM to 10 PM IST (except Sundays)
            if now.weekday() != 6 and 19 <= now.hour <= 22 and now.minute == 0:
                if self._last_reminder_hour != now.hour:
                    self.logger.info(f"[DAR] Sending reminders at {now.hour}:00 IST.")
                    await self.send_dar_reminders()
                    self._last_reminder_hour = now.hour

            await asyncio.sleep(60)

    # -------------------------------------------------------------------------
    # Role management
    # -------------------------------------------------------------------------

    async def handle_role_removal(self):
        """Removes the DAR Submitted role from all members at 11:00 AM."""
        removed_members = []
        for member in self.bot.get_all_members():
            try:
                if DAR_SUBMITTED_ROLE_ID in [role.id for role in member.roles]:
                    role = discord.utils.get(member.guild.roles, id=DAR_SUBMITTED_ROLE_ID)
                    await member.remove_roles(role)
                    removed_members.append(member.name)
                    self.logger.info(f"[DAR] Removed role {role.name} from {member.name}.")
                    await asyncio.sleep(0.5)  # Rate limit protection: 2 ops/sec
            except discord.Forbidden:
                self.logger.error(f"[ERR-DAR-005] [DAR] Missing permission to remove role from {member.name}.")
            except discord.HTTPException as e:
                if e.status == 429:
                    retry_after = e.retry_after if hasattr(e, 'retry_after') else 5
                    self.logger.warning(f"[DAR] Rate limited. Waiting {retry_after}s...")
                    await asyncio.sleep(retry_after)
                else:
                    self.logger.error(f"[ERR-DAR-006] [DAR] HTTP error processing {member.name}: {e}")
            except Exception as e:
                self.logger.error(f"[ERR-DAR-007] [DAR] Error processing {member.name}: {e}")

        await self.log_dar_submissions(removed_members)

    async def log_dar_submissions(self, members: list):
        """Logs the list of members who had DAR Submitted removed to a file."""
        os.makedirs(DAR_LOG_DIRECTORY, exist_ok=True)
        date_str = now_ist().strftime("%Y-%m-%d")
        log_path = os.path.join(DAR_LOG_DIRECTORY, f"dar_submissions_{date_str}.txt")
        with open(log_path, "w") as f:
            f.write("DAR Submissions removed at 11:00 AM:\n")
            for member in members:
                f.write(f"{member}\n")
        self.logger.info(f"[DAR] Submissions logged to {log_path}.")

    async def send_dar_reminders(self):
        """DMs all members who haven't submitted their DAR yet."""
        for member in self.bot.get_all_members():
            role_ids = [role.id for role in member.roles]
            if (
                member.id != self.bot.user.id
                and DAR_SUBMITTED_ROLE_ID not in role_ids
                and PA_ROLE_ID            not in role_ids
                and ON_LEAVE_ROLE_ID      not in role_ids
                and DAR_EXCLUDE_ROLE_ID   not in role_ids
            ):
                try:
                    await member.send("Reminder: You haven't submitted your D.A.R yet.")
                    self.logger.info(f"[DAR] Sent reminder to {member.name}.")
                    await asyncio.sleep(1.0)  # Rate limit: max 1 DM per second
                except discord.Forbidden:
                    self.logger.warning(f"[ERR-DAR-008] [DAR] Cannot DM {member.name} (DMs disabled).")
                except discord.HTTPException as e:
                    if e.status == 429:
                        retry_after = e.retry_after if hasattr(e, 'retry_after') else 5
                        self.logger.warning(f"[DAR] Rate limited on DM. Waiting {retry_after}s...")
                        await asyncio.sleep(retry_after)
                    else:
                        self.logger.error(f"[ERR-DAR-009] [DAR] HTTP error DMing {member.name}: {e}")
                except Exception as e:
                    self.logger.error(f"[ERR-DAR-010] [DAR] Error DMing {member.name}: {e}")


async def setup(bot):
    await bot.add_cog(DARCog(bot))
