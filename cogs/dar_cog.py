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

# IDs of the relevant roles
DAR_SUBMITTED_ROLE_ID = 1281317724294877236
ON_LEAVE_ROLE_ID = 1284784204403707914
PA_ROLE_ID = 1281170902368784385
DAR_CHANNEL_ID = 1282571345850400768
DAR_EXCLUDE_ROLE_ID = 1282590818376482816

# Linux-compatible log directory
DAR_LOG_DIRECTORY = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'Database', 'DAR exports'))


class DARCog(commands.Cog, name="DAR"):
    """Assigns DAR Submitted role and sends reminders."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._last_reminder_hour = None

    # -------------------------------------------------------------------------
    # Lifecycle
    # -------------------------------------------------------------------------

    async def cog_load(self):
        """Called automatically when the cog is loaded."""
        asyncio.ensure_future(self.check_role_expiry())

    # -------------------------------------------------------------------------
    # Background loop
    # -------------------------------------------------------------------------

    async def check_role_expiry(self):
        """Periodically checks for role expiry and sends reminders."""
        await self.bot.wait_until_ready()
        while not self.bot.is_closed():
            now = datetime.datetime.now()
            logging.info(f"[DAR] Current time: {now}")

            # Remove DAR Submitted role at 11:00 AM daily
            if now.hour == 11 and now.minute == 0:
                logging.info("[DAR] 11:00 AM — handling role removal.")
                await self.handle_role_removal()

            # Send DAR reminders every hour from 7 PM to 10 PM (except Sundays)
            if now.weekday() != 6 and 19 <= now.hour <= 22 and now.minute == 0:
                if self._last_reminder_hour != now.hour:
                    logging.info(f"[DAR] Sending reminders at {now.hour}:00")
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
                    logging.info(f"[DAR] Removed role {role.name} from {member.name}")
            except discord.Forbidden:
                logging.error(f"[DAR] Missing permissions to remove role from {member.name}")
            except Exception as e:
                logging.error(f"[DAR] Error processing {member.name}: {e}")

        await self.log_dar_submissions(removed_members)

    async def log_dar_submissions(self, members: list):
        """Logs the list of members who had DAR Submitted removed to a file."""
        os.makedirs(DAR_LOG_DIRECTORY, exist_ok=True)
        date_str = datetime.datetime.now().strftime("%Y-%m-%d")
        log_path = os.path.join(DAR_LOG_DIRECTORY, f"dar_submissions_{date_str}.txt")
        with open(log_path, "w") as f:
            f.write("DAR Submissions removed at 11:00 AM:\n")
            for member in members:
                f.write(f"{member}\n")
        logging.info(f"[DAR] Submissions logged to {log_path}")

    async def send_dar_reminders(self):
        """DMs all members who haven't submitted their DAR yet."""
        for member in self.bot.get_all_members():
            role_ids = [role.id for role in member.roles]
            if (
                member.id != self.bot.user.id
                and DAR_SUBMITTED_ROLE_ID not in role_ids
                and PA_ROLE_ID not in role_ids
                and ON_LEAVE_ROLE_ID not in role_ids
                and DAR_EXCLUDE_ROLE_ID not in role_ids
            ):
                try:
                    await member.send("Reminder: You haven't submitted your D.A.R yet.")
                    logging.info(f"[DAR] Sent reminder to {member.name}")
                    await asyncio.sleep(1)
                except discord.Forbidden:
                    logging.warning(f"[DAR] Cannot DM {member.name} (DMs disabled).")
                except Exception as e:
                    logging.error(f"[DAR] Error DMing {member.name}: {e}")

    # -------------------------------------------------------------------------
    # Event listeners
    # -------------------------------------------------------------------------

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        """Assigns DAR Submitted role when an embed is posted in the DAR channel."""
        if message.channel.id != DAR_CHANNEL_ID:
            return
        if not message.embeds:
            return

        embed = message.embeds[0]
        author_name = embed.author.name
        guild = message.guild
        if guild is None:
            return

        member = guild.get_member_named(author_name)
        if member:
            role = discord.utils.get(guild.roles, id=DAR_SUBMITTED_ROLE_ID)
            if role:
                await member.add_roles(role)
                logging.info(f"[DAR] Assigned role {role.name} to {author_name}")
            else:
                logging.error(f"[DAR] Role {DAR_SUBMITTED_ROLE_ID} not found in guild.")
        else:
            logging.error(f"[DAR] Member '{author_name}' not found in guild.")


async def setup(bot: commands.Bot):
    await bot.add_cog(DARCog(bot))
